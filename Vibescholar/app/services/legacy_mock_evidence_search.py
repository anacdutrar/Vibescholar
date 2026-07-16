"""Temporary isolated adapter for the legacy offline mock evidence search."""

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models.reference import ProjectReference
from app.providers.mock_provider import MockProvider
from app.repositories.reference_repository import ReferenceRepository


class LegacyMockEvidenceSearch:
    """Preserve the pre-workflow mock behavior only for explicit offline mode."""

    def __init__(self, provider: MockProvider | None = None) -> None:
        self._provider = provider or MockProvider()

    def search_references(
        self,
        db: Session,
        sentence_text: str,
        project_id: int,
        project_settings,
        excluded_reference_ids: set[int],
    ) -> list[ProjectReference]:
        """Seed and query only legacy mock references without invoking the real workflow."""
        _, found_ids, created_ids = ReferenceRepository.ensure_global_references(
            db,
            MockProvider.reference_payloads(),
        )
        candidates = [
            reference
            for reference in ReferenceRepository.list_by_project(db, project_id)
            if reference.id not in excluded_reference_ids
        ]
        logger.info(
            "evidence.mock.references resolved found_ids=%s created_ids=%s candidate_count=%s",
            found_ids,
            created_ids,
            len(candidates),
        )
        return self._provider.search(sentence_text, project_settings, candidates)
