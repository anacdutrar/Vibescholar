from typing import List
from app.providers.interfaces import BaseEvidenceProvider
from app.models.reference import ProjectReference
from app.models.project_settings import ProjectSettings

QUALIS_RANK = {
    "A1": 9, "A2": 8, "A3": 7, "A4": 6,
    "B1": 5, "B2": 4, "B3": 3, "B4": 2, "C": 1
}

class MockProvider(BaseEvidenceProvider):
    def search(self, query: str, settings: ProjectSettings, candidates: List[ProjectReference]) -> List[ProjectReference]:
        filtered_list = []
        query_words = set(query.lower().replace(".", "").replace(",", "").split())

        # Qualis minimum rank threshold
        min_qualis_rank = QUALIS_RANK.get(settings.minimum_qualis, 0)

        for candidate in candidates:
            # 1. Qualis Score Filter
            cand_qualis_rank = QUALIS_RANK.get(candidate.qualis_score, 0)
            if cand_qualis_rank < min_qualis_rank:
                continue

            # 2. Publication Year Range Filter
            if settings.publication_year_min is not None:
                if candidate.year is None or candidate.year < settings.publication_year_min:
                    continue
            if settings.publication_year_max is not None:
                if candidate.year is None or candidate.year > settings.publication_year_max:
                    continue

            # 3. Open Access Filter
            if settings.only_open_access and candidate.availability != "ABERTO":
                continue

            filtered_list.append(candidate)

        # 4. Keyword relevance sorting
        # Count how many query words are present in the candidate title/abstract
        def calculate_relevance(ref: ProjectReference) -> int:
            text = (ref.title + " " + (ref.abstract or "")).lower()
            matches = sum(1 for word in query_words if word in text)
            return matches

        # 5. DOI Preference & Relevance Sorting
        # Sort key: (relevance_score DESC, has_doi DESC)
        def sort_key(ref: ProjectReference):
            relevance = calculate_relevance(ref)
            has_doi = 1 if (settings.prefer_doi and ref.doi) else 0
            return (relevance, has_doi)

        filtered_list.sort(key=sort_key, reverse=True)

        # 6. Apply max suggestions limit
        max_sug = settings.max_suggestions if settings.max_suggestions else 5
        return filtered_list[:max_sug]
