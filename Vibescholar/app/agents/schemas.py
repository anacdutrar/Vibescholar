"""Structured-output contracts for search planning and evidence evaluation."""

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class SentenceType(str, Enum):
    """Semantic categories assigned to a sentence by the search planner."""

    SCIENTIFIC_CLAIM = "scientific_claim"
    CITATION_CLAIM = "citation_claim"
    NON_SCIENTIFIC = "non_scientific"
    INVALID = "invalid"


class SearchToolName(str, Enum):
    """Conceptual actions available to the search planner for one round."""

    NONE = "none"
    SEARCH_ACADEMIC_WORKS = "search_academic_works"
    RESOLVE_CITATION_METADATA = "resolve_citation_metadata"


class CitationHint(BaseModel):
    """Citation metadata detected in a sentence before external resolution."""

    raw: str = Field(min_length=1, description="Citation fragment exactly as detected in the sentence.")
    doi: str | None = Field(default=None, description="DOI detected in the citation, when available.")
    author: str | None = Field(default=None, description="Author token detected in the citation, when available.")
    year: int | None = Field(default=None, description="Publication year detected in the citation, when available.")
    title: str | None = Field(default=None, description="Work title inferred from the citation, when available.")

    @field_validator("raw")
    @classmethod
    def normalize_raw_hint(cls, value: str) -> str:
        """Strip and reject citation fragments without visible content."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("citation hint must not be empty")
        return stripped

    @field_validator("doi", "author", "title", mode="before")
    @classmethod
    def normalize_optional_hint_text(cls, value):
        """Preserve supplied metadata while normalizing empty optional strings."""
        if isinstance(value, str):
            return value.strip() or None
        return value


class SearchPlan(BaseModel):
    """One structured decision produced by the SearchAgent for a single round."""

    sentence_type: SentenceType = Field(description="Semantic classification of the input sentence.")
    should_search: bool = Field(description="Whether the backend should execute the selected search action.")
    selected_tool: SearchToolName = Field(description="Single conceptual tool selected for this round.")
    topic: str | None = Field(default=None, description="Concise academic topic extracted from the sentence.")
    tags: list[str] = Field(default_factory=list, description="Academic concepts useful for retrieval and filtering.")
    queries: list[str] = Field(default_factory=list, description="Unique academic queries proposed for this round.")
    citation_hints: list[CitationHint] = Field(
        default_factory=list,
        description="Citation fragments that may be resolved to bibliographic metadata.",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Planner confidence signal between zero and one.")
    reason: str = Field(min_length=1, description="Brief explanation for the selected sentence type and action.")

    @field_validator("queries")
    @classmethod
    def normalize_queries(cls, queries: list[str]) -> list[str]:
        """Strip, reject empty values, and enforce case-insensitive uniqueness."""
        normalized: list[str] = []
        seen: set[str] = set()
        for query in queries:
            stripped = query.strip()
            if not stripped:
                raise ValueError("queries must not contain empty values")
            key = stripped.casefold()
            if key in seen:
                raise ValueError("queries must be unique after normalization")
            seen.add(key)
            normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def validate_action_consistency(self) -> "SearchPlan":
        """Ensure the plan represents exactly one internally consistent action."""
        if not self.should_search:
            if self.selected_tool is not SearchToolName.NONE:
                raise ValueError("should_search=false requires selected_tool=none")
            if self.queries:
                raise ValueError("selected_tool=none requires an empty queries list")
            return self

        if self.selected_tool is SearchToolName.NONE:
            raise ValueError("should_search=true requires a search tool")
        if self.selected_tool is SearchToolName.SEARCH_ACADEMIC_WORKS:
            if not 1 <= len(self.queries) <= 5:
                raise ValueError("search_academic_works requires between one and five queries")
        elif (
            self.selected_tool is SearchToolName.RESOLVE_CITATION_METADATA
            and not self.queries
            and not self.citation_hints
        ):
            raise ValueError("citation resolution without queries requires at least one citation hint")
        return self


class ProviderRoundResult(BaseModel):
    """Aggregated result of one academic provider during a search round."""

    provider: str = Field(min_length=1, description="Stable provider identifier.")
    success: bool = Field(description="Whether the provider completed without an operational error.")
    results_found: int = Field(ge=0, description="Number of raw candidates returned by the provider.")
    error_code: str | None = Field(default=None, description="Stable error code when the provider failed.")


class SearchRoundSummary(BaseModel):
    """Aggregate-only feedback supplied to the SearchAgent for query refinement."""

    round_number: int = Field(ge=1, description="One-based search round number.")
    queries_used: list[str] = Field(description="Queries already executed in this round.")
    provider_results: list[ProviderRoundResult] = Field(
        default_factory=list,
        description="Operational result reported by each provider.",
    )
    raw_results: int = Field(ge=0, description="Total raw candidates returned by all providers.")
    after_deduplication: int = Field(ge=0, description="Candidates remaining after canonical deduplication.")
    after_filters: int = Field(ge=0, description="Candidates remaining after deterministic project filters.")
    evaluated_candidates: int = Field(ge=0, description="Candidates already evaluated semantically.")
    strong_support_count: int = Field(ge=0, description="Strong-support results accumulated so far.")
    partial_support_count: int = Field(ge=0, description="Partial-support results accumulated so far.")
    missing_strong_evidence: int = Field(ge=0, description="Strong results still missing from the configured target.")


class EvidenceVerdict(str, Enum):
    """Conservative semantic verdicts produced by the evidence evaluator."""

    STRONG_SUPPORT = "strong_support"
    PARTIAL_SUPPORT = "partial_support"
    NO_SUPPORT = "no_support"
    CONTRADICTS = "contradicts"
    INSUFFICIENT_ABSTRACT = "insufficient_abstract"


class EvidenceAnalysisScope(str, Enum):
    """Metadata scope actually available to the evidence evaluator."""

    TITLE_ONLY = "title_only"
    TITLE_AND_ABSTRACT = "title_and_abstract"


class EvidenceEvaluation(BaseModel):
    """Semantic evaluation tied to an unchanged transient candidate key."""

    candidate_key: str = Field(min_length=1, description="Canonical candidate key received from the backend.")
    verdict: EvidenceVerdict = Field(description="Evaluator verdict for the sentence-candidate relationship.")
    confidence: float = Field(ge=0.0, le=1.0, description="Evaluator confidence signal between zero and one.")
    reason: str = Field(min_length=1, description="Conservative explanation grounded in title and abstract.")
    analysis_scope: EvidenceAnalysisScope = Field(description="Candidate metadata used by the evaluation.")


class EvidenceEvaluationBatch(BaseModel):
    """Structured output containing evaluations for one bounded candidate batch."""

    evaluations: list[EvidenceEvaluation] = Field(
        description="Evaluations whose candidate keys must match the submitted candidates.",
    )
