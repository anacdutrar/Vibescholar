"""Concrete concurrent execution of one academic-search query."""

import asyncio

from app.core.config import settings
from app.llm.exceptions import (
    AcademicProviderError,
    ToolArgumentsValidationError,
    ToolUnavailableError,
)
from app.providers.openalex_provider import OpenAlexProvider
from app.providers.semantic_scholar_provider import SemanticScholarProvider
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchInput,
    AcademicSearchStatus,
    AcademicSearchToolResult,
    ProviderExecutionSummary,
    ReferenceCandidate,
    deduplicate_reference_candidates,
)


class AcademicSearchExecutor:
    """Query enabled academic providers once and aggregate transient candidates."""

    def __init__(
        self,
        openalex_provider: OpenAlexProvider | None = None,
        semantic_scholar_provider: SemanticScholarProvider | None = None,
        *,
        provider_order: tuple[str, ...] | None = None,
    ) -> None:
        self._openalex = openalex_provider or OpenAlexProvider()
        self._semantic_scholar = semantic_scholar_provider or SemanticScholarProvider()
        self._provider_order = provider_order or settings.SEARCH_PROVIDER_ORDER

    async def execute(self, request: AcademicSearchInput) -> AcademicSearchExecutionResult:
        """Execute exactly one query once per enabled provider, concurrently."""
        validated = AcademicSearchInput.model_validate(request)
        if len(validated.queries) != 1:
            raise ToolArgumentsValidationError(
                "This search round requires exactly one academic query."
            )
        effective_limit = min(validated.limit_per_provider, settings.RESULTS_PER_PROVIDER)
        providers = self._ordered_providers()
        if not providers:
            raise ToolUnavailableError("No academic search provider is enabled.")

        query = validated.queries[0]
        outcomes = await asyncio.gather(
            *(provider.search_works(query, effective_limit) for _, provider in providers),
            return_exceptions=True,
        )

        summaries: list[ProviderExecutionSummary] = []
        raw_candidates: list[ReferenceCandidate] = []
        for (provider_name, _), outcome in zip(providers, outcomes, strict=True):
            if isinstance(outcome, AcademicProviderError):
                summaries.append(
                    ProviderExecutionSummary(
                        provider=provider_name,
                        success=False,
                        results_found=0,
                        error_code=outcome.code.value,
                    )
                )
                continue
            if isinstance(outcome, BaseException):
                raise outcome
            candidates = [ReferenceCandidate.model_validate(item) for item in outcome][
                :effective_limit
            ]
            raw_candidates.extend(candidates)
            summaries.append(
                ProviderExecutionSummary(
                    provider=provider_name,
                    success=True,
                    results_found=len(candidates),
                )
            )

        candidates = deduplicate_reference_candidates(raw_candidates)
        status = self._status(summaries, bool(candidates))
        return AcademicSearchExecutionResult(
            candidates=candidates,
            public_result=AcademicSearchToolResult(
                status=status,
                providers=summaries,
                raw_results=len(raw_candidates),
                after_deduplication=len(candidates),
                message=self._message(status),
                requested_limit_per_provider=validated.limit_per_provider,
                effective_limit_per_provider=effective_limit,
            ),
        )

    def _ordered_providers(self) -> list[tuple[str, object]]:
        """Resolve only the two explicit providers in configured order."""
        providers: list[tuple[str, object]] = []
        for provider_name in self._provider_order:
            if provider_name == "openalex":
                providers.append((provider_name, self._openalex))
            elif provider_name in {"semantic_scholar", "semanticscholar"}:
                providers.append(("semantic_scholar", self._semantic_scholar))
            else:
                raise ValueError(f"Unsupported academic provider: {provider_name}")
        return providers

    @staticmethod
    def _status(
        summaries: list[ProviderExecutionSummary],
        has_candidates: bool,
    ) -> AcademicSearchStatus:
        failed = any(not summary.success for summary in summaries)
        if has_candidates and failed:
            return AcademicSearchStatus.PARTIAL_SUCCESS
        if has_candidates:
            return AcademicSearchStatus.SUCCESS
        if failed:
            return AcademicSearchStatus.FAILED
        return AcademicSearchStatus.EMPTY

    @staticmethod
    def _message(status: AcademicSearchStatus) -> str:
        messages = {
            AcademicSearchStatus.SUCCESS: "Academic search completed.",
            AcademicSearchStatus.PARTIAL_SUCCESS: (
                "Academic search completed with an unavailable provider."
            ),
            AcademicSearchStatus.EMPTY: "Academic search completed without candidates.",
            AcademicSearchStatus.FAILED: "Academic providers did not return usable results.",
        }
        return messages[status]
