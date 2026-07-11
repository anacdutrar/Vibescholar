import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import Base, get_db
from app.app import fastapi_app
from app.core.security import hash_password
from app.models.user import User
from app.models.document import DocumentVersion, Sentence
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
