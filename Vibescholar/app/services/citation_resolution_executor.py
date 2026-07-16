"""Concrete concurrent resolution of one set of citation hints."""

import asyncio
import time

from app.agents.schemas import CitationHint
from app.core.config import settings
from app.core.logging import logger
from app.llm.exceptions import (
    AcademicProviderError,
    ToolArgumentsValidationError,
    ToolUnavailableError,
)
from app.providers.openalex_provider import OpenAlexProvider
from app.providers.semantic_scholar_provider import SemanticScholarProvider
from app.tools.schemas import (
    CitationResolutionExecutionResult,
    CitationResolutionInput,
    CitationResolutionStatus,
    CitationResolutionToolResult,
    ReferenceCandidate,
    deduplicate_reference_candidates,
    is_valid_doi,
    normalize_doi,
    normalize_text,
    normalize_title,
)


class CitationResolutionExecutor:
    """Resolve one deterministic citation criterion across enabled providers."""

    def __init__(
        self,
        openalex_provider: OpenAlexProvider | None = None,
        semantic_scholar_provider: SemanticScholarProvider | None = None,
        *,
        provider_order: tuple[str, ...] | None = None,
        lookup_limit: int = 5,
    ) -> None:
        if lookup_limit <= 0:
            raise ValueError("lookup_limit must be positive")
        self._openalex = openalex_provider or OpenAlexProvider()
        self._semantic_scholar = semantic_scholar_provider or SemanticScholarProvider()
        self._provider_order = provider_order or settings.SEARCH_PROVIDER_ORDER
        self._lookup_limit = min(lookup_limit, settings.RESULTS_PER_PROVIDER)

    async def execute(
        self,
        request: CitationResolutionInput,
    ) -> CitationResolutionExecutionResult:
        """Execute one prioritized lookup per enabled provider, concurrently."""
        validated = CitationResolutionInput.model_validate(request)
        lookup_arguments, criterion = self._lookup_arguments(validated.citation_hints)
        providers = self._ordered_providers()
        if not providers:
            raise ToolUnavailableError("No citation resolution provider is enabled.")

        started_at = time.perf_counter()
        logger.info(
            "ai.pipeline.executor.started executor=citation_resolution providers=%s "
            "criterion=%s limit=%s",
            len(providers),
            criterion,
            self._lookup_limit,
        )
        outcomes = await asyncio.gather(
            *(
                provider.lookup(limit=self._lookup_limit, **lookup_arguments)
                for _, provider in providers
            ),
            return_exceptions=True,
        )

        failures = 0
        successful_providers = 0
        raw_matches: list[ReferenceCandidate] = []
        for (_, _), outcome in zip(providers, outcomes, strict=True):
            if isinstance(outcome, AcademicProviderError):
                failures += 1
                continue
            if isinstance(outcome, BaseException):
                raise outcome
            successful_providers += 1
            candidates = [ReferenceCandidate.model_validate(item) for item in outcome][
                :self._lookup_limit
            ]
            raw_matches.extend(
                candidate
                for candidate in candidates
                if self._matches_criterion(candidate, criterion, lookup_arguments)
            )

        matches = deduplicate_reference_candidates(raw_matches)
        status = self._status(
            match_count=len(matches),
            failures=failures,
            successful_providers=successful_providers,
        )
        result = CitationResolutionExecutionResult(
            matches=matches,
            public_result=CitationResolutionToolResult(
                status=status,
                matches_found=len(matches),
                message=self._message(status),
            ),
        )
        logger.info(
            "ai.pipeline.executor.completed executor=citation_resolution status=%s "
            "providers=%s provider_failures=%s raw_matches=%s matches=%s duration=%.4f",
            status.value,
            len(providers),
            failures,
            len(raw_matches),
            len(matches),
            time.perf_counter() - started_at,
        )
        return result

    @staticmethod
    def _lookup_arguments(
        hints: list[CitationHint],
    ) -> tuple[dict, str]:
        """Choose DOI, title, or author/year once using deterministic priority."""
        for hint in hints:
            if is_valid_doi(hint.doi):
                return {"doi": normalize_doi(hint.doi)}, "doi"
        for hint in hints:
            if hint.title:
                arguments = {"title": hint.title}
                if hint.year is not None:
                    arguments["year"] = hint.year
                return arguments, "title"
        for hint in hints:
            if hint.author and hint.year is not None:
                return {"authors": [hint.author], "year": hint.year}, "author_year"
        raise ToolArgumentsValidationError(
            "Citation resolution requires a DOI, title, or author with year."
        )

    @staticmethod
    def _matches_criterion(
        candidate: ReferenceCandidate,
        criterion: str,
        arguments: dict,
    ) -> bool:
        """Keep only exact deterministic or author/year-plausible lookup results."""
        if criterion == "doi":
            return normalize_doi(candidate.doi) == normalize_doi(arguments["doi"])
        if criterion == "title":
            if normalize_title(candidate.title) != normalize_title(arguments["title"]):
                return False
            requested_year = arguments.get("year")
            return requested_year is None or candidate.year == requested_year
        requested_author = normalize_text(arguments["authors"][0])
        requested_tokens = set(requested_author.split())
        return candidate.year == arguments["year"] and any(
            requested_tokens.issubset(set(normalize_text(author).split()))
            for author in candidate.authors
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
        *,
        match_count: int,
        failures: int,
        successful_providers: int,
    ) -> CitationResolutionStatus:
        if failures and match_count:
            return CitationResolutionStatus.PARTIAL_FAILURE
        if failures and not match_count:
            return CitationResolutionStatus.FAILED
        if not successful_providers:
            return CitationResolutionStatus.FAILED
        if match_count == 0:
            return CitationResolutionStatus.NOT_FOUND
        if match_count == 1:
            return CitationResolutionStatus.RESOLVED
        return CitationResolutionStatus.AMBIGUOUS

    @staticmethod
    def _message(status: CitationResolutionStatus) -> str:
        messages = {
            CitationResolutionStatus.RESOLVED: "Citation metadata resolved.",
            CitationResolutionStatus.AMBIGUOUS: "Multiple citation matches remain.",
            CitationResolutionStatus.NOT_FOUND: "No citation metadata match was found.",
            CitationResolutionStatus.PARTIAL_FAILURE: (
                "Citation metadata was found with an unavailable provider."
            ),
            CitationResolutionStatus.FAILED: "Citation providers did not return a usable result.",
        }
        return messages[status]
