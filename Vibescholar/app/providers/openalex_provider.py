from typing import List
from app.providers.interfaces import BaseEvidenceProvider
from app.models.reference import ProjectReference
from app.models.project_settings import ProjectSettings

class OpenAlexProvider(BaseEvidenceProvider):
    def search(self, query: str, settings: ProjectSettings, candidates: List[ProjectReference]) -> List[ProjectReference]:
        # Stub for V2 integration - returns empty list in V1 Mock mode
        return []
