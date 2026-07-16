"""Focused regression tests for the enriched reference-library presentation."""

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.security import hash_password
from app.exceptions.document import ProjectNotFoundException
from app.models.reference import ProjectReference
from app.models.user import Project, User
from app.schemas.response import ReferenceOut
from app.services.reference_service import ReferenceService
from app.ui.pages import references


@pytest.fixture
def reference_db():
    """Provide an isolated database without touching the application's SQLite file."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_reference_public_schema_preserves_all_persisted_academic_metadata() -> None:
    reference = ProjectReference(
        id=7,
        project_id=3,
        title="A complete academic reference",
        authors="Ana Silva; Bruno Costa",
        journal="Journal of Complete Metadata",
        year=2025,
        doi="10.1234/complete.2025",
        qualis_score="A1",
        abstract="A persisted abstract.",
        availability="ABERTO",
    )

    public = ReferenceOut.model_validate(reference)

    assert public.model_dump() == {
        "id": 7,
        "project_id": 3,
        "title": "A complete academic reference",
        "authors": "Ana Silva; Bruno Costa",
        "journal": "Journal of Complete Metadata",
        "year": 2025,
        "doi": "10.1234/complete.2025",
        "qualis_score": "A1",
        "abstract": "A persisted abstract.",
        "availability": "ABERTO",
    }


def test_reference_public_schema_accepts_missing_optional_metadata() -> None:
    public = ReferenceOut.model_validate(
        ProjectReference(
            id=8,
            project_id=3,
            title="Reference with partial metadata",
            authors="",
            journal=None,
            year=None,
            doi=None,
            qualis_score=None,
            abstract=None,
            availability=None,
        )
    )

    assert public.journal is None
    assert public.year is None
    assert public.doi is None
    assert public.qualis_score is None
    assert public.abstract is None
    assert public.availability is None


def test_transient_provider_fields_are_not_claimed_by_public_schema() -> None:
    """Fields not persisted by ProjectReference must not be fabricated by the API."""
    assert {
        "issn",
        "eissn",
        "language",
        "provider",
        "source_url",
        "provider_relevance_score",
    }.isdisjoint(ReferenceOut.model_fields)


def test_reference_view_model_formats_complete_metadata_without_mutation() -> None:
    source = {
        "id": 9,
        "title": "Long-lived metadata",
        "authors": "Ana Silva; Bruno Costa; Carla Lima; Diego Souza; Elena Rocha",
        "journal": "Metadata Review",
        "year": 2024,
        "doi": "https://doi.org/10.4321/metadata.2024",
        "qualis_score": "A2",
        "abstract": "Complete abstract text.",
        "availability": "ABERTO",
        "issn": "1234-567X",
        "eissn": "9876-5432",
        "language": "pt",
        "provider": "openalex",
        "source_url": "https://openalex.org/W123",
    }
    original = dict(source)

    view = references._reference_view_model(source)

    assert view["doi_display"] == "10.4321/metadata.2024"
    assert view["doi_url"] == "https://doi.org/10.4321/metadata.2024"
    assert view["authors_summary"] == "Ana Silva; Bruno Costa; Carla Lima +2"
    assert view["authors"] == source["authors"]
    assert view["journal"] == "Metadata Review"
    assert view["open_access"] == "Sim"
    assert view["qualis"] == "A2"
    assert view["abstract"] == "Complete abstract text."
    assert view["issn"] == "1234-567X"
    assert view["eissn"] == "9876-5432"
    assert view["language"] == "pt"
    assert view["source_url"] == "https://openalex.org/W123"
    assert source == original


def test_reference_view_model_uses_consistent_missing_metadata_labels() -> None:
    view = references._reference_view_model(
        {
            "id": 10,
            "title": "Minimal reference",
            "authors": "",
            "journal": None,
            "year": None,
            "doi": None,
            "qualis_score": None,
            "abstract": None,
            "availability": None,
        }
    )

    assert view["authors_summary"] == "Autores não informados"
    assert view["journal"] == "Não informado"
    assert view["year"] == "Não informado"
    assert view["doi_display"] == "Não disponível"
    assert view["doi_url"] is None
    assert view["qualis"] == "Não classificado"
    assert view["abstract"] == "Resumo não disponível"
    assert view["has_abstract"] is False
    assert view["open_access"] == "Não informado"
    assert view["issn"] == "Não informado"
    assert view["eissn"] == "Não informado"
    assert view["language"] == "Não informado"


@pytest.mark.parametrize(
    ("persisted", "expected"),
    [
        ("ABERTO", "Sim"),
        ("FECHADO", "Não"),
        (None, "Não informado"),
        ("unknown", "Não informado"),
    ],
)
def test_open_access_display_preserves_unknown_state(persisted, expected) -> None:
    assert references._availability_label(persisted) == expected


def test_invalid_doi_and_unsafe_source_url_do_not_create_links() -> None:
    view = references._reference_view_model(
        {
            "title": "Unsafe metadata",
            "authors": "Author",
            "doi": "not-a-doi",
            "source_url": "javascript:alert(1)",
        }
    )

    assert view["doi_display"] == "Não disponível"
    assert view["doi_url"] is None
    assert view["source_url"] == ""


def test_reference_service_keeps_project_and_user_isolation(reference_db) -> None:
    first_user = User(
        username="owner",
        password_hash=hash_password("password123"),
        email="owner@example.org",
    )
    second_user = User(
        username="other",
        password_hash=hash_password("password123"),
        email="other@example.org",
    )
    reference_db.add_all([first_user, second_user])
    reference_db.flush()
    first_project = Project(user_id=first_user.id, name="First project")
    second_project = Project(user_id=second_user.id, name="Second project")
    reference_db.add_all([first_project, second_project])
    reference_db.flush()
    reference_db.add_all(
        [
            ProjectReference(
                project_id=first_project.id,
                title="First reference",
                authors="First author",
                availability="FECHADO",
            ),
            ProjectReference(
                project_id=second_project.id,
                title="Second reference",
                authors="Second author",
                availability="FECHADO",
            ),
        ]
    )
    reference_db.commit()
    service = ReferenceService(reference_db)

    visible = service.list_references(first_project.id, first_user.id)

    assert [item.title for item in visible] == ["First reference"]
    with pytest.raises(ProjectNotFoundException):
        service.list_references(first_project.id, second_user.id)


def test_reference_page_preserves_actions_and_does_not_call_ai_pipeline() -> None:
    source = inspect.getsource(references.references_page)

    assert "api_list_references_async" in source
    assert "api_create_reference_async" in source
    assert "api_update_reference_async" in source
    assert "api_delete_reference_async" in source
    assert "api_import_references_async" in source
    assert 'icon="visibility"' in source
    assert "open_details" in source
    assert "overflow-wrap:anywhere" in source
    assert "search_evidence" not in source
    assert "EvidenceSearchWorkflow" not in source
    assert "QualisLookupService" not in source
