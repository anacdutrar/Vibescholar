"""Boundary function for a future multi-provider academic search executor."""

from typing import Protocol

from app.core.config import settings
from app.llm.exceptions import ToolUnavailableError
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchInput,
    AcademicSearchToolResult,
)


class AcademicSearchExecutor(Protocol):
    """Minimal asynchronous dependency accepted by academic search."""

    async def execute(self, request: AcademicSearchInput) -> AcademicSearchExecutionResult:
        """Execute one validated request and return complete internal results."""
        ...


async def search_academic_works(
    request: AcademicSearchInput,
    executor: AcademicSearchExecutor | None,
) -> AcademicSearchExecutionResult:
    """Delegate one bounded search and preserve internal and public result boundaries."""
    validated = AcademicSearchInput.model_validate(request)
    if executor is None:
        raise ToolUnavailableError("The academic-search executor is unavailable.")
    effective_limit = min(validated.limit_per_provider, settings.RESULTS_PER_PROVIDER)
    effective_request = AcademicSearchInput(
        queries=validated.queries,
        limit_per_provider=effective_limit,
    )
    try:
        execution = AcademicSearchExecutionResult.model_validate(
            await executor.execute(effective_request)
        )
    except ToolUnavailableError:
        raise
    except Exception:
        return AcademicSearchExecutionResult(
            candidates=[],
            public_result=AcademicSearchToolResult(
                status="failed",
                providers=[],
                raw_results=0,
                after_deduplication=0,
                message="The academic-search executor failed.",
                requested_limit_per_provider=validated.limit_per_provider,
                effective_limit_per_provider=effective_limit,
            ),
        )
    public_payload = execution.public_result.model_dump()
    public_payload.update(
        requested_limit_per_provider=validated.limit_per_provider,
        effective_limit_per_provider=effective_limit,
    )
    public_result = AcademicSearchToolResult.model_validate(public_payload)
    return AcademicSearchExecutionResult(
        candidates=execution.candidates,
        public_result=public_result,
    )
