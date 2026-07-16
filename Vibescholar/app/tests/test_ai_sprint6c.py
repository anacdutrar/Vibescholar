"""Hardening tests for terminal sources and real evidence-service integration."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.schemas import (
    EvidenceAnalysisScope,
    EvidenceEvaluation,
    EvidenceEvaluationBatch,
    EvidenceVerdict,
    SearchToolName,
    SentenceType,
)
from app.app import fastapi_app
from app.core.config import settings
from app.core.database import Base, get_db
from app.models.document import Document, DocumentVersion, Sentence
from app.models.project_settings import ProjectSettings
from app.models.reference import EvidenceSuggestion, ProjectReference
from app.models.user import Project, User
from app.repositories.reference_repository import ReferenceRepository
from app.routers import grounding as grounding_router
from app.services import grounding_service as grounding_service_module
from app.services.evidence_search_state import (
    EvidenceSearchSession,
    EvidenceSearchSessionStore,
    SearchSessionStatus,
)
from app.services.evidence_search_workflow import (
    EvidenceSearchRoundResult,
    EvidenceSearchWorkflow,
    RoundResultSource,
    summarize_evaluations,
)
from app.services.evidence_service import EvidenceService
from app.services.reference_filter_service import ReferenceFilterCriteria, ReferenceFilterService
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchInput,
    AcademicSearchStatus,
    AcademicSearchToolResult,
    CandidateEvaluationStatus,
    EvidenceSearchCandidate,
    ProviderExecutionSummary,
    ReferenceCandidate,
    SearchToolCallRecord,
    SearchToolExecutionOutcome,
)


def run(coro):
    return asyncio.run(coro)


def candidate(index: int, *, open_access: bool = True) -> ReferenceCandidate:
    return ReferenceCandidate(
        provider="openalex",
        external_id=f"hardening-{index}",
        title=f"Hardening evidence {index}",
        authors=[f"Author {index}"],
        year=2020 + index,
        doi=f"10.1000/hardening.{index}",
        abstract=f"Evidence abstract {index}.",
        is_open_access=open_access,
    )


def evaluation(item: ReferenceCandidate, verdict: EvidenceVerdict) -> EvidenceEvaluation:
    return EvidenceEvaluation(
        candidate_key=item.candidate_key,
        verdict=verdict,
        confidence=0.9,
        reason="Deterministic hardening verdict.",
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
        reason="Deterministic hardening verdict.",
        analysis_scope=EvidenceAnalysisScope.TITLE_AND_ABSTRACT,
    )


def session_and_result(
    items: list[tuple[ReferenceCandidate, EvidenceVerdict]],
    *,
    status: SearchSessionStatus = SearchSessionStatus.ACTIVE,
    source: RoundResultSource = RoundResultSource.NEW_SEARCH,
) -> tuple[EvidenceSearchSession, EvidenceSearchRoundResult]:
    session = EvidenceSearchSession(current_round=1, status=status)
    evaluations: list[EvidenceEvaluation] = []
    for item, verdict in items:
        session.candidates[item.candidate_key] = transient(item, verdict)
        session.recovered_candidate_keys.add(item.candidate_key)
        session.evaluated_candidate_keys.add(item.candidate_key)
        if verdict is EvidenceVerdict.STRONG_SUPPORT:
            session.strong_support_keys.add(item.candidate_key)
        elif verdict is EvidenceVerdict.PARTIAL_SUPPORT:
            session.partial_support_keys.add(item.candidate_key)
        evaluations.append(evaluation(item, verdict))
    result = EvidenceSearchRoundResult(
        session_status=status,
        round_number=session.current_round,
        source=source,
        evaluation_summary=summarize_evaluations(evaluations),
        evaluations=evaluations,
        reserved_candidate_keys=tuple(item.candidate_key for item in evaluations),
        target_reached=False,
        refinement_recommended=False,
    )
    return session, result


def academic_outcome(candidates: list[ReferenceCandidate], query: str) -> SearchToolExecutionOutcome:
    public = AcademicSearchToolResult(
        status=AcademicSearchStatus.SUCCESS if candidates else AcademicSearchStatus.EMPTY,
        providers=[
            ProviderExecutionSummary(
                provider="openalex", success=True, results_found=len(candidates)
            )
        ],
        raw_results=len(candidates),
        after_deduplication=len(candidates),
        message="Academic search completed.",
        requested_limit_per_provider=15,
        effective_limit_per_provider=15,
    )
    call = SearchToolCallRecord(
        tool_call_id=f"call-{query}",
        tool_name=SearchToolName.SEARCH_ACADEMIC_WORKS,
        validated_arguments=AcademicSearchInput(queries=[query], limit_per_provider=15),
    )
    return SearchToolExecutionOutcome(
        sentence_type=SentenceType.SCIENTIFIC_CLAIM,
        action_taken=SearchToolName.SEARCH_ACADEMIC_WORKS,
        tool_call_id=call.tool_call_id,
        tool_execution=AcademicSearchExecutionResult(candidates=candidates, public_result=public),
        tool_call=call,
        reason=public.message,
    )


def no_action_outcome() -> SearchToolExecutionOutcome:
    return SearchToolExecutionOutcome(
        sentence_type=SentenceType.NON_SCIENTIFIC,
        action_taken=SearchToolName.NONE,
        reason="No academic action is appropriate.",
    )


class SequenceAgent:
    def __init__(self, initial, refined=()):
        self.initial = initial
        self.refined = list(refined)
        self.initial_calls = 0
        self.refined_calls = 0

    async def run_search_decision(self, *args, **kwargs):
        self.initial_calls += 1
        return self.initial

    async def run_refined_search_decision(self, **kwargs):
        self.refined_calls += 1
        return self.refined.pop(0)


class RecordingEvaluator:
    def __init__(self, verdict: EvidenceVerdict = EvidenceVerdict.NO_SUPPORT):
        self.verdict = verdict
        self.calls: list[list[str]] = []

    async def evaluate_batch(self, sentence, candidates):
        self.calls.append([item.candidate_key for item in candidates])
        return EvidenceEvaluationBatch(
            evaluations=[
                EvidenceEvaluation(
                    candidate_key=item.candidate_key,
                    verdict=self.verdict,
                    confidence=0.9,
                    reason="Deterministic evaluator response.",
                    analysis_scope=EvidenceAnalysisScope.TITLE_AND_ABSTRACT,
                )
                for item in candidates
            ]
        )


class ExplodingExecutor:
    async def execute(self, request):
        raise AssertionError("a none decision must not execute a tool or provider")


class WorkflowStub:
    def __init__(self, store, session, result):
        self.store = store
        self.session = session
        self.result = result
        self.calls = []

    async def execute_round(self, **kwargs):
        self.calls.append(kwargs)
        await self.store.set(
            (kwargs["user_id"], kwargs["document_version_id"], kwargs["sentence_uuid"]),
            self.session,
        )
        return self.result


class LegacySpy:
    def __init__(self):
        self.calls = 0

    def search_references(self, *args, **kwargs):
        self.calls += 1
        return []


@pytest.fixture()
def router_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(username="sprint6c", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(user_id=user.id, name="Hardening")
    db.add(project)
    db.flush()
    db.add(ProjectSettings(project_id=project.id, max_suggestions=5))
    document = Document(project_id=project.id, title="Document", content="Scientific claim.")
    db.add(document)
    db.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        content_snapshot="Scientific claim.",
        created_by=user.username,
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    sentence = Sentence(
        document_version_id=version.id,
        sentence_uuid="sentence-6c",
        paragraph_number=1,
        sentence_number=1,
        position=0.0,
        text="A scientific claim requires evidence.",
    )
    db.add(sentence)
    db.commit()

    def override_get_db():
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[grounding_router.get_current_user] = lambda: user
    client = TestClient(fastapi_app, raise_server_exceptions=True)
    yield client, db, user, project, version, sentence
    client.close()
    fastapi_app.dependency_overrides.clear()
    db.close()
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        Base.metadata.drop_all(connection)
        connection.execute(text("PRAGMA foreign_keys=ON"))
    engine.dispose()


def workflow(agent, evaluator, store=None) -> EvidenceSearchWorkflow:
    return EvidenceSearchWorkflow(
        search_agent=agent,
        evidence_evaluator=evaluator,
        reference_filter=ReferenceFilterService(),
        session_store=store or EvidenceSearchSessionStore(),
        academic_search_executor=ExplodingExecutor(),
        citation_resolution_executor=ExplodingExecutor(),
    )


def execute(instance, *, criteria=None, sentence_uuid="hardening-workflow"):
    return instance.execute_round(
        user_id=1,
        document_version_id=1,
        sentence_uuid=sentence_uuid,
        sentence="A scientific claim requires evidence.",
        citation_hints=None,
        filter_criteria=criteria or ReferenceFilterCriteria(),
    )


def test_terminal_refined_search_preserves_executed_origin(monkeypatch):
    monkeypatch.setattr(settings, "MAX_SEARCH_ROUNDS", 2)
    monkeypatch.setattr(settings, "TARGET_STRONG_EVIDENCE", 5)
    agent = SequenceAgent(
        academic_outcome([candidate(1)], "initial"),
        [academic_outcome([candidate(2)], "refined")],
    )
    result = run(execute(workflow(agent, RecordingEvaluator())))

    assert result.session_status is SearchSessionStatus.EXHAUSTED
    assert result.source is RoundResultSource.REFINED_SEARCH
    assert result.refinement_recommended is False
    assert agent.initial_calls == 1
    assert agent.refined_calls == 1


def test_prospective_source_is_rejected_for_terminal_result():
    with pytest.raises(ValidationError, match="terminal result cannot recommend refinement"):
        EvidenceSearchRoundResult(
            session_status=SearchSessionStatus.EXHAUSTED,
            round_number=3,
            source=RoundResultSource.REFINEMENT_RECOMMENDED,
            evaluation_summary=summarize_evaluations([]),
            target_reached=False,
            refinement_recommended=False,
        )


def test_none_is_terminal_no_action_without_tool_provider_evaluator_or_refinement():
    agent = SequenceAgent(no_action_outcome())
    evaluator = RecordingEvaluator()
    result = run(execute(workflow(agent, evaluator)))

    assert result.source is RoundResultSource.NO_ACTION
    assert result.session_status is SearchSessionStatus.EXHAUSTED
    assert result.failure_code is None
    assert result.search_outcome.tool_was_called is False
    assert evaluator.calls == []
    assert agent.initial_calls == 1
    assert agent.refined_calls == 0


def test_batches_use_only_new_accepted_pending_candidates(monkeypatch):
    monkeypatch.setattr(settings, "MAX_SEARCH_ROUNDS", 1)
    monkeypatch.setattr(settings, "EVIDENCE_BATCH_SIZE", 5)
    old = candidate(1)
    accepted = [candidate(index) for index in range(2, 8)]
    rejected = [candidate(index, open_access=False) for index in range(8, 11)]
    session = EvidenceSearchSession()
    session.candidates[old.candidate_key] = transient(old, EvidenceVerdict.NO_SUPPORT)
    session.recovered_candidate_keys.add(old.candidate_key)
    session.evaluated_candidate_keys.add(old.candidate_key)
    store = EvidenceSearchSessionStore()
    run(store.set((1, 1, "batch-filter"), session))
    agent = SequenceAgent(academic_outcome([old, *accepted, *rejected], "bounded"))
    evaluator = RecordingEvaluator()

    result = run(
        execute(
            workflow(agent, evaluator, store),
            criteria=ReferenceFilterCriteria(only_open_access=True),
            sentence_uuid="batch-filter",
        )
    )

    assert [len(batch) for batch in evaluator.calls] == [5, 1]
    evaluated_keys = {key for batch in evaluator.calls for key in batch}
    assert evaluated_keys == {item.candidate_key for item in accepted}
    assert old.candidate_key not in evaluated_keys
    assert not evaluated_keys.intersection(item.candidate_key for item in rejected)
    assert result.round_summary.raw_results == 10
    assert result.round_summary.after_filters == 6


def test_router_real_flow_persists_only_support_and_never_uses_legacy(
    monkeypatch, router_context
):
    client, db, user, project, version, sentence = router_context
    monkeypatch.setattr(settings, "USE_MOCK", False)
    strong, partial, unsupported = candidate(1), candidate(2), candidate(3)
    session, result = session_and_result(
        [
            (strong, EvidenceVerdict.STRONG_SUPPORT),
            (partial, EvidenceVerdict.PARTIAL_SUPPORT),
            (unsupported, EvidenceVerdict.NO_SUPPORT),
        ]
    )
    store = EvidenceSearchSessionStore()
    workflow_stub = WorkflowStub(store, session, result)
    legacy = LegacySpy()
    service = EvidenceService(
        workflow=workflow_stub,
        session_store=store,
        legacy_search=legacy,
    )
    monkeypatch.setattr(grounding_service_module, "EvidenceService", lambda: service)

    def mock_seed_forbidden(*args, **kwargs):
        raise AssertionError("the real flow must not seed mock references")

    monkeypatch.setattr(ReferenceRepository, "ensure_global_references", mock_seed_forbidden)
    response = client.post(
        "/api/sentences/search/evidence", json={"sentence_id": sentence.id}
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(workflow_stub.calls) == 1
    assert legacy.calls == 0
    assert len(payload) == 2
    assert all(item["status"] == "PENDING" for item in payload)
    assert set(payload[0]) == {
        "id", "document_version_id", "sentence_uuid", "reference_id",
        "status", "created_at", "reference",
    }
    assert db.query(ProjectReference).count() == 2
    assert db.query(EvidenceSuggestion).count() == 2
    assert db.query(ProjectReference).filter(ProjectReference.project_id.is_(None)).count() == 0
    stored = run(store.get((user.id, version.id, sentence.sentence_uuid)))
    assert stored.presented_candidate_keys == {strong.candidate_key, partial.candidate_key}
    assert stored.candidates[unsupported.candidate_key].shown_to_user is False


def test_router_persistence_failure_keeps_reserve_unpresented(
    monkeypatch, router_context
):
    client, db, user, project, version, sentence = router_context
    monkeypatch.setattr(settings, "USE_MOCK", False)
    item = candidate(1)
    session, result = session_and_result([(item, EvidenceVerdict.STRONG_SUPPORT)])
    store = EvidenceSearchSessionStore()
    service = EvidenceService(
        workflow=WorkflowStub(store, session, result),
        session_store=store,
    )
    monkeypatch.setattr(grounding_service_module, "EvidenceService", lambda: service)

    def fail_stage(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("controlled"))

    monkeypatch.setattr(ReferenceRepository, "get_or_stage_pending_suggestion", fail_stage)
    response = client.post(
        "/api/sentences/search/evidence", json={"sentence_id": sentence.id}
    )

    assert response.status_code == 409
    assert db.query(EvidenceSuggestion).count() == 0
    stored = run(store.get((user.id, version.id, sentence.sentence_uuid)))
    assert stored.presented_candidate_keys == set()
    assert stored.candidates[item.candidate_key].shown_to_user is False


@pytest.mark.parametrize(
    ("status", "source", "failure_code"),
    [
        (SearchSessionStatus.EXHAUSTED, RoundResultSource.NO_ACTION, None),
        (SearchSessionStatus.FAILED, RoundResultSource.FAILED, "provider_failure"),
    ],
)
def test_router_returns_safe_empty_response_for_none_and_operational_failure(
    monkeypatch, router_context, status, source, failure_code
):
    client, db, user, project, version, sentence = router_context
    monkeypatch.setattr(settings, "USE_MOCK", False)
    session, result = session_and_result([], status=status, source=source)
    if failure_code:
        result = result.model_copy(update={"failure_code": failure_code})
    store = EvidenceSearchSessionStore()
    service = EvidenceService(
        workflow=WorkflowStub(store, session, result),
        session_store=store,
    )
    monkeypatch.setattr(grounding_service_module, "EvidenceService", lambda: service)

    response = client.post(
        "/api/sentences/search/evidence", json={"sentence_id": sentence.id}
    )

    assert response.status_code == 200
    assert response.json() == []
    assert db.query(ProjectReference).count() == 0
    assert db.query(EvidenceSuggestion).count() == 0


def test_mock_mode_uses_legacy_without_constructing_real_runtime(monkeypatch, router_context):
    client, db, user, project, version, sentence = router_context
    monkeypatch.setattr(settings, "USE_MOCK", True)
    legacy = LegacySpy()
    service = EvidenceService(legacy_search=legacy)

    def real_runtime_forbidden():
        raise AssertionError("mock mode must not construct the real runtime")

    monkeypatch.setattr(service, "_real_runtime", real_runtime_forbidden)
    result = run(
        service.search(
            db,
            sentence.text,
            project.id,
            user_id=user.id,
            document_version_id=version.id,
            sentence_uuid=sentence.sentence_uuid,
        )
    )

    assert result == []
    assert legacy.calls == 1


def test_legacy_mode_persists_global_mock_references_in_reused_database(
    monkeypatch, router_context
):
    client, db, user, project, version, sentence = router_context
    monkeypatch.setattr(settings, "USE_MOCK", True)
    service = EvidenceService()
    monkeypatch.setattr(
        service,
        "_real_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("real runtime must remain isolated")),
    )

    run(
        service.search(
            db,
            sentence.text,
            project.id,
            user_id=user.id,
            document_version_id=version.id,
            sentence_uuid=sentence.sentence_uuid,
        )
    )

    assert db.query(ProjectReference).filter(ProjectReference.project_id.is_(None)).count() >= 12
