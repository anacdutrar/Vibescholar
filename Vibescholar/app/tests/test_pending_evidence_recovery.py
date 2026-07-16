"""Persisted pending-suggestion recovery without invoking the AI pipeline."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.app import fastapi_app
from app.core.database import Base, get_db
from app.models.document import Document, DocumentVersion, Sentence
from app.models.reference import EvidenceSuggestion, ProjectReference
from app.models.user import Project, User
from app.routers import grounding as grounding_router
from app.ui import api_client
from app.ui.pages.workspace import _load_pending_or_search_evidence_suggestions


@pytest.fixture()
def pending_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    owner = User(username="pending-owner", password_hash="hash")
    other = User(username="pending-other", password_hash="hash")
    db.add_all([owner, other])
    db.flush()

    owner_project = Project(user_id=owner.id, name="Owner project")
    other_project = Project(user_id=other.id, name="Other project")
    db.add_all([owner_project, other_project])
    db.flush()

    def create_sentence(project: Project, suffix: str):
        document = Document(
            project_id=project.id,
            title=f"Document {suffix}",
            content="Scientific statement.",
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            content_snapshot="Scientific statement.",
            created_by="test",
        )
        db.add(version)
        db.flush()
        document.current_version_id = version.id
        sentence = Sentence(
            document_version_id=version.id,
            sentence_uuid=f"sentence-{suffix}",
            paragraph_number=1,
            sentence_number=1,
            position=0.0,
            text="Scientific statement.",
        )
        db.add(sentence)
        db.flush()
        return version, sentence

    owner_version, owner_sentence = create_sentence(owner_project, "owner")
    other_version, other_sentence = create_sentence(other_project, "other")

    statuses = ("PENDING", "APPROVED", "REJECTED")
    owner_suggestions = []
    for index, status in enumerate(statuses, start=1):
        reference = ProjectReference(
            project_id=owner_project.id,
            title=f"Owner reference {index}",
            authors="Owner author",
        )
        db.add(reference)
        db.flush()
        suggestion = EvidenceSuggestion(
            document_version_id=owner_version.id,
            sentence_uuid=owner_sentence.sentence_uuid,
            reference_id=reference.id,
            status=status,
        )
        db.add(suggestion)
        owner_suggestions.append(suggestion)

    other_reference = ProjectReference(
        project_id=other_project.id,
        title="Other reference",
        authors="Other author",
    )
    db.add(other_reference)
    db.flush()
    db.add(
        EvidenceSuggestion(
            document_version_id=other_version.id,
            sentence_uuid=other_sentence.sentence_uuid,
            reference_id=other_reference.id,
            status="PENDING",
        )
    )
    db.commit()

    def override_get_db():
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[grounding_router.get_current_user] = lambda: owner
    client = TestClient(fastapi_app, raise_server_exceptions=True)
    yield (
        client,
        db,
        owner,
        owner_sentence,
        other_sentence,
        owner_suggestions,
    )
    client.close()
    fastapi_app.dependency_overrides.clear()
    db.close()
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        Base.metadata.drop_all(connection)
        connection.execute(text("PRAGMA foreign_keys=ON"))
    engine.dispose()


def test_get_returns_only_pending_for_owned_sentence(pending_context, monkeypatch):
    client, _, _, sentence, _, suggestions = pending_context
    monkeypatch.setattr(
        "app.services.grounding_service.EvidenceService",
        lambda: (_ for _ in ()).throw(
            AssertionError("pending GET must not construct the evidence workflow")
        ),
    )

    response = client.get(
        f"/api/sentences/{sentence.id}/evidence-suggestions",
        params={"status": "PENDING"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [suggestions[0].id]
    assert response.json()[0]["status"] == "PENDING"
    assert response.json()[0]["reference"]["title"] == "Owner reference 1"


def test_get_rejects_missing_and_foreign_sentences(pending_context):
    client, _, _, _, foreign_sentence, _ = pending_context

    missing = client.get(
        "/api/sentences/999999/evidence-suggestions",
        params={"status": "PENDING"},
    )
    forbidden = client.get(
        f"/api/sentences/{foreign_sentence.id}/evidence-suggestions",
        params={"status": "PENDING"},
    )

    assert missing.status_code == 404
    assert forbidden.status_code == 403


def test_approved_and_rejected_disappear_from_pending_lookup(pending_context):
    client, _, _, sentence, _, suggestions = pending_context
    pending = suggestions[0]

    approved = client.put(
        f"/api/evidence-suggestions/{pending.id}",
        json={"status": "APPROVED"},
    )
    after_approval = client.get(
        f"/api/sentences/{sentence.id}/evidence-suggestions",
        params={"status": "PENDING"},
    )

    assert approved.status_code == 200
    assert after_approval.status_code == 200
    assert after_approval.json() == []

    approved_again = suggestions[1]
    reset = client.put(
        f"/api/evidence-suggestions/{approved_again.id}",
        json={"status": "PENDING"},
    )
    rejected = client.put(
        f"/api/evidence-suggestions/{approved_again.id}",
        json={"status": "REJECTED"},
    )
    after_rejection = client.get(
        f"/api/sentences/{sentence.id}/evidence-suggestions",
        params={"status": "PENDING"},
    )

    assert reset.status_code == 200
    assert rejected.status_code == 200
    assert after_rejection.json() == []


def test_ui_after_reload_uses_backend_pending_without_search_post():
    async def scenario():
        persisted = [{"id": 7, "status": "PENDING", "reference": {"id": 3}}]
        state = {"status": "checking", "items": [], "error": None}
        pending_request = AsyncMock(return_value=persisted)
        search_request = AsyncMock()

        searched = await _load_pending_or_search_evidence_suggestions(
            state,
            pending_request,
            search_request,
            lambda: None,
        )

        assert searched is False
        assert state["items"] == persisted
        pending_request.assert_awaited_once_with()
        search_request.assert_not_awaited()

    asyncio.run(scenario())


def test_ui_without_pending_runs_search_post_exactly_once():
    async def scenario():
        materialized_reserve = [
            {"id": 8, "status": "PENDING", "reference": {"id": 4}}
        ]
        state = {"status": "checking", "items": [], "error": None}
        pending_request = AsyncMock(return_value=[])
        search_request = AsyncMock(return_value=materialized_reserve)

        searched = await _load_pending_or_search_evidence_suggestions(
            state,
            pending_request,
            search_request,
            lambda: None,
        )

        assert searched is True
        assert state["items"] == materialized_reserve
        pending_request.assert_awaited_once_with()
        search_request.assert_awaited_once_with()

    asyncio.run(scenario())


def test_ui_client_reads_pending_with_get_and_never_posts(monkeypatch):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [{"id": 9, "status": "PENDING"}]

    class Client:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, path, **kwargs):
            self.calls.append(("GET", path, kwargs))
            return Response()

        async def post(self, *args, **kwargs):
            raise AssertionError("pending recovery must not POST")

    client = Client()
    monkeypatch.setattr(api_client, "_async_client", lambda cookies=None: client)

    result = asyncio.run(
        api_client.api_list_pending_evidence_suggestions_async({}, 23)
    )

    assert result == [{"id": 9, "status": "PENDING"}]
    assert client.calls == [
        (
            "GET",
            "/api/sentences/23/evidence-suggestions",
            {"params": {"status": "PENDING"}},
        )
    ]
