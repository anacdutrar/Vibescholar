"""Transient provider and evidence-candidate contracts without ORM dependencies."""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.schemas import (
    CitationHint,
    EvidenceAnalysisScope,
    EvidenceVerdict,
    SearchToolName,
    SentenceType,
)
from app.core.config import settings


class AcademicSearchInput(BaseModel):
    """Validated arguments for a cross-provider academic-work search."""

    queries: list[str] = Field(
        min_length=1,
        max_length=5,
        description="Distinct academic search queries selected by the model.",
    )
    limit_per_provider: int = Field(
        gt=0,
        description="Requested result limit for each enabled academic provider.",
    )

    @field_validator("queries")
    @classmethod
    def normalize_queries(cls, queries: list[str]) -> list[str]:
        """Strip queries and reject empty or case-insensitive duplicate values."""
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


class CitationResolutionInput(BaseModel):
    """Validated citation hints submitted for metadata resolution."""

    citation_hints: list[CitationHint] = Field(
        min_length=1,
        description="One or more citation hints already detected in the sentence.",
    )


class AcademicSearchStatus(str, Enum):
    """Operational academic-search states without automatic pipeline behavior.

    Success and partial success may continue a future pipeline, empty may allow
    refinement, and failed denotes an operational failure rather than a semantic
    refinement signal. Those transitions are intentionally not implemented here.
    """

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    EMPTY = "empty"
    FAILED = "failed"


class CitationResolutionStatus(str, Enum):
    """Operational citation-resolution states without automatic follow-up.

    Not-found may permit a future resolution strategy. Operational retry belongs
    to a backend or provider, while refinement remains a separate future inference.
    """

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class ToolExecutionStatus(str, Enum):
    """Backend execution status for one bounded search-tool decision."""

    NOT_CALLED = "not_called"
    SUCCESS = "success"
    FAILED = "failed"


class ProviderExecutionSummary(BaseModel):
    """Safe operational summary for one backend-selected academic provider."""

    provider: str = Field(min_length=1, description="Backend-selected provider identifier.")
    success: bool = Field(description="Whether this provider completed successfully.")
    results_found: int = Field(ge=0, description="Raw results returned by this provider.")
    error_code: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.:-]+$",
        description="Optional safe operational code without stack traces or credentials.",
    )

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        """Strip and reject empty provider identifiers."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider must not be empty")
        return stripped

    @field_validator("error_code", mode="before")
    @classmethod
    def normalize_error_code(cls, value):
        """Normalize optional error codes before applying the safe pattern."""
        if isinstance(value, str):
            return value.strip() or None
        return value


class AcademicSearchToolResult(BaseModel):
    """Public academic-search result containing only safe operational metadata."""

    status: AcademicSearchStatus = Field(description="Aggregate academic-search status.")
    providers: list[ProviderExecutionSummary] = Field(
        description="Operational summaries for backend-selected providers.",
    )
    raw_results: int = Field(ge=0, description="Total raw provider results before deduplication.")
    after_deduplication: int = Field(ge=0, description="Candidate count after canonical deduplication.")
    message: str = Field(min_length=1, max_length=500, description="Safe user-neutral operational message.")
    requested_limit_per_provider: int = Field(gt=0, description="Limit requested in the tool call.")
    effective_limit_per_provider: int = Field(gt=0, description="Limit enforced by backend configuration.")

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        """Strip the bounded public operational message."""
        return value.strip()

    @model_validator(mode="after")
    def validate_operational_consistency(self) -> "AcademicSearchToolResult":
        """Validate counts, limits, provider outcomes, and aggregate status."""
        if self.after_deduplication > self.raw_results:
            raise ValueError("after_deduplication cannot exceed raw_results")
        if self.raw_results != sum(provider.results_found for provider in self.providers):
            raise ValueError("raw_results must equal the provider result total")
        if self.effective_limit_per_provider > self.requested_limit_per_provider:
            raise ValueError("effective limit cannot exceed the requested limit")
        if self.effective_limit_per_provider > settings.RESULTS_PER_PROVIDER:
            raise ValueError("effective limit exceeds the configured provider limit")

        successful = [provider for provider in self.providers if provider.success]
        failed = [provider for provider in self.providers if not provider.success]
        if self.status is AcademicSearchStatus.SUCCESS:
            if not self.providers or failed or self.after_deduplication < 1:
                raise ValueError("success requires all providers and at least one result")
        elif self.status is AcademicSearchStatus.PARTIAL_SUCCESS:
            if (
                not any(provider.results_found > 0 for provider in successful)
                or not failed
                or self.after_deduplication < 1
            ):
                raise ValueError("partial_success requires successful and failed providers with results")
        elif self.status is AcademicSearchStatus.EMPTY:
            if not self.providers or failed or self.after_deduplication != 0:
                raise ValueError("empty requires successful providers and zero results")
        elif self.status is AcademicSearchStatus.FAILED:
            if self.after_deduplication != 0 or any(provider.results_found for provider in self.providers):
                raise ValueError("failed cannot contain usable results")
        return self


class CitationResolutionToolResult(BaseModel):
    """Public citation-resolution result without bibliographic metadata."""

    status: CitationResolutionStatus = Field(description="Aggregate citation-resolution status.")
    matches_found: int = Field(ge=0, description="Number of internal candidate matches.")
    message: str = Field(min_length=1, max_length=500, description="Safe user-neutral operational message.")

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        """Strip the bounded public operational message."""
        return value.strip()

    @model_validator(mode="after")
    def validate_status_count(self) -> "CitationResolutionToolResult":
        """Ensure each resolution status agrees with its public match count."""
        if self.status is CitationResolutionStatus.RESOLVED and self.matches_found < 1:
            raise ValueError("resolved requires at least one match")
        if self.status is CitationResolutionStatus.AMBIGUOUS and self.matches_found < 2:
            raise ValueError("ambiguous requires at least two matches")
        if self.status in {CitationResolutionStatus.NOT_FOUND, CitationResolutionStatus.FAILED}:
            if self.matches_found != 0:
                raise ValueError(f"{self.status.value} requires zero matches")
        return self


class SearchToolCallRecord(BaseModel):
    """Validated record of one function tool call emitted by the model."""

    tool_call_id: str = Field(min_length=1, description="SDK tool-call identifier preserved for future use.")
    tool_name: SearchToolName = Field(description="Whitelisted function name received from the SDK response.")
    validated_arguments: AcademicSearchInput | CitationResolutionInput = Field(
        description="Pydantic-validated arguments associated with the real function call.",
    )

    @model_validator(mode="after")
    def reject_none_action(self) -> "SearchToolCallRecord":
        """Ensure the whitelisted action and validated DTO remain consistent."""
        if self.tool_name is SearchToolName.NONE:
            raise ValueError("a tool-call record cannot use the none action")
        if (
            self.tool_name is SearchToolName.SEARCH_ACADEMIC_WORKS
            and not isinstance(self.validated_arguments, AcademicSearchInput)
        ):
            raise ValueError("academic search requires AcademicSearchInput")
        if (
            self.tool_name is SearchToolName.RESOLVE_CITATION_METADATA
            and not isinstance(self.validated_arguments, CitationResolutionInput)
        ):
            raise ValueError("citation resolution requires CitationResolutionInput")
        return self


def normalize_text(value: str, *, remove_punctuation: bool = False) -> str:
    """Return stable Unicode text with case folding and normalized whitespace."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if remove_punctuation:
        normalized = "".join(
            " " if unicodedata.category(character).startswith("P") else character
            for character in normalized
        )
    return " ".join(normalized.split())


def normalize_doi(value: str | None) -> str | None:
    """Normalize common DOI URL and label prefixes without validating DOI semantics."""
    if not value:
        return None
    normalized = value.strip().casefold()
    normalized = re.sub(r"^(?:https?://)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized).strip()
    return normalized or None


def is_valid_doi(value: str | None) -> bool:
    """Return whether a normalized DOI has the standard registrant/suffix shape."""
    normalized = normalize_doi(value)
    return bool(normalized and re.fullmatch(r"10\.\d{4,9}/\S+", normalized))


def normalize_title(value: str | None) -> str:
    """Normalize a title for deterministic comparison without semantic changes."""
    return normalize_text(value or "", remove_punctuation=True)


def normalize_issn(value: str | None) -> str | None:
    """Normalize a syntactically usable print or electronic ISSN."""
    if not value:
        return None
    compact = re.sub(r"^e?issn:\s*", "", value.strip(), flags=re.IGNORECASE)
    compact = re.sub(r"[^0-9Xx]", "", compact).upper()
    if not re.fullmatch(r"\d{7}[\dX]", compact):
        return None
    return f"{compact[:4]}-{compact[4:]}"


def normalize_authors(values: Iterable[str] | None) -> list[str]:
    """Strip author names and retain their provider order without duplicates."""
    authors: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        name = " ".join(str(value).strip().split())
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            authors.append(name)
    return authors


def build_candidate_key(
    *,
    provider: str,
    doi: str | None = None,
    external_id: str | None = None,
    title: str | None = None,
    year: int | None = None,
) -> str:
    """Build a deterministic candidate key using DOI, external ID, then title and year."""
    normalized_provider = normalize_text(provider or "")
    if not normalized_provider:
        raise ValueError("provider is required to build candidate_key")

    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"

    normalized_external_id = external_id.strip().casefold() if external_id else ""
    if normalized_external_id:
        return f"{normalized_provider}:{normalized_external_id}"

    normalized_title = normalize_title(title)
    if normalized_title:
        suffix = f":{year}" if year is not None else ""
        return f"{normalized_provider}:title:{normalized_title}{suffix}"

    raise ValueError("candidate requires a DOI, external_id, or usable title")


class ReferenceCandidate(BaseModel):
    """Normalized transient academic work returned by a provider, never an ORM entity."""

    model_config = ConfigDict(frozen=True)

    external_id: str | None = Field(default=None, description="Provider-specific work identifier.")
    provider: str = Field(min_length=1, description="Stable identifier of the source provider.")
    title: str = Field(default="", description="Normalized bibliographic title when available.")
    authors: list[str] = Field(default_factory=list, description="Author names in provider order.")
    journal: str | None = Field(default=None, description="Journal or venue name when available.")
    year: int | None = Field(default=None, description="Publication year when available.")
    doi: str | None = Field(default=None, description="DOI in provider form; normalized only for candidate_key.")
    abstract: str | None = Field(default=None, description="Abstract supplied by the provider when available.")
    availability: str | None = Field(default=None, description="Provider-normalized access availability.")
    language: str | None = Field(default=None, description="Language code or provider language label.")
    source_url: str | None = Field(default=None, description="Canonical source page URL when available.")
    provider_relevance_score: float | None = Field(
        default=None,
        description="Optional provider relevance score without an assumed universal range.",
    )
    issn: str | None = Field(default=None, description="Normalized linking ISSN when supplied.")
    eissn: str | None = Field(default=None, description="Normalized electronic ISSN when supplied.")
    issns: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Immutable normalized ISSNs supplied for the publication venue.",
    )
    publication_type: str | None = Field(default=None, description="Provider publication-type label.")
    citation_count: int | None = Field(
        default=None,
        ge=0,
        description="Provider citation count when available.",
    )
    is_open_access: bool | None = Field(
        default=None,
        description="Provider open-access indicator when available.",
    )
    candidate_key: str = Field(
        description="Canonical stable identity generated from bibliographic identifiers.",
    )

    @model_validator(mode="before")
    @classmethod
    def assign_canonical_candidate_key(cls, value):
        """Replace any external key with the canonical identity before validation."""
        if not isinstance(value, Mapping):
            return value
        candidate = dict(value)
        candidate["candidate_key"] = build_candidate_key(
            provider=candidate.get("provider", ""),
            doi=candidate.get("doi"),
            external_id=candidate.get("external_id"),
            title=candidate.get("title"),
            year=candidate.get("year"),
        )
        return candidate

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        """Normalize provider identity for stable keys and comparisons."""
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("provider must not be empty")
        return normalized

    @field_validator("external_id", "title", "doi", mode="before")
    @classmethod
    def strip_identity_fields(cls, value):
        """Remove external whitespace while preserving provider metadata content."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("authors", mode="before")
    @classmethod
    def normalize_candidate_authors(cls, value):
        """Normalize provider author names while retaining their order."""
        return normalize_authors(value)

    @field_validator("issn", "eissn", mode="before")
    @classmethod
    def normalize_candidate_issn(cls, value):
        """Normalize individual ISSN values and discard malformed values."""
        return normalize_issn(value)

    @field_validator("issns", mode="before")
    @classmethod
    def normalize_candidate_issns(cls, value):
        """Normalize and deduplicate immutable venue ISSNs."""
        normalized: list[str] = []
        for item in value or ():
            issn = normalize_issn(item)
            if issn and issn not in normalized:
                normalized.append(issn)
        return tuple(normalized)


def candidate_completeness(candidate: ReferenceCandidate) -> int:
    """Return a deterministic metadata-completeness score for transient merging."""
    scalar_fields = (
        "external_id", "title", "journal", "year", "doi", "abstract", "availability",
        "language", "source_url", "provider_relevance_score", "issn", "eissn",
        "publication_type", "citation_count", "is_open_access",
    )
    return sum(getattr(candidate, field) not in (None, "") for field in scalar_fields) + len(
        candidate.authors
    ) + len(candidate.issns)


def _deduplication_key(candidate: ReferenceCandidate) -> str:
    """Build the cross-provider identity used only for transient deduplication."""
    doi = normalize_doi(candidate.doi)
    if doi:
        return f"doi:{doi}"
    title = normalize_title(candidate.title)
    if title and candidate.year is not None:
        return f"title:{title}:{candidate.year}"
    return candidate.candidate_key


def _merge_candidates(
    preferred: ReferenceCandidate,
    secondary: ReferenceCandidate,
) -> ReferenceCandidate:
    """Fill missing metadata on the deterministic preferred candidate."""
    values = preferred.model_dump(exclude={"candidate_key"})
    secondary_values = secondary.model_dump(exclude={"candidate_key"})
    for field, value in secondary_values.items():
        if field in {"provider", "external_id"}:
            continue
        if field == "authors":
            if len(value) > len(values[field]):
                values[field] = value
        elif field == "issns":
            values[field] = tuple(dict.fromkeys((*values[field], *value)))
        elif values[field] in (None, "", [], ()) and value not in (None, "", [], ()):
            values[field] = value
    return ReferenceCandidate(**values)


def deduplicate_reference_candidates(
    candidates: Iterable[ReferenceCandidate],
) -> list[ReferenceCandidate]:
    """Deduplicate transient candidates and retain the most complete metadata."""
    selected: dict[str, ReferenceCandidate] = {}
    order: list[str] = []
    for candidate in candidates:
        key = _deduplication_key(candidate)
        if key not in selected:
            selected[key] = candidate
            order.append(key)
            continue
        current = selected[key]
        if candidate_completeness(candidate) > candidate_completeness(current):
            selected[key] = _merge_candidates(candidate, current)
        else:
            selected[key] = _merge_candidates(current, candidate)
    return [selected[key] for key in order]


class AcademicSearchExecutionResult(BaseModel):
    """Internal academic-search result retaining complete transient candidates."""

    candidates: list[ReferenceCandidate] = Field(description="Internal deduplicated reference candidates.")
    public_result: AcademicSearchToolResult = Field(description="Safe aggregate result for external use.")

    @model_validator(mode="after")
    def validate_candidate_count(self) -> "AcademicSearchExecutionResult":
        """Keep the internal candidates aligned with the public deduplicated count."""
        if len(self.candidates) != self.public_result.after_deduplication:
            raise ValueError("candidate count must equal after_deduplication")
        return self

    def to_public_result(self) -> AcademicSearchToolResult:
        """Return only the safe public result, never candidates or internal metadata."""
        return self.public_result


class CitationResolutionExecutionResult(BaseModel):
    """Internal citation-resolution result retaining complete candidate matches."""

    matches: list[ReferenceCandidate] = Field(description="Internal reference candidates matching citation hints.")
    public_result: CitationResolutionToolResult = Field(description="Safe aggregate result for external use.")

    @model_validator(mode="after")
    def validate_match_count(self) -> "CitationResolutionExecutionResult":
        """Keep internal matches aligned with the public match count."""
        if len(self.matches) != self.public_result.matches_found:
            raise ValueError("match count must equal matches_found")
        return self

    def to_public_result(self) -> CitationResolutionToolResult:
        """Return only the safe public result, never matches or bibliographic metadata."""
        return self.public_result


class SearchToolExecutionOutcome(BaseModel):
    """Backend-owned result containing exactly one action-compatible execution."""

    sentence_type: SentenceType = Field(description="Sentence classification derived by the backend flow.")
    action_taken: SearchToolName = Field(description="Action established from the actual SDK tool call.")
    tool_call_id: str | None = Field(default=None, description="Preserved SDK tool-call identifier.")
    tool_execution: AcademicSearchExecutionResult | CitationResolutionExecutionResult | None = Field(
        default=None,
        description="Internal execution result for the actual tool call.",
    )
    tool_call: SearchToolCallRecord | None = Field(
        default=None,
        description="Validated record of the actual SDK function call.",
    )
    reason: str = Field(min_length=1, description="Backend-owned explanation of the resulting status.")

    @model_validator(mode="after")
    def validate_execution_consistency(self) -> "SearchToolExecutionOutcome":
        """Require no execution for none and exactly the action-specific result otherwise."""
        if self.action_taken is SearchToolName.NONE:
            if self.tool_call_id is not None or self.tool_execution is not None or self.tool_call is not None:
                raise ValueError("the none action cannot contain a tool execution")
            return self
        if not self.tool_call_id or self.tool_call is None:
            raise ValueError("a called action requires its SDK call identifier and record")
        if self.tool_call.tool_call_id != self.tool_call_id or self.tool_call.tool_name is not self.action_taken:
            raise ValueError("tool-call metadata must match the executed action")
        if (
            self.action_taken is SearchToolName.SEARCH_ACADEMIC_WORKS
            and not isinstance(self.tool_execution, AcademicSearchExecutionResult)
        ):
            raise ValueError("academic search requires AcademicSearchExecutionResult")
        if (
            self.action_taken is SearchToolName.RESOLVE_CITATION_METADATA
            and not isinstance(self.tool_execution, CitationResolutionExecutionResult)
        ):
            raise ValueError("citation resolution requires CitationResolutionExecutionResult")
        return self

    @property
    def tool_was_called(self) -> bool:
        """Compatibility view derived from the actual action."""
        return self.action_taken is not SearchToolName.NONE

    @property
    def tool_succeeded(self) -> bool | None:
        """Compatibility view derived from the tool-specific public status."""
        if self.tool_execution is None:
            return None
        public = self.tool_execution.to_public_result()
        return public.status.value != "failed"

    @property
    def execution_status(self) -> ToolExecutionStatus:
        """Compatibility view derived without duplicating operational state."""
        if self.tool_execution is None:
            return ToolExecutionStatus.NOT_CALLED
        return ToolExecutionStatus.SUCCESS if self.tool_succeeded else ToolExecutionStatus.FAILED

    @property
    def requested_limit_per_provider(self) -> int | None:
        """Expose academic requested limit without duplicating stored state."""
        if isinstance(self.tool_execution, AcademicSearchExecutionResult):
            return self.tool_execution.public_result.requested_limit_per_provider
        return None

    @property
    def effective_limit_per_provider(self) -> int | None:
        """Expose academic effective limit without duplicating stored state."""
        if isinstance(self.tool_execution, AcademicSearchExecutionResult):
            return self.tool_execution.public_result.effective_limit_per_provider
        return None


class CandidateEvaluationStatus(str, Enum):
    """Internal lifecycle of a transient candidate before user presentation."""

    PENDING = "pending"
    EVALUATED = "evaluated"
    FAILED = "failed"


class EvidenceSearchCandidate(BaseModel):
    """Transient candidate state retained during one in-memory evidence search session."""

    reference: ReferenceCandidate = Field(description="Normalized transient academic reference.")
    persisted_reference_id: int | None = Field(
        default=None,
        gt=0,
        description="Existing ProjectReference identifier after controlled persistence.",
    )
    provider: str = Field(min_length=1, description="Provider responsible for the candidate.")
    search_round: int = Field(ge=1, description="One-based round in which the candidate was found.")
    evaluation_status: CandidateEvaluationStatus = Field(
        default=CandidateEvaluationStatus.PENDING,
        description="Current internal evaluation lifecycle status.",
    )
    verdict: EvidenceVerdict | None = Field(default=None, description="Semantic verdict after evaluation.")
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Evaluator confidence signal when evaluation succeeded.",
    )
    reason: str | None = Field(default=None, description="Evaluator explanation or controlled failure reason.")
    analysis_scope: EvidenceAnalysisScope | None = Field(
        default=None,
        description="Semantic fields used by the evaluator when evaluation succeeded.",
    )
    shown_to_user: bool = Field(default=False, description="Whether this candidate was presented in the UI.")
