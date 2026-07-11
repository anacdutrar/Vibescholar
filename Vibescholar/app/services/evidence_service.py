from sqlalchemy.orm import Session
from typing import List, Optional, Set
from app.repositories.project_settings_repository import ProjectSettingsRepository
from app.repositories.reference_repository import ReferenceRepository
from app.providers.mock_provider import MockProvider
from app.providers.openalex_provider import OpenAlexProvider
from app.providers.semantic_scholar_provider import SemanticScholarProvider
from app.models.reference import ProjectReference
from app.core.config import settings as app_settings
from app.core.logging import logger

class EvidenceService:
    def __init__(self):
        # Instantiate provider instances
        self.providers = {
            "mock": MockProvider(),
            "openalex": OpenAlexProvider(),
            "semanticscholar": SemanticScholarProvider()
        }

    def search(
        self,
        db: Session,
        sentence_text: str,
        project_id: int,
        excluded_reference_ids: Optional[Set[int]] = None,
    ) -> List[ProjectReference]:
        """
        Retrieves project settings and candidate references, maps the active search provider,
        and returns matching reference suggestions based on project preferences.
        """
        # 1. Fetch project settings (fallback to default settings if none created)
        settings_repo = ProjectSettingsRepository()
        project_settings = settings_repo.get_by_project_id(db, project_id)
        if not project_settings:
            project_settings = settings_repo.create_default(db, project_id)

        # Mock references must exist in project_references before a suggestion can reference them.
        _, found_ids, created_ids = ReferenceRepository.ensure_global_references(
            db, MockProvider.reference_payloads()
        )
        logger.info(
            "evidence.mock.references resolved found_ids=%s created_ids=%s",
            found_ids,
            created_ids,
        )

        # 2. Fetch candidate references (global references + project specific)
        candidates = ReferenceRepository.list_by_project(db, project_id)
        excluded_reference_ids = excluded_reference_ids or set()
        discarded_ids = [ref.id for ref in candidates if ref.id in excluded_reference_ids]
        candidates = [ref for ref in candidates if ref.id not in excluded_reference_ids]
        logger.info(
            "evidence.search project_id=%s settings=%s candidate_count=%s discarded_ids=%s",
            project_id,
            {
                "minimum_qualis": project_settings.minimum_qualis,
                "publication_year_min": project_settings.publication_year_min,
                "publication_year_max": project_settings.publication_year_max,
                "only_open_access": project_settings.only_open_access,
                "prefer_doi": project_settings.prefer_doi,
                "max_suggestions": project_settings.max_suggestions,
            },
            len(candidates),
            discarded_ids,
        )

        # 3. Determine active provider
        # In V1 MVP, we always fallback to the MockProvider unless config specifies otherwise
        provider_name = "mock"
        if not app_settings.USE_MOCK:
            # Future provision for other engines (defaults to mock if not implemented)
            provider_name = "mock"

        provider = self.providers.get(provider_name, self.providers["mock"])

        # 4. Search and filter candidates
        matches = provider.search(sentence_text, project_settings, candidates)
        logger.info(
            "evidence.search result_count=%s reference_ids=%s",
            len(matches),
            [reference.id for reference in matches],
        )
        return matches
