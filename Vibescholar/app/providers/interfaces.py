from abc import ABC, abstractmethod
from typing import List
from app.models.reference import ProjectReference
from app.models.project_settings import ProjectSettings

class BaseEvidenceProvider(ABC):
    @abstractmethod
    def search(self, query: str, settings: ProjectSettings, candidates: List[ProjectReference]) -> List[ProjectReference]:
        """
        Search for references matching the sentence query, applying the project settings filters.
        """
        pass
