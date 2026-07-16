"""Read-only ISSN lookup against the separately imported local Qualis dataset."""

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from app.core.config import settings
from app.schemas.qualis import (
    QualisLookupResult,
    QualisLookupStatus,
    QualisRecord,
)
from app.utils.issn import normalize_issn


class QualisLookupService:
    """Provide deterministic local Qualis lookup without HTTP or ORM access."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        configured_path = Path(database_path or settings.QUALIS_DATABASE_PATH)
        if not configured_path.is_absolute():
            configured_path = Path(__file__).resolve().parents[2] / configured_path
        self._database_path = configured_path

    def _connect_read_only(self) -> sqlite3.Connection:
        """Open the dedicated dataset without permitting writes or creation."""
        database_uri = f"file:{self._database_path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def lookup_issn(self, issn: str | None) -> QualisLookupResult:
        """Return one reliable classification or a typed non-found status."""
        normalized = normalize_issn(issn)
        if normalized is None:
            return QualisLookupResult(status=QualisLookupStatus.INVALID_ISSN)
        if not self._database_path.is_file():
            return QualisLookupResult(status=QualisLookupStatus.DATASET_UNAVAILABLE)

        try:
            with closing(self._connect_read_only()) as connection:
                rows = connection.execute(
                    """
                    SELECT issn, title, stratum, parent_area, quadrennium
                    FROM qualis_records
                    WHERE issn = ?
                    ORDER BY id
                    """,
                    (normalized,),
                ).fetchall()
        except sqlite3.Error:
            return QualisLookupResult(status=QualisLookupStatus.DATASET_UNAVAILABLE)

        if not rows:
            return QualisLookupResult(status=QualisLookupStatus.NOT_FOUND)
        strata = {str(row["stratum"]).strip().casefold() for row in rows}
        if len(strata) != 1:
            return QualisLookupResult(status=QualisLookupStatus.AMBIGUOUS)

        row = rows[0]
        return QualisLookupResult(
            status=QualisLookupStatus.FOUND,
            record=QualisRecord(
                issn=row["issn"],
                title=row["title"],
                stratum=row["stratum"],
                parent_area=row["parent_area"],
                quadrennium=row["quadrennium"],
            ),
        )

    def lookup_any(self, issns: Iterable[str | None]) -> QualisLookupResult:
        """Return the first reliable ordered match unless classifications conflict."""
        normalized_issns: list[str] = []
        seen: set[str] = set()
        for value in issns:
            normalized = normalize_issn(value)
            if normalized is not None and normalized not in seen:
                seen.add(normalized)
                normalized_issns.append(normalized)

        if not normalized_issns:
            return QualisLookupResult(status=QualisLookupStatus.INVALID_ISSN)

        found: list[QualisRecord] = []
        for normalized in normalized_issns:
            result = self.lookup_issn(normalized)
            if result.status is QualisLookupStatus.DATASET_UNAVAILABLE:
                return result
            if result.status is QualisLookupStatus.AMBIGUOUS:
                return result
            if result.status is QualisLookupStatus.FOUND and result.record is not None:
                found.append(result.record)

        if not found:
            return QualisLookupResult(status=QualisLookupStatus.NOT_FOUND)
        if len({record.stratum.strip().casefold() for record in found}) > 1:
            return QualisLookupResult(status=QualisLookupStatus.AMBIGUOUS)
        return QualisLookupResult(
            status=QualisLookupStatus.FOUND,
            record=found[0],
        )
