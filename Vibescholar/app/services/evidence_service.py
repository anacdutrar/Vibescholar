from sqlalchemy.orm import Session
from typing import List
from app.repositories.project_settings_repository import ProjectSettingsRepository
from app.repositories.reference_repository import ReferenceRepository
from app.providers.mock_provider import MockProvider
from app.providers.openalex_provider import OpenAlexProvider
from app.providers.semantic_scholar_provider import SemanticScholarProvider
from app.models.reference import ProjectReference
from app.core.config import settings as app_settings

class EvidenceService:
    def __init__(self):
        # Instantiate provider instances
        self.providers = {
            "mock": MockProvider(),
            "openalex": OpenAlexProvider(),
            "semanticscholar": SemanticScholarProvider()
        }

    def search(self, db: Session, sentence_text: str, project_id: int) -> List[ProjectReference]:
        """
        Retrieves project settings and candidate references, maps the active search provider,
        and returns matching reference suggestions based on project preferences.
        """
        # 1. Fetch project settings (fallback to default settings if none created)
        settings_repo = ProjectSettingsRepository()
        project_settings = settings_repo.get_by_project_id(db, project_id)
        if not project_settings:
            project_settings = settings_repo.create_default(db, project_id)

        # 2. Fetch candidate references (global references + project specific)
        candidates = ReferenceRepository.list_by_project(db, project_id)

        # 3. Determine active provider
        # In V1 MVP, we always fallback to the MockProvider unless config specifies otherwise
        provider_name = "mock"
        if not app_settings.USE_MOCK:
            # Future provision for other engines (defaults to mock if not implemented)
            provider_name = "mock"

        provider = self.providers.get(provider_name, self.providers["mock"])

        # 4. Search and filter candidates
        return provider.search(sentence_text, project_settings, candidates)
