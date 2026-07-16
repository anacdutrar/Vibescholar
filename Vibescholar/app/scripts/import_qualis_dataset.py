"""Manual local XLSX importer for the dedicated Qualis SQLite dataset."""

import argparse
import hashlib
import os
import re
import sqlite3
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from app.core.config import Settings
from app.utils.issn import normalize_issn


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_COLUMN_ALIASES = {
    "issn": {"issn", "issn impresso", "issn eletronico"},
    "title": {"titulo", "titulo do periodico", "nome do periodico", "periodico"},
    "stratum": {"estrato", "qualis", "classificacao"},
    "parent_area": {"area mae", "area de avaliacao", "area"},
    "quadrennium": {
        "quadrienio",
        "quadrenio",
        "periodo de avaliacao",
        "periodo",
    },
}


@dataclass(frozen=True, slots=True)
class QualisImportResult:
    """Operational summary of one completed atomic dataset import."""

    database_path: Path
    quadrennium: str
    source_sha256: str
    rows_read: int
    rows_imported: int
    rows_rejected: int


def _normalize_header(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().casefold()
    return " ".join(text.split())


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if letters is None:
        raise ValueError(f"invalid XLSX cell reference: {reference}")
    result = 0
    for character in letters.group(0):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_MAIN_NS}}}si")
    ]


def _worksheet_paths(archive: zipfile.ZipFile) -> list[str]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(
        archive.read("xl/_rels/workbook.xml.rels")
    )
    targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall(
            f"{{{_PACKAGE_REL_NS}}}Relationship"
        )
    }
    paths: list[str] = []
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
        target = targets.get(relationship_id or "")
        if target:
            normalized = PurePosixPath("xl") / target.lstrip("/")
            paths.append(str(normalized))
    return paths


def _worksheet_rows(
    archive: zipfile.ZipFile,
    path: str,
    shared_strings: list[str],
):
    root = ElementTree.fromstring(archive.read(path))
    for row in root.findall(f".//{{{_MAIN_NS}}}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            reference = cell.attrib.get("r", "")
            cell_type = cell.attrib.get("t")
            value_node = cell.find(f"{{{_MAIN_NS}}}v")
            if cell_type == "inlineStr":
                value = "".join(
                    node.text or ""
                    for node in cell.iter(f"{{{_MAIN_NS}}}t")
                )
            elif value_node is None:
                value = ""
            elif cell_type == "s":
                try:
                    value = shared_strings[int(value_node.text or "")]
                except (ValueError, IndexError):
                    value = ""
            else:
                value = value_node.text or ""
            values[_column_index(reference)] = value
        if values:
            width = max(values) + 1
            yield [values.get(index, "") for index in range(width)]


def _xlsx_sheets(source_path: Path):
    try:
        with zipfile.ZipFile(source_path) as archive:
            shared_strings = _shared_strings(archive)
            for worksheet_path in _worksheet_paths(archive):
                yield list(
                    _worksheet_rows(
                        archive,
                        worksheet_path,
                        shared_strings,
                    )
                )
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError("source is not a readable XLSX workbook") from exc


def _locate_columns(rows: list[list[str]], quadrennium: str | None):
    required = {"issn", "title", "stratum", "parent_area"}
    if quadrennium is None:
        required.add("quadrennium")
    for row_index, row in enumerate(rows[:50]):
        mapped: dict[str, int] = {}
        for column_index, value in enumerate(row):
            header = _normalize_header(value)
            for field, aliases in _COLUMN_ALIASES.items():
                if header in aliases and field not in mapped:
                    mapped[field] = column_index
        if required.issubset(mapped):
            return row_index, mapped
    return None


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return " ".join(str(row[index]).strip().split())


def _source_sha256(source_path: Path) -> str:
    digest = hashlib.sha256()
    with source_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE dataset_metadata (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            quadrennium TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            rows_read INTEGER NOT NULL,
            rows_imported INTEGER NOT NULL,
            rows_rejected INTEGER NOT NULL
        );

        CREATE TABLE qualis_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issn TEXT NOT NULL,
            title TEXT NOT NULL,
            stratum TEXT NOT NULL,
            parent_area TEXT NOT NULL,
            quadrennium TEXT NOT NULL,
            UNIQUE (issn, stratum, quadrennium)
        );

        CREATE INDEX idx_qualis_records_issn
        ON qualis_records (issn);
        """
    )


def import_qualis_dataset(
    source_path: str | Path,
    database_path: str | Path,
    *,
    quadrennium: str | None = None,
) -> QualisImportResult:
    """Import one local XLSX into a newly recreated dedicated SQLite database."""
    source = Path(source_path)
    destination = Path(database_path)
    if not source.is_file():
        raise FileNotFoundError(f"Qualis XLSX not found: {source}")

    selected_rows: list[list[str]] | None = None
    header_index = -1
    columns: dict[str, int] = {}
    for rows in _xlsx_sheets(source):
        located = _locate_columns(rows, quadrennium)
        if located is not None:
            header_index, columns = located
            selected_rows = rows
            break
    if selected_rows is None:
        raise ValueError("required Qualis columns were not found in the XLSX")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(f"{destination}.tmp")
    if temporary.exists():
        temporary.unlink()

    rows_read = 0
    rows_imported = 0
    rows_rejected = 0
    imported_quadrennia: set[str] = set()
    try:
        connection = sqlite3.connect(temporary)
        try:
            _create_schema(connection)
            for row in selected_rows[header_index + 1 :]:
                if not any(str(value).strip() for value in row):
                    continue
                rows_read += 1
                normalized_issn = normalize_issn(_cell(row, columns["issn"]))
                title = _cell(row, columns["title"])
                stratum = _cell(row, columns["stratum"]).upper()
                parent_area = _cell(row, columns["parent_area"])
                row_quadrennium = (
                    " ".join(quadrennium.strip().split())
                    if quadrennium is not None
                    else _cell(row, columns["quadrennium"])
                )
                if not all(
                    (
                        normalized_issn,
                        title,
                        stratum,
                        parent_area,
                        row_quadrennium,
                    )
                ):
                    rows_rejected += 1
                    continue

                imported_quadrennia.add(row_quadrennium)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO qualis_records (
                        issn, title, stratum, parent_area, quadrennium
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_issn,
                        title,
                        stratum,
                        parent_area,
                        row_quadrennium,
                    ),
                )
                rows_imported += cursor.rowcount

            if len(imported_quadrennia) != 1:
                raise ValueError(
                    "one import must represent exactly one non-empty quadrennium"
                )
            imported_quadrennium = next(iter(imported_quadrennia))
            source_hash = _source_sha256(source)
            connection.execute(
                """
                INSERT INTO dataset_metadata (
                    id, quadrennium, imported_at, source_sha256,
                    rows_read, rows_imported, rows_rejected
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    imported_quadrennium,
                    datetime.now(timezone.utc).isoformat(),
                    source_hash,
                    rows_read,
                    rows_imported,
                    rows_rejected,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

    return QualisImportResult(
        database_path=destination,
        quadrennium=imported_quadrennium,
        source_sha256=source_hash,
        rows_read=rows_read,
        rows_imported=rows_imported,
        rows_rejected=rows_rejected,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import one local official Qualis XLSX into dedicated SQLite."
    )
    parser.add_argument("--source", required=True, help="Path to the local XLSX file.")
    parser.add_argument(
        "--database",
        help="Destination SQLite path; defaults to QUALIS_DATABASE_PATH.",
    )
    parser.add_argument(
        "--quadrennium",
        help="Quadrennium used when the XLSX has no corresponding column.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = Settings()
    result = import_qualis_dataset(
        args.source,
        args.database or config.QUALIS_DATABASE_PATH,
        quadrennium=args.quadrennium,
    )
    print(
        "Qualis import completed: "
        f"rows_read={result.rows_read} "
        f"rows_imported={result.rows_imported} "
        f"rows_rejected={result.rows_rejected} "
        f"database={result.database_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
