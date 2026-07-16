"""Isolated tests for the local Qualis XLSX import and read-only lookup."""

import ast
import hashlib
import inspect
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.schemas.qualis import QualisLookupStatus
from app.scripts.import_qualis_dataset import import_qualis_dataset
from app.services.qualis_lookup_service import QualisLookupService
from app.utils.issn import normalize_issn


FIXTURE = Path(__file__).parent / "fixtures" / "qualis_synthetic.xlsx"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234-5678", "1234-5678"),
        ("1234567x", "1234-567X"),
        (" 1234 - 567X ", "1234-567X"),
        ("ISSN: 1234-567X", "1234-567X"),
        ("eISSN: 8765 4321", "8765-4321"),
        ("1234/567X", None),
        ("1234-567A", None),
        ("invalid", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_issn_is_strict_and_canonical(raw, expected):
    assert normalize_issn(raw) == expected


def test_qualis_database_path_has_safe_default(monkeypatch):
    monkeypatch.delenv("QUALIS_DATABASE_PATH", raising=False)

    assert Settings().QUALIS_DATABASE_PATH == "data/qualis/qualis.sqlite3"


@pytest.fixture
def artifact_directory():
    directory = Path.cwd() / ".test-artifacts" / f"qualis-{uuid4().hex}"
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()
        directory.rmdir()
        parent = directory.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


@pytest.fixture
def imported_dataset(artifact_directory):
    destination = artifact_directory / "qualis.sqlite3"
    result = import_qualis_dataset(FIXTURE, destination)
    return destination, result


def test_import_creates_dedicated_sqlite_and_metadata(imported_dataset):
    database, result = imported_dataset
    expected_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()

    assert database.is_file()
    assert result.database_path == database
    assert result.quadrennium == "2017-2020"
    assert result.source_sha256 == expected_hash
    assert result.rows_read == 5
    assert result.rows_imported == 3
    assert result.rows_rejected == 1

    with closing(sqlite3.connect(database)) as connection:
        metadata = connection.execute(
            """
            SELECT quadrennium, imported_at, source_sha256,
                   rows_read, rows_imported, rows_rejected
            FROM dataset_metadata
            """
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert metadata[0] == "2017-2020"
    assert metadata[1]
    assert metadata[2] == expected_hash
    assert metadata[3:] == (5, 3, 1)
    assert {"dataset_metadata", "qualis_records"}.issubset(tables)
    assert "users" not in tables
    assert "projects" not in tables
    assert "evidence_suggestions" not in tables


def test_import_rejects_invalid_row_consolidates_duplicate_and_preserves_conflict(
    imported_dataset,
):
    database, _ = imported_dataset

    with closing(sqlite3.connect(database)) as connection:
        records = connection.execute(
            """
            SELECT issn, title, stratum, parent_area, quadrennium
            FROM qualis_records
            ORDER BY id
            """
        ).fetchall()

    assert records == [
        ("1234-567X", "Journal One", "A1", "Computação", "2017-2020"),
        (
            "1234-567X",
            "Journal One Conflict",
            "B1",
            "Computação",
            "2017-2020",
        ),
        ("8765-4321", "Journal Two", "A2", "Engenharia", "2017-2020"),
    ]


def test_import_can_use_explicit_quadrennium_override(artifact_directory):
    database = artifact_directory / "qualis.sqlite3"

    result = import_qualis_dataset(
        FIXTURE,
        database,
        quadrennium="2021-2024",
    )

    assert result.quadrennium == "2021-2024"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT DISTINCT quadrennium FROM qualis_records"
        ).fetchall() == [("2021-2024",)]


def test_import_rejects_workbook_without_required_columns_without_partial_database(
    artifact_directory,
):
    invalid_source = artifact_directory / "not-xlsx.xlsx"
    invalid_source.write_text("not an XLSX", encoding="utf-8")
    database = artifact_directory / "qualis.sqlite3"

    with pytest.raises(ValueError, match="readable XLSX"):
        import_qualis_dataset(invalid_source, database)

    assert not database.exists()
    assert not Path(f"{database}.tmp").exists()


def test_lookup_found_not_found_invalid_unavailable_and_ambiguous(
    imported_dataset,
    artifact_directory,
):
    database, _ = imported_dataset
    service = QualisLookupService(database)

    found = service.lookup_issn("87654321")
    assert found.status is QualisLookupStatus.FOUND
    assert found.record is not None
    assert found.record.issn == "8765-4321"
    assert found.record.stratum == "A2"

    assert service.lookup_issn("1111-1111").status is QualisLookupStatus.NOT_FOUND
    assert service.lookup_issn("not-an-issn").status is QualisLookupStatus.INVALID_ISSN
    assert service.lookup_issn("1234-567X").status is QualisLookupStatus.AMBIGUOUS
    assert (
        QualisLookupService(artifact_directory / "missing.sqlite3")
        .lookup_issn("8765-4321")
        .status
        is QualisLookupStatus.DATASET_UNAVAILABLE
    )


def test_lookup_any_deduplicates_preserves_order_and_detects_incompatibility(
    imported_dataset,
):
    database, _ = imported_dataset
    with closing(sqlite3.connect(database)) as connection:
        connection.executemany(
            """
            INSERT INTO qualis_records (
                issn, title, stratum, parent_area, quadrennium
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("1111-1111", "First A2", "A2", "Area", "2017-2020"),
                ("2222-2222", "Different A1", "A1", "Area", "2017-2020"),
            ],
        )
        connection.commit()

    service = QualisLookupService(database)
    ordered = service.lookup_any(
        ["invalid", "11111111", "1111-1111", "8765-4321"]
    )
    assert ordered.status is QualisLookupStatus.FOUND
    assert ordered.record is not None
    assert ordered.record.issn == "1111-1111"

    incompatible = service.lookup_any(["2222-2222", "8765-4321"])
    assert incompatible.status is QualisLookupStatus.AMBIGUOUS
    assert service.lookup_any(["invalid", None]).status is QualisLookupStatus.INVALID_ISSN
    assert service.lookup_any(["3333-3333"]).status is QualisLookupStatus.NOT_FOUND


def test_lookup_connection_is_read_only(imported_dataset):
    database, _ = imported_dataset
    service = QualisLookupService(database)

    connection = service._connect_read_only()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(
                """
                INSERT INTO qualis_records (
                    issn, title, stratum, parent_area, quadrennium
                ) VALUES ('9999-9999', 'No write', 'A1', 'Area', '2017-2020')
                """
            )
    finally:
        connection.close()


def test_qualis_modules_have_no_network_capes_orm_or_main_database_dependency():
    import app.scripts.import_qualis_dataset as importer_module
    import app.services.qualis_lookup_service as service_module

    for module in (importer_module, service_module):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        imported_modules = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        lowered = source.casefold()

        assert "httpx" not in imported_modules
        assert "requests" not in imported_modules
        assert not any(name.startswith("sqlalchemy") for name in imported_modules)
        assert "app.core.database" not in imported_modules
        assert "app.models" not in imported_modules
        assert "capes" not in lowered
