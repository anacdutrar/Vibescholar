"""Isolated tests for the EvidenceService workflow facade integration."""

import ast
import asyncio
import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.schemas import EvidenceAnalysisScope, EvidenceEvaluation, EvidenceVerdict
from app.core.config import settings
from app.core.database import Base
from app.models.document import Document, DocumentVersion
from app.models.project_settings import ProjectSettings
from app.models.reference import EvidenceSuggestion, ProjectReference
from app.models.user import Project, User
from app.repositories.reference_repository import ReferenceRepository
from app.schemas.response import EvidenceSuggestionOut
from app.services.evidence_search_state import (
    EvidenceSearchSession,
    EvidenceSearchSessionStore,
    SearchSessionStatus,
)
from app.services.evidence_search_workflow import (
    EvidenceSearchRoundResult,
    RoundResultSource,
    summarize_evaluations,
)
from app.services.evidence_service import EvidenceService
from app.tools.schemas import CandidateEvaluationStatus, EvidenceSearchCandidate, ReferenceCandidate


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def db_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="sprint6", password_hash="hash")
    session.add(user)
    session.flush()
    project = Project(user_id=user.id, name="AI integration")
    session.add(project)
    session.flush()
    project_settings = ProjectSettings(project_id=project.id, max_suggestions=1)
    session.add(project_settings)
    session.flush()
    document = Document(project_id=project.id, title="Document", content="Claim.")
    session.add(document)
    session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        content_snapshot="Claim.",
        created_by="sprint6",
    )
    session.add(version)
    session.commit()
    yield session, user, project, version
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def candidate(index: int) -> ReferenceCandidate:
    return ReferenceCandidate(
        provider="openalex",
        external_id=f"work-{index}",
        title=f"Evidence work {index}",
        authors=[f"Author {index}"],
        year=2020 + index,
        doi=f"10.1000/work.{index}",
        abstract=f"Supporting abstract {index}.",
        is_open_access=True,
    )


def evaluation(item: ReferenceCandidate, verdict: EvidenceVerdict) -> EvidenceEvaluation:
    return EvidenceEvaluation(
        candidate_key=item.candidate_key,
        verdict=verdict,
        confidence=0.9,
        reason="Typed evaluator result.",
        analysis_scope=EvidenceAnalysisScope.TITLE_AND_ABSTRACT,
    )


def transient(item: ReferenceCandidate, verdict: EvidenceVerdict) -> EvidenceSearchCandidate:
    return EvidenceSearchCandidate(
        reference=item,
        provider=item.provider,
        search_round=1,
        evaluation_status=CandidateEvaluationStatus.EVALUATED,
        verdict=verdict,
        confidence=0.9,
        reason="Typed evaluator result.",
        analysis_scope=EvidenceAnalysisScope.TITLE_AND_ABSTRACT,
    )


def round_result(evaluations: list[EvidenceEvaluation]) -> EvidenceSearchRoundResult:
    return EvidenceSearchRoundResult(
        session_status=SearchSessionStatus.ACTIVE,
        round_number=1,
        source=RoundResultSource.NEW_SEARCH,
        evaluation_summary=summarize_evaluations(evaluations),
        evaluations=evaluations,
        reserved_candidate_keys=tuple(item.candidate_key for item in evaluations),
        target_reached=False,
        refinement_recommended=False,
    )


class WorkflowStub:
    def __init__(self, store, sessions_and_results):
        self.store = store
        self.sessions_and_results = list(sessions_and_results)
        self.calls = []

    async def execute_round(self, **kwargs):
        self.calls.append(kwargs)
        session, result = self.sessions_and_results.pop(0)
        await self.store.set(
            (kwargs["user_id"], kwargs["document_version_id"], kwargs["sentence_uuid"]),
            session,
        )
        return result


class LegacyStub:
    def __init__(self):
        self.calls = 0

    def search_references(self, *args, **kwargs):
        self.calls += 1
        return []


def session_for(items_with_verdicts):
    session = EvidenceSearchSession(current_round=1)
    evaluations = []
    for item, verdict in items_with_verdicts:
        session.candidates[item.candidate_key] = transient(item, verdict)
        session.evaluated_candidate_keys.add(item.candidate_key)
        if verdict is EvidenceVerdict.STRONG_SUPPORT:
            session.strong_support_keys.add(item.candidate_key)
        elif verdict is EvidenceVerdict.PARTIAL_SUPPORT:
            session.partial_support_keys.add(item.candidate_key)
        evaluations.append(evaluation(item, verdict))
    return session, evaluations


def call_service(service, db_context):
    db, user, project, version = db_context
    return service.search(
        db,
        "A bounded scientific claim.",
        project.id,
        user_id=user.id,
        document_version_id=version.id,
        sentence_uuid="sentence-sprint6",
    )


def test_real_facade_persists_only_support_and_presents_only_public_items(
    monkeypatch, db_context
):
    monkeypatch.setattr(settings, "USE_MOCK", False)
    items = [candidate(index) for index in range(5)]
    verdicts = list(EvidenceVerdict)
    session, evaluations = session_for(list(zip(items, verdicts, strict=True)))
    store = EvidenceSearchSessionStore()
    workflow = WorkflowStub(store, [(session, round_result(evaluations))])
    service = EvidenceService(workflow=workflow, session_store=store)

    response = run(call_service(service, db_context))

    db, user, project, version = db_context
    assert len(workflow.calls) == 1
    assert len(response) == 1
    assert response[0].status == "PENDING"
    assert db.query(ProjectReference).count() == 2
    assert db.query(EvidenceSuggestion).count() == 1
    assert all(item.status == "PENDING" for item in db.query(EvidenceSuggestion).all())
    stored = run(store.get((user.id, version.id, "sentence-sprint6")))
    assert stored.candidates[items[0].candidate_key].shown_to_user is True
    assert stored.candidates[items[1].candidate_key].shown_to_user is False
    assert stored.presented_candidate_keys == {items[0].candidate_key}
    assert items[1].candidate_key in stored.partial_support_keys


def test_reserve_reuses_reference_and_creates_suggestion_later(monkeypatch, db_context):
    monkeypatch.setattr(settings, "USE_MOCK", False)
    strong, partial = candidate(1), candidate(2)
    first_session, first_evaluations = session_for(
        [(strong, EvidenceVerdict.STRONG_SUPPORT), (partial, EvidenceVerdict.PARTIAL_SUPPORT)]
    )
    second_session = first_session
    second_evaluations = [evaluation(partial, EvidenceVerdict.PARTIAL_SUPPORT)]
    store = EvidenceSearchSessionStore()
    workflow = WorkflowStub(
        store,
        [
            (first_session, round_result(first_evaluations)),
            (second_session, round_result(second_evaluations)),
        ],
    )
    service = EvidenceService(workflow=workflow, session_store=store)

    first = run(call_service(service, db_context))
    second = run(call_service(service, db_context))

    db, _, _, _ = db_context
    assert first[0].reference.title == strong.title
    assert second[0].reference.title == partial.title
    assert db.query(ProjectReference).count() == 2
    assert db.query(EvidenceSuggestion).count() == 2
    assert len({row.reference_id for row in db.query(EvidenceSuggestion).all()}) == 2


def test_public_schema_failure_keeps_reference_and_reserve_unpresented(
    monkeypatch, db_context
):
    monkeypatch.setattr(settings, "USE_MOCK", False)
    item = candidate(1)
    session, evaluations = session_for([(item, EvidenceVerdict.STRONG_SUPPORT)])
    store = EvidenceSearchSessionStore()
    workflow = WorkflowStub(store, [(session, round_result(evaluations))])
    service = EvidenceService(workflow=workflow, session_store=store)

    def fail_validation(*args, **kwargs):
        raise ValueError("public schema failure")

    monkeypatch.setattr(EvidenceSuggestionOut, "model_validate", fail_validation)
    with pytest.raises(ValueError, match="public schema failure"):
        run(call_service(service, db_context))

    db, user, _, version = db_context
    assert db.query(ProjectReference).count() == 1
    assert db.query(EvidenceSuggestion).count() == 0
    stored = run(store.get((user.id, version.id, "sentence-sprint6")))
    assert stored.presented_candidate_keys == set()
    assert stored.candidates[item.candidate_key].shown_to_user is False


def test_suggestion_persistence_failure_does_not_mark_presented(monkeypatch, db_context):
    monkeypatch.setattr(settings, "USE_MOCK", False)
    item = candidate(1)
    session, evaluations = session_for([(item, EvidenceVerdict.STRONG_SUPPORT)])
    store = EvidenceSearchSessionStore()
    workflow = WorkflowStub(store, [(session, round_result(evaluations))])
    service = EvidenceService(workflow=workflow, session_store=store)

    def fail_stage(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("controlled"))

    monkeypatch.setattr(ReferenceRepository, "get_or_stage_pending_suggestion", fail_stage)
    with pytest.raises(IntegrityError):
        run(call_service(service, db_context))

    db, user, _, version = db_context
    assert db.query(ProjectReference).count() == 1
    assert db.query(EvidenceSuggestion).count() == 0
    stored = run(store.get((user.id, version.id, "sentence-sprint6")))
    assert stored.presented_candidate_keys == set()


def test_mock_mode_never_calls_real_workflow(monkeypatch, db_context):
    monkeypatch.setattr(settings, "USE_MOCK", True)
    store = EvidenceSearchSessionStore()
    workflow = WorkflowStub(store, [])
    legacy = LegacyStub()
    service = EvidenceService(
        workflow=workflow,
        session_store=store,
        legacy_search=legacy,
    )

    response = run(call_service(service, db_context))

    assert response == []
    assert workflow.calls == []
    assert legacy.calls == 1


def test_completed_session_is_retained_while_support_reserve_is_unpresented():
    async def scenario():
        item = candidate(1)
        session, _ = session_for([(item, EvidenceVerdict.STRONG_SUPPORT)])
        session.status = SearchSessionStatus.COMPLETED
        store = EvidenceSearchSessionStore()
        key = (1, 1, "completed-reserve")
        await store.set(key, session)
        async with store.search_guard(key):
            pass
        retained = await store.get(key)
        assert retained is session
        assert retained.candidates[item.candidate_key].shown_to_user is False

    run(scenario())


def test_evidence_service_is_facade_not_agent_or_provider_client():
    source = inspect.getsource(__import__("app.services.evidence_service", fromlist=["*"]))
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "SearchAgent" not in imported
    assert "OpenAlexProvider" not in imported
    assert "SemanticScholarProvider" not in imported
    assert "httpx" not in imported


def test_public_contract_fields_are_preserved():
    assert set(EvidenceSuggestionOut.model_fields) == {
        "id",
        "document_version_id",
        "sentence_uuid",
        "reference_id",
        "status",
        "created_at",
        "reference",
    }
