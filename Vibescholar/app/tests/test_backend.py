import inspect
import asyncio
import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import Base, get_db
from app.core.config import settings
from app.app import fastapi_app
from app.core.security import hash_password
from app.models.user import Project, User
from app.models.document import DocumentVersion, Sentence
from app.models.project_settings import ProjectSettings
from app.models.reference import EvidenceSuggestion, ProjectReference
from app.repositories.reference_repository import ReferenceRepository
from app.schemas.request import UserCreate
from app.ui import api_client
from app.ui.pages import dashboard, login
from app.ui.pages.workspace import (
    QUILL_INIT_JS,
    _is_current_autosave_response,
    _persist_content_before_version,
    _persist_content_before_version_locked,
    _detect_apparent_citation,
    _filter_sentences_by_paragraph,
    _initial_paragraph_filter,
    _paragraph_filter_options,
    _reference_matches_citation,
    _sentence_panel_view,
    _set_sentence_view_filter,
)
from app.utils.sentence_splitter import filter_analyzable_content, split_sentences
from app.utils.text_normalizer import normalize_text

# StaticPool forces ALL connections to reuse the same single in-memory connection.
# This is critical: without it, each new connection opens a FRESH blank :memory: database.
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

# Enable WAL + foreign keys on the shared test connection
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def use_explicit_legacy_mock_mode(monkeypatch):
    """Backend regression tests deliberately exercise the temporary offline path."""
    monkeypatch.setattr(settings, "USE_MOCK", True)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        # Seed test user
        test_user = User(
            username="testuser",
            password_hash=hash_password("testpass123"),
            email="test@vibescholar.org"
        )
        db.add(test_user)
        db.commit()
        yield db
    finally:
        db.close()
        # Temporarily disable FK enforcement so drop_all can tear tables down
        # regardless of foreign key dependency order (required for circular FKs)
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys=OFF"))
            Base.metadata.drop_all(bind=conn)
            conn.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys=ON"))

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    fastapi_app.dependency_overrides[get_db] = override_get_db
    # raise_server_exceptions=True so test failures surface properly
    c = TestClient(fastapi_app, raise_server_exceptions=True)
    yield c
    fastapi_app.dependency_overrides.clear()

def test_auth_flow(client):
    # 1. Register a new user
    reg_response = client.post("/api/auth/register", json={
        "username": "newuser",
        "password": "newpassword123",
        "email": "new@vibescholar.org"
    })
    assert reg_response.status_code == 201
    assert reg_response.json()["username"] == "newuser"

    # 2. Login
    login_response = client.post("/api/auth/login", json={
        "username": "newuser",
        "password": "newpassword123"
    })
    assert login_response.status_code == 200
    assert "session_username" in login_response.cookies

    # 3. Logout
    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert "session_username" not in logout_response.cookies

def test_ui_register_payload_matches_user_create_schema():
    payload = api_client.register_payload("  uiuser  ", "secret123", "  ui@example.com  ")
    public_payload = api_client.public_payload(payload)

    assert public_payload == {
        "username": "uiuser",
        "password": "<omitted>",
        "email": "ui@example.com",
    }
    parsed = UserCreate(**payload)
    assert parsed.username == "uiuser"
    assert parsed.email == "ui@example.com"

    payload_without_email = api_client.register_payload("uiuser2", "secret123", "   ")
    assert payload_without_email == {"username": "uiuser2", "password": "secret123"}
    parsed_without_email = UserCreate(**payload_without_email)
    assert parsed_without_email.email is None

def test_ui_validation_message_for_register_422_detail():
    detail = [
        {"loc": ["body", "email"], "type": "value_error", "msg": "value is not a valid email address"},
        {"loc": ["body", "password"], "type": "string_too_short", "msg": "String should have at least 6 characters"},
    ]
    assert api_client.validation_error_message(detail) == "E-mail inválido; Senha muito curta"

@pytest.mark.anyio
async def test_api_create_project_async_uses_async_post(monkeypatch):
    calls = []

    class MockAsyncClient:
        def __init__(self, base_url=None, cookies=None, timeout=None):
            self.base_url = base_url
            self.cookies = cookies
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path, json):
            calls.append({
                "base_url": self.base_url,
                "cookies": self.cookies,
                "timeout": self.timeout,
                "path": path,
                "json": json,
            })
            request = httpx.Request("POST", f"{self.base_url}{path}")
            return httpx.Response(
                201,
                json={"id": 1, "user_id": 1, "name": json["name"], "description": json["description"], "created_at": "2026-07-11T00:00:00"},
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await api_client.api_create_project_async({"session_username": "testuser"}, "  Meu projeto  ", "Desc")

    assert result["name"] == "Meu projeto"
    assert calls == [{
        "base_url": api_client.BASE_URL,
        "cookies": {"session_username": "testuser"},
        "timeout": api_client.HTTP_TIMEOUT,
        "path": "/api/projects",
        "json": {"name": "Meu projeto", "description": "Desc"},
    }]

def test_project_document_flow(client):
    # Log in testuser
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123"
    })

    # Create project
    proj_res = client.post("/api/projects", json={
        "name": "Meu Projeto de Teste",
        "description": "Descricao do projeto"
    })
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    # Create document
    doc_res = client.post(f"/api/projects/{project_id}/documents", json={
        "title": "Minha Introducao",
        "content": "Frase de teste numero um. Outra frase muito importante."
    })
    assert doc_res.status_code == 201
    doc_id = doc_res.json()["id"]
    assert doc_res.json()["current_version_id"] is not None
    assert doc_res.json()["grounding_score"] == 0.0

    # Test Autosave (updates content directly, does NOT create a version)
    initial_version_id = doc_res.json()["current_version_id"]
    
    autosave_res = client.put(f"/api/documents/{doc_id}/content", json={
        "content": "Frase de teste numero um. Outra frase modificada e muito importante."
    })
    assert autosave_res.status_code == 200
    assert autosave_res.json()["content"] == "Frase de teste numero um. Outra frase modificada e muito importante."
    # current_version_id remains unchanged
    assert autosave_res.json()["current_version_id"] == initial_version_id

    # Test Manual Versioning (creates snapshot, extracts sentences, resets versions)
    ver_res = client.post(f"/api/documents/{doc_id}/version")
    assert ver_res.status_code == 201
    new_version_id = ver_res.json()["id"]
    assert new_version_id != initial_version_id

    # Get updated document metadata
    updated_doc_res = client.get(f"/api/documents/{doc_id}")
    assert updated_doc_res.json()["current_version_id"] == new_version_id

def test_duplicate_project_name_returns_409_and_session_remains_usable(client, db_session):
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123"
    })

    first_res = client.post("/api/projects", json={
        "name": "Meu projeto",
        "description": "Primeiro projeto"
    })
    assert first_res.status_code == 201

    duplicate_res = client.post("/api/projects", json={
        "name": "  Meu projeto  ",
        "description": "Nome duplicado com espaços externos"
    })
    assert duplicate_res.status_code == 409
    assert duplicate_res.json()["detail"] == "Já existe um projeto com esse nome."

    try:
        db_session.query(User).filter(User.username == "testuser").first()
    except PendingRollbackError as exc:
        pytest.fail(f"Session entered PendingRollbackError after duplicate project: {exc}")

    another_res = client.post("/api/projects", json={
        "name": "Outro projeto",
        "description": "Projeto criado depois do conflito"
    })
    assert another_res.status_code == 201

    register_res = client.post("/api/auth/register", json={
        "username": "otheruser",
        "password": "otherpass123",
        "email": "other@vibescholar.org"
    })
    assert register_res.status_code == 201

    client.post("/api/auth/login", json={
        "username": "otheruser",
        "password": "otherpass123"
    })
    same_name_other_user_res = client.post("/api/projects", json={
        "name": "Meu projeto",
        "description": "Mesmo nome para outro usuário"
    })
    assert same_name_other_user_res.status_code == 201

def test_sentence_uuid_equivalence_matching(client, db_session):
    # Log in
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123"
    })

    # Create project & document
    proj_res = client.post("/api/projects", json={"name": "P1"})
    project_id = proj_res.json()["id"]

    # Initial text
    doc_res = client.post(f"/api/projects/{project_id}/documents", json={
        "title": "D1",
        "content": "A inteligencia artificial revolucionou o diagnostico medico."
    })
    doc_id = doc_res.json()["id"]
    v1_id = doc_res.json()["current_version_id"]

    # Fetch sentences for Version 1
    v1_sentences = db_session.query(Sentence).filter(Sentence.document_version_id == v1_id).all()
    assert len(v1_sentences) == 1
    v1_uuid = v1_sentences[0].sentence_uuid
    assert v1_uuid is not None

    # Change punctuation (autosave + version save)
    client.put(f"/api/documents/{doc_id}/content", json={
        "content": "A inteligencia artificial revolucionou o diagnostico medico!"
    })
    v2_res = client.post(f"/api/documents/{doc_id}/version")
    assert v2_res.status_code == 201
    v2_id = v2_res.json()["id"]

    # Fetch sentences for Version 2
    v2_sentences = db_session.query(Sentence).filter(Sentence.document_version_id == v2_id).all()
    assert len(v2_sentences) == 1
    v2_uuid = v2_sentences[0].sentence_uuid

    # The sentence text is equivalent (modulo punctuation and casing), so UUID should be reused!
    assert v2_uuid == v1_uuid

def test_document_import_and_export(client):
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123"
    })

    proj_res = client.post("/api/projects", json={"name": "Export Project"})
    project_id = proj_res.json()["id"]

    # Test importing from TXT file upload
    file_content = b"Primeira frase do documento importado. Segunda frase importante."
    import_res = client.post(
        "/api/documents/import",
        data={"project_id": project_id, "title": "Artigo Importado"},
        files={"file": ("artigo.txt", file_content, "text/plain")}
    )
    assert import_res.status_code == 201
    doc_id = import_res.json()["id"]
    assert import_res.json()["content"] == "Primeira frase do documento importado. Segunda frase importante."

    # Test exporting document
    export_res = client.get(f"/api/documents/{doc_id}/export/markdown")
    assert export_res.status_code == 200
    assert b"Primeira frase do documento importado" in export_res.content


def _create_grounding_context(
    client,
    project_name="Grounding Project",
    content="A inteligência artificial melhora a recuperação de informação científica.",
):
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    project_res = client.post("/api/projects", json={"name": project_name})
    assert project_res.status_code == 201
    project_id = project_res.json()["id"]
    document_res = client.post(f"/api/projects/{project_id}/documents", json={
        "title": "Documento de evidências",
        "content": content,
    })
    assert document_res.status_code == 201
    document_id = document_res.json()["id"]
    sentences_res = client.get(f"/api/documents/{document_id}/sentences")
    assert sentences_res.status_code == 200
    sentence = sentences_res.json()[0]
    return project_id, document_id, sentence


def test_project_delete_dialog_is_persistent_and_refreshes_once():
    page_source = inspect.getsource(dashboard.dashboard_page)
    selector_source = inspect.getsource(dashboard._project_selector)
    confirm_source = page_source.split("async def confirm_project_delete", 1)[1].split(
        "def open_project_delete_dialog", 1
    )[0]
    after_refresh = confirm_source.split("await dashboard_content.refresh()", 1)[1]

    assert "with ui.dialog() as project_delete_dialog" in page_source
    assert "with ui.dialog() as dlg_del" not in selector_source
    assert "onclick=event.stopPropagation()" in selector_source
    assert confirm_source.count("await dashboard_content.refresh()") == 1
    assert ".close()" not in after_refresh
    assert ".enable()" not in after_refresh
    assert ".disable()" not in after_refresh
    assert ".set_text()" not in after_refresh


def test_mock_evidence_uses_persisted_references_without_duplicates(client, db_session):
    _, document_id, sentence = _create_grounding_context(client)

    first = client.post("/api/sentences/search/evidence", json={"sentence_id": sentence["id"]})
    assert first.status_code == 200
    first_suggestions = first.json()
    assert 3 <= len(first_suggestions) <= 5
    assert db_session.query(ProjectReference).filter(ProjectReference.project_id.is_(None)).count() >= 12
    assert all(item["reference_id"] is not None for item in first_suggestions)
    assert all(item["reference_id"] > 0 for item in first_suggestions)
    assert all(
        db_session.query(ProjectReference).filter(ProjectReference.id == item["reference_id"]).first()
        for item in first_suggestions
    )

    suggestion_count = db_session.query(EvidenceSuggestion).count()
    second = client.post("/api/sentences/search/evidence", json={"sentence_id": sentence["id"]})
    assert second.status_code == 200
    assert db_session.query(EvidenceSuggestion).count() == suggestion_count
    assert {item["id"] for item in second.json()} == {item["id"] for item in first_suggestions}

    rejected = first_suggestions[0]
    reject_res = client.put(
        f"/api/evidence-suggestions/{rejected['id']}", json={"status": "REJECTED"}
    )
    assert reject_res.status_code == 200
    after_reject = client.post("/api/sentences/search/evidence", json={"sentence_id": sentence["id"]})
    assert after_reject.status_code == 200
    assert all(
        item["reference_id"] != rejected["reference_id"] or item["status"] != "PENDING"
        for item in after_reject.json()
    )

    approved = next(item for item in after_reject.json() if item["status"] == "PENDING")
    approve_res = client.put(
        f"/api/evidence-suggestions/{approved['id']}", json={"status": "APPROVED"}
    )
    assert approve_res.status_code == 200
    after_approve = client.post("/api/sentences/search/evidence", json={"sentence_id": sentence["id"]})
    approved_rows = [
        item for item in after_approve.json()
        if item["reference_id"] == approved["reference_id"]
    ]
    assert len(approved_rows) == 1
    assert approved_rows[0]["status"] == "APPROVED"

    sentence_list = client.get(f"/api/documents/{document_id}/sentences").json()
    assert sentence_list[0]["approved_evidence_count"] == 1
    assert sentence_list[0]["approved_reference_titles"] == [approved["reference"]["title"]]


def test_mock_evidence_not_found_and_filters_without_results(client, db_session):
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    missing = client.post("/api/sentences/search/evidence", json={"sentence_id": 999999})
    assert missing.status_code == 404

    project_id, _, sentence = _create_grounding_context(client, "Filtered Project")
    project_settings = db_session.query(ProjectSettings).filter(
        ProjectSettings.project_id == project_id
    ).one()
    project_settings.minimum_qualis = "A1"
    project_settings.publication_year_min = 2099
    project_settings.publication_year_max = 2100
    project_settings.only_open_access = True
    project_settings.prefer_doi = True
    project_settings.max_suggestions = 5
    db_session.commit()

    filtered = client.post("/api/sentences/search/evidence", json={"sentence_id": sentence["id"]})
    assert filtered.status_code == 200
    assert filtered.json() == []


def test_suggestion_integrity_failure_rolls_back_session(client, db_session):
    _, _, sentence = _create_grounding_context(client, "Rollback Project")
    invalid = EvidenceSuggestion(
        document_version_id=sentence["document_version_id"],
        sentence_uuid=sentence["sentence_uuid"],
        reference_id=-999,
        status="PENDING",
    )

    with pytest.raises(IntegrityError):
        ReferenceRepository.create_suggestion(db_session, invalid)

    try:
        assert db_session.query(User).filter(User.username == "testuser").first() is not None
    except PendingRollbackError as exc:
        pytest.fail(f"Session entered PendingRollbackError after suggestion failure: {exc}")


def test_sentence_paragraph_filter_is_local_and_handles_unidentified():
    sentences = [
        {"id": 1, "paragraph_number": 1, "text": "Primeira."},
        {"id": 2, "paragraph_number": 1, "text": "Segunda."},
        {"id": 3, "paragraph_number": 2, "text": "Terceira."},
        {"id": 4, "paragraph_number": None, "text": "Sem posição."},
    ]

    assert _paragraph_filter_options(sentences) == {
        "all": "Todos os parágrafos",
        "1": "Parágrafo 1",
        "2": "Parágrafo 2",
        "unidentified": "Sem parágrafo identificado",
    }
    assert [item["id"] for item in _filter_sentences_by_paragraph(sentences, "1")] == [1, 2]
    assert [item["id"] for item in _filter_sentences_by_paragraph(sentences, "2")] == [3]
    assert [item["id"] for item in _filter_sentences_by_paragraph(sentences, "unidentified")] == [4]
    assert len(_filter_sentences_by_paragraph(sentences, "all")) == 4


def test_soft_deleted_project_is_restored_with_same_logical_record(client, db_session):
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    created = client.post("/api/projects", json={
        "name": "Projeto restaurável",
        "description": "Descrição original",
    })
    assert created.status_code == 201
    project_id = created.json()["id"]

    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 200
    assert db_session.query(Project).filter(Project.id == project_id).one().deleted_at is not None

    restored = client.post("/api/projects", json={
        "name": "  Projeto restaurável  ",
        "description": "Descrição restaurada",
    })
    assert restored.status_code == 201
    assert restored.json()["id"] == project_id

    logical_projects = db_session.query(Project).filter(
        Project.user_id == restored.json()["user_id"],
        Project.name == "Projeto restaurável",
    ).all()
    assert len(logical_projects) == 1
    assert logical_projects[0].deleted_at is None
    assert logical_projects[0].description == "Descrição restaurada"
    assert db_session.query(ProjectSettings).filter(
        ProjectSettings.project_id == project_id
    ).count() == 1

    active_duplicate = client.post("/api/projects", json={"name": "Projeto restaurável"})
    assert active_duplicate.status_code == 409
    assert active_duplicate.json()["detail"] == "Já existe um projeto com esse nome."


def test_citation_doi_match_confirmation_is_real_and_not_duplicated(client, db_session):
    project_id, document_id, sentence = _create_grounding_context(
        client,
        "DOI Citation Project",
        "O método apresentou resultados consistentes 10.7777/metodo.2022.1.",
    )
    reference = ProjectReference(
        project_id=project_id,
        title="Método científico aplicado",
        authors="Marina Costa",
        journal="Revista de Metodologia",
        year=2022,
        doi="10.7777/metodo.2022.1",
        qualis_score="A1",
        availability="ABERTO",
    )
    db_session.add(reference)
    db_session.commit()

    assert sentence["status"] == "UNVERIFIED"
    assert _detect_apparent_citation(sentence["text"])["doi"] == "10.7777/metodo.2022.1"

    search = client.post("/api/sentences/search/evidence", json={"sentence_id": sentence["id"]})
    assert search.status_code == 200
    match = next(item for item in search.json() if item["reference_id"] == reference.id)
    assert match["status"] == "PENDING"

    first_confirmation = client.put(
        f"/api/evidence-suggestions/{match['id']}", json={"status": "APPROVED"}
    )
    second_confirmation = client.put(
        f"/api/evidence-suggestions/{match['id']}", json={"status": "APPROVED"}
    )
    assert first_confirmation.status_code == 200
    assert second_confirmation.status_code == 200
    assert db_session.query(EvidenceSuggestion).filter(
        EvidenceSuggestion.document_version_id == sentence["document_version_id"],
        EvidenceSuggestion.sentence_uuid == sentence["sentence_uuid"],
        EvidenceSuggestion.reference_id == reference.id,
    ).count() == 1

    updated_sentence = client.get(f"/api/documents/{document_id}/sentences").json()[0]
    assert updated_sentence["status"] == "SUPPORTED"
    assert updated_sentence["approved_evidence_count"] == 1


def test_citation_author_year_matches_library_without_auto_support(client, db_session):
    project_id, _, sentence = _create_grounding_context(
        client,
        "Author Citation Project",
        "A escrita acadêmica exige revisão contínua (Silva et al., 2022).",
    )
    reference = ProjectReference(
        project_id=project_id,
        title="Revisão da escrita acadêmica",
        authors="Silva, Paula; Ramos, André",
        journal="Escrita Científica",
        year=2022,
        doi="10.8888/escrita.2022",
        qualis_score="A2",
        availability="ABERTO",
    )
    db_session.add(reference)
    db_session.commit()

    citation = _detect_apparent_citation(sentence["text"])
    assert citation == {
        "raw": "(Silva et al., 2022)",
        "doi": None,
        "author": "Silva",
        "year": 2022,
    }
    assert _reference_matches_citation({
        "authors": reference.authors,
        "year": reference.year,
        "doi": reference.doi,
    }, citation)
    assert sentence["status"] == "UNVERIFIED"

    search = client.post("/api/sentences/search/evidence", json={"sentence_id": sentence["id"]})
    assert search.status_code == 200
    match = next(item for item in search.json() if item["reference_id"] == reference.id)
    assert match["status"] == "PENDING"
    persisted_sentence = db_session.query(Sentence).filter(Sentence.id == sentence["id"]).one()
    assert persisted_sentence.status == "UNVERIFIED"


def test_non_analyzable_editorial_and_structural_blocks_are_filtered():
    content = """Received April 24, 2018, accepted May 23, 2018, date of publication June 18, 2018, date of current version June 29, 2018.

DOI: 10.1109/EXAMPLE.2018.1

Fig. 2 Experimental overview

Table I Results

| Method | Score |
|--------|-------|
| Model A | 0.91 |

A pesquisa científica apresenta resultados válidos e reproduzíveis.

References

Silva, P. Referência que não deve ser analisada. 2022.
Outra referência também não deve aparecer."""

    sentences = split_sentences(content)

    assert [item["text"] for item in sentences] == [
        "A pesquisa científica apresenta resultados válidos e reproduzíveis."
    ]
    assert "Received" not in " ".join(item["text"] for item in sentences)
    assert "Referência" not in " ".join(item["text"] for item in sentences)


def test_reference_heading_stops_analysis_and_short_normal_text_is_preserved():
    content = """Texto curto funciona.

Referências

Esta linha possui verbo e pontuação, mas pertence às referências.

Bibliography

Another bibliographic entry is present."""

    sentences = split_sentences(content)

    assert [item["text"] for item in sentences] == ["Texto curto funciona."]


def test_isolated_doi_figure_table_and_markdown_table_generate_no_sentences():
    content = """10.1234/example.5678

Figure 1

Fig. 2

Table 1

Table IV

| Campo | Valor |

-----:::::_____|||||"""

    assert split_sentences(content) == []


def test_analysis_filter_does_not_modify_original_document_content(client):
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    project = client.post("/api/projects", json={"name": "Filtered Analysis"}).json()
    original_content = (
        "Received April 24, 2018, accepted May 23, 2018.\n\n"
        "Este parágrafo científico permanece disponível para análise.\n\n"
        "References\n\n"
        "Uma referência bibliográfica não entra no grounding."
    )
    analysis_copy = filter_analyzable_content(original_content)
    assert original_content.startswith("Received April 24, 2018")
    assert analysis_copy != original_content

    created = client.post(f"/api/projects/{project['id']}/documents", json={
        "title": "Documento filtrado",
        "content": original_content,
    })
    assert created.status_code == 201
    assert created.json()["content"] == original_content

    sentences = client.get(f"/api/documents/{created.json()['id']}/sentences").json()
    assert [sentence["text"] for sentence in sentences] == [
        "Este parágrafo científico permanece disponível para análise."
    ]


def _build_large_sentence_collection() -> list[dict]:
    counts = {paragraph: 1 for paragraph in range(1, 195)}
    counts[102] = 24
    remaining = 699 - sum(counts.values())
    paragraphs = [paragraph for paragraph in range(1, 195) if paragraph != 102]
    for index in range(remaining):
        counts[paragraphs[index % len(paragraphs)]] += 1

    sentences = []
    sentence_id = 1
    for paragraph, count in counts.items():
        for sentence_number in range(1, count + 1):
            sentences.append({
                "id": sentence_id,
                "paragraph_number": paragraph,
                "sentence_number": sentence_number,
                "text": f"Sentença {sentence_number} do parágrafo {paragraph}.",
                "status": "UNVERIFIED",
                "approved_evidence_count": 0,
            })
            sentence_id += 1
    return sentences


def test_initial_sentence_panel_renders_only_first_paragraph_page():
    sentences = _build_large_sentence_collection()
    initial_filter = _initial_paragraph_filter(sentences)
    view_state = {"filter": initial_filter, "sentence_page": 1, "summary_page": 1}

    view = _sentence_panel_view(sentences, view_state)

    assert len(sentences) == 699
    assert initial_filter == "1"
    assert initial_filter != "all"
    assert view["mode"] == "sentences"
    assert view["card_count"] <= 10
    assert all(item["paragraph_number"] == 1 for item in view["items"])


def test_all_paragraphs_view_contains_only_paginated_summaries():
    sentences = _build_large_sentence_collection()
    view_state = {"filter": "all", "sentence_page": 1, "summary_page": 1}

    first_page = _sentence_panel_view(sentences, view_state)
    view_state["summary_page"] = 8
    last_page = _sentence_panel_view(sentences, view_state)

    assert first_page["mode"] == "summaries"
    assert first_page["card_count"] == 0
    assert first_page["summary_count"] == 25
    assert first_page["total_pages"] == 8
    assert last_page["page"] == 8
    assert last_page["summary_count"] == 19
    assert all("sentence_count" in summary for summary in first_page["items"])


def test_sentence_pagination_and_filter_change_reset():
    sentences = _build_large_sentence_collection()
    original_paragraphs = [sentence["paragraph_number"] for sentence in sentences]
    view_state = {"filter": "102", "sentence_page": 1, "summary_page": 1}

    first_page = _sentence_panel_view(sentences, view_state)
    view_state["sentence_page"] = 3
    third_page = _sentence_panel_view(sentences, view_state)

    assert first_page["total_items"] == 24
    assert first_page["total_pages"] == 3
    assert first_page["card_count"] == 10
    assert third_page["page"] == 3
    assert third_page["card_count"] == 4

    _set_sentence_view_filter(view_state, "103")
    assert view_state == {"filter": "103", "sentence_page": 1, "summary_page": 1}
    assert [sentence["paragraph_number"] for sentence in sentences] == original_paragraphs
    assert all(sentence["paragraph_number"] is not None for sentence in sentences)


def test_sentence_view_logic_has_no_api_dependency():
    assert "api." not in inspect.getsource(_initial_paragraph_filter)
    assert "api." not in inspect.getsource(_sentence_panel_view)
    assert "api." not in inspect.getsource(_set_sentence_view_filter)


def test_restore_loads_draft_without_creating_version_and_preserves_history(client, db_session):
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    project = client.post("/api/projects", json={"name": "Version Restore Project"}).json()
    initial_content = "Conteúdo original da primeira versão."
    created = client.post(f"/api/projects/{project['id']}/documents", json={
        "title": "Documento versionado",
        "content": initial_content,
    }).json()
    document_id = created["id"]
    first_version_id = created["current_version_id"]

    latest_editor_content = "Conteúdo mais recente capturado diretamente do editor."
    put_response = client.put(f"/api/documents/{document_id}/content", json={
        "content": latest_editor_content,
    })
    assert put_response.status_code == 200
    second_version = client.post(f"/api/documents/{document_id}/version")
    assert second_version.status_code == 201
    assert second_version.json()["content_snapshot"] == latest_editor_content

    versions_before = db_session.query(DocumentVersion).filter(
        DocumentVersion.document_id == document_id
    ).order_by(DocumentVersion.version_number).all()
    history_before = [
        (version.id, version.version_number, version.content_snapshot)
        for version in versions_before
    ]
    current_version_before_restore = second_version.json()["id"]

    restored = client.post(
        f"/api/documents/{document_id}/restore/{first_version_id}"
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "document_id": document_id,
        "restored_from_version_id": first_version_id,
        "restored_from_version_number": 1,
        "content": initial_content,
    }

    versions_after_restore = db_session.query(DocumentVersion).filter(
        DocumentVersion.document_id == document_id
    ).order_by(DocumentVersion.version_number).all()
    assert len(versions_before) == len(versions_after_restore) == 2
    assert [
        (version.id, version.version_number, version.content_snapshot)
        for version in versions_after_restore
    ] == history_before

    updated_document = client.get(f"/api/documents/{document_id}").json()
    assert updated_document["content"] == initial_content
    assert updated_document["current_version_id"] == current_version_before_restore

    saved_after_restore = client.post(f"/api/documents/{document_id}/version")
    assert saved_after_restore.status_code == 201
    assert saved_after_restore.json()["content_snapshot"] == initial_content
    assert db_session.query(DocumentVersion).filter(
        DocumentVersion.document_id == document_id
    ).count() == 3


def test_identical_manual_save_returns_200_without_duplicate_version(client, db_session):
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    project = client.post("/api/projects", json={"name": "No Duplicate Version"}).json()
    created = client.post(f"/api/projects/{project['id']}/documents", json={
        "title": "Documento sem duplicata",
        "content": "Mesmo conteúdo normalizado.",
    }).json()
    document_id = created["id"]
    count_before = db_session.query(DocumentVersion).filter(
        DocumentVersion.document_id == document_id
    ).count()

    response = client.post(f"/api/documents/{document_id}/version")

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["message"] == "Nenhuma alteração desde a última versão."
    assert db_session.query(DocumentVersion).filter(
        DocumentVersion.document_id == document_id
    ).count() == count_before


@pytest.mark.anyio
async def test_manual_version_persists_content_before_post(monkeypatch):
    calls = []
    visible_content = "Conteúdo visível no Quill no instante do clique."

    async def fake_put(cookies, document_id, content):
        calls.append(("PUT", document_id, content))
        return {"id": document_id, "content": content}

    async def fake_post(cookies, document_id):
        calls.append(("POST", document_id))
        return {"id": 44, "document_id": document_id, "version_number": 3}

    monkeypatch.setattr(api_client, "api_autosave_content_async", fake_put)
    monkeypatch.setattr(api_client, "api_save_version_async", fake_post)

    result = await _persist_content_before_version(
        {"session_username": "testuser"}, 9, visible_content
    )

    assert result["id"] == 44
    assert calls == [
        ("PUT", 9, visible_content),
        ("POST", 9),
    ]


@pytest.mark.anyio
async def test_pending_autosave_finishes_before_manual_put_and_post(monkeypatch):
    lock = asyncio.Lock()
    pending_started = asyncio.Event()
    release_pending = asyncio.Event()
    calls = []

    async def pending_autosave():
        async with lock:
            calls.append("AUTOSAVE_START")
            pending_started.set()
            await release_pending.wait()
            calls.append("AUTOSAVE_END")

    async def fake_put(cookies, document_id, content):
        calls.append("MANUAL_PUT")
        return {"id": document_id, "content": content}

    async def fake_post(cookies, document_id):
        calls.append("VERSION_POST")
        return {"id": 45, "document_id": document_id, "version_number": 4}

    monkeypatch.setattr(api_client, "api_autosave_content_async", fake_put)
    monkeypatch.setattr(api_client, "api_save_version_async", fake_post)

    pending_task = asyncio.create_task(pending_autosave())
    await pending_started.wait()
    manual_task = asyncio.create_task(
        _persist_content_before_version_locked(lock, {}, 9, "Conteúdo atual")
    )
    await asyncio.sleep(0)
    assert calls == ["AUTOSAVE_START"]

    release_pending.set()
    await pending_task
    await manual_task

    assert calls == [
        "AUTOSAVE_START",
        "AUTOSAVE_END",
        "MANUAL_PUT",
        "VERSION_POST",
    ]


def test_quill_programmatic_content_is_silent_and_cancels_autosave():
    assert "window.__vs_autosave_timer" in QUILL_INIT_JS
    assert "cancelQuillAutosave();" in QUILL_INIT_JS
    assert "setText(text, 'silent')" in QUILL_INIT_JS
    assert "setText(initial, 'silent')" in QUILL_INIT_JS
    assert "source !== 'user' || window.__vs_loading_content" in QUILL_INIT_JS
    assert "change_ignored source=" in QUILL_INIT_JS


def test_stale_autosave_response_is_ignored_without_editor_regression():
    autosave_state = {
        "next_revision": 2,
        "latest_started": 2,
        "latest_completed": 0,
    }

    assert _is_current_autosave_response(autosave_state, 1) is False
    assert _is_current_autosave_response(autosave_state, 2) is True
    assert "setQuillContent" not in inspect.getsource(_is_current_autosave_response)


@pytest.mark.parametrize("text", [
    "In [18], Taha et al. present an algorithm for surveillance.",
    "The result in Fig. 2 confirms the hypothesis.",
    "The results in Figs. 2 and 3 confirm the hypothesis.",
    "Eq. 4 defines the objective function.",
    "Eqs. 4 and 5 define the objective functions.",
    "Ref. 8 describes the protocol.",
    "Refs. 8 and 9 describe the protocol.",
    "No. 4 identifies the experiment.",
    "Nos. 4 and 5 identify the experiments.",
    "Dr. Silva presents the method.",
    "Prof. Silva presents the method.",
    "Sr. Silva apresenta o método.",
    "Sra. Silva apresenta o método.",
    "Mr. Smith presents the method.",
    "Mrs. Smith presents the method.",
    "Ms. Smith presents the method.",
    "Example Inc. develops the platform.",
    "Example Ltd. develops the platform.",
    "Example Co. develops the platform.",
    "Vol. 4 contains the article.",
    "See pp. 20-30 for the complete discussion.",
    "See p. 15 for the complete discussion.",
    "Ch. 3 presents the architecture.",
    "Sec. 2 presents the architecture.",
    "Art. 5 defines the requirement.",
    "Method A vs. Method B produces different results.",
    "The variables, etc. remain controlled.",
    "Several methods, e.g. neural networks, were evaluated.",
    "The values, i.e. the observed measurements, were recorded.",
])
def test_scientific_abbreviations_do_not_split_sentences(text):
    sentences = split_sentences(text)
    assert [item["text"] for item in sentences] == [text]


@pytest.mark.parametrize("text", [
    '"A internet mudou o mundo" (SILVA, 2024, p. 15).',
    "The complete interval appears on pp. 20-30 and supports the result.",
    "According to [18], the proposed method is effective.",
    "According to [4,5], the proposed method is effective.",
    "The proposed method (Author et al., 2022) is effective.",
])
def test_pagination_and_citations_remain_inside_sentence(text):
    sentences = split_sentences(text)
    assert [item["text"] for item in sentences] == [text]


def test_bibliographic_and_editorial_blocks_are_not_analyzable():
    content = """SILVA, João Alberto. A evolução da tecnologia. São Paulo: Editora Alfa, 2024.

IEEE

ACM

ABNT

APA

Authors

Affiliations

Received April 24, 2018.

Accepted May 23, 2018.

Keywords: artificial intelligence

Index Terms: surveillance

Funding: Research grant 123.

Acknowledgment: The authors thank the institution.

DOI: 10.1234/example.2024"""

    assert split_sentences(content) == []


@pytest.mark.parametrize("marker", ["1.", "2.", "4)", "I.", "II.", "III.", "a)", "b)", "c)"])
def test_enumeration_marker_does_not_create_isolated_paragraph(marker):
    content = f"{marker}\n\nThe procedure improves scientific reproducibility."
    sentences = split_sentences(content)
    assert [item["text"] for item in sentences] == [
        "The procedure improves scientific reproducibility."
    ]
    assert sentences[0]["paragraph_number"] == 1


def test_login_card_is_centered_and_responsive():
    source = inspect.getsource(login.login_page)
    assert "position:fixed" in source
    assert "inset:0" in source
    assert "align-items:center; justify-content:center" in source
    assert "width:min(440px, calc(100vw - 32px))" in source
    assert "max-width:440px" in source
    assert "margin:auto" in source
