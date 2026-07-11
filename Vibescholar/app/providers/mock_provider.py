from typing import List
from app.providers.interfaces import BaseEvidenceProvider
from app.models.reference import ProjectReference
from app.models.project_settings import ProjectSettings

QUALIS_RANK = {
    "A1": 9, "A2": 8, "A3": 7, "A4": 6,
    "B1": 5, "B2": 4, "B3": 3, "B4": 2, "C": 1
}

class MockProvider(BaseEvidenceProvider):
    MOCK_REFERENCES = [
        ("Ana Lima; Bruno Costa", "Inteligência artificial aplicada à escrita acadêmica", "Revista Brasileira de IA", 2023, "A1", "10.1000/ia-escrita", "ABERTO", "inteligência artificial escrita científica acadêmica"),
        ("Carla Mendes", "Boas práticas de escrita científica em dissertações", "Educação e Pesquisa", 2021, "A2", "10.1000/escrita-cientifica", "ABERTO", "escrita científica dissertações teses metodologia"),
        ("Diego Souza", "Integridade acadêmica e versionamento de documentos", "Journal of Academic Integrity", 2022, "A1", "10.1000/integridade", "ABERTO", "integridade acadêmica versionamento autoria"),
        ("Elena Rocha", "Recuperação de informação para revisão bibliográfica", "Information Retrieval Review", 2020, "A2", "10.1000/ir-review", "FECHADO", "recuperação informação referências busca evidência"),
        ("Felipe Nunes", "Visão computacional e análise automatizada de imagens", "Computer Vision Letters", 2024, "A1", "10.1000/visao-computacional", "ABERTO", "visão computacional imagens análise"),
        ("Gabriela Pinto", "Redes neurais profundas em sistemas inteligentes", "Neural Systems", 2022, "A1", "10.1000/redes-neurais", "ABERTO", "redes neurais deep learning inteligência artificial"),
        ("Helena Dias", "Metodologia científica para pesquisa aplicada", "Métodos em Pesquisa", 2019, "B1", "10.1000/metodologia", "ABERTO", "metodologia científica pesquisa aplicada"),
        ("Igor Martins", "Ética, autoria e transparência no uso de IA", "Ethics in Science", 2023, "A2", "10.1000/etica-ia", "ABERTO", "ética autoria transparência inteligência artificial"),
        ("Joana Alves", "Sistemas de apoio à produção textual acadêmica", "Tecnologias Educacionais", 2021, "B1", "10.1000/producao-textual", "FECHADO", "produção textual acadêmica escrita"),
        ("Lucas Pereira", "Métricas para avaliação da fundamentação científica", "Scientometrics Today", 2020, "A2", "10.1000/fundamentacao", "ABERTO", "fundamentação científica citações evidências"),
        ("Marina Teixeira", "Gestão de referências em projetos de pesquisa", "Library Science Review", 2018, "B1", "10.1000/gestao-referencias", "ABERTO", "referências bibliográficas biblioteca pesquisa"),
        ("Rafael Gomes", "Qualidade de dados em aplicações acadêmicas web", "Software Acadêmico", 2022, "A2", "10.1000/dados-academicos", "ABERTO", "dados acadêmicos plataforma web qualidade"),
    ]

    @classmethod
    def reference_payloads(cls) -> list[dict]:
        """Return seed data without inventing database identifiers."""
        payloads = []
        for data in cls.MOCK_REFERENCES:
            authors, title, journal, year, qualis, doi, availability, abstract = data
            payloads.append({
                "authors": authors,
                "title": title,
                "journal": journal,
                "year": year,
                "qualis_score": qualis,
                "doi": doi,
                "availability": availability,
                "abstract": abstract,
            })
        return payloads

    def _mock_reference(self, index: int, data: tuple) -> ProjectReference:
        """Compatibility helper returning an unpersisted reference with no fake ID."""
        authors, title, journal, year, qualis, doi, availability, abstract = data
        return ProjectReference(
            id=None,
            project_id=None,
            authors=authors,
            title=title,
            journal=journal,
            year=year,
            qualis_score=qualis,
            doi=doi,
            availability=availability,
            abstract=abstract,
        )

    def search(self, query: str, settings: ProjectSettings, candidates: List[ProjectReference]) -> List[ProjectReference]:
        pool = list(candidates or [])
        filtered_list = []
        query_words = set(query.lower().replace(".", "").replace(",", "").split())

        # Qualis minimum rank threshold
        min_qualis_rank = QUALIS_RANK.get(settings.minimum_qualis, 0)

        seen_keys = set()
        for candidate in pool:
            key = (getattr(candidate, "doi", None) or getattr(candidate, "title", "")).lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)
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

        max_sug = min(max(settings.max_suggestions if settings.max_suggestions else 5, 3), 5)
        thematic = [ref for ref in filtered_list if calculate_relevance(ref) > 0]
        generic = [ref for ref in filtered_list if calculate_relevance(ref) == 0]
        return (thematic + generic)[:max_sug]
