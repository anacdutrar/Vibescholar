"""Boundary function for a future multi-provider academic search executor."""

import time
from typing import Protocol

from app.core.config import settings
from app.core.logging import logger
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
        logger.warning(
            "ai.pipeline.tool.failed tool=search_academic_works status=unavailable"
        )
        raise ToolUnavailableError("The academic-search executor is unavailable.")
    configured_limit = settings.RESULTS_PER_PROVIDER
    started_at = time.perf_counter()
    logger.info(
        "ai.pipeline.tool.started tool=search_academic_works query_count=%s "
        "configured_limit=%s effective_limit=%s",
        len(validated.queries),
        configured_limit,
        configured_limit,
    )
    try:
        execution = AcademicSearchExecutionResult.model_validate(
            await executor.execute(validated)
        )
    except ToolUnavailableError:
        raise
    except Exception as exc:
        logger.warning(
            "ai.pipeline.tool.failed tool=search_academic_works status=failed "
            "error_type=%s duration=%.4f",
            type(exc).__name__,
            time.perf_counter() - started_at,
        )
        return AcademicSearchExecutionResult(
            candidates=[],
            public_result=AcademicSearchToolResult(
                status="failed",
                providers=[],
                raw_results=0,
                after_deduplication=0,
                message="The academic-search executor failed.",
                requested_limit_per_provider=configured_limit,
                effective_limit_per_provider=configured_limit,
            ),
        )
    public_payload = execution.public_result.model_dump()
    public_payload.update(
        requested_limit_per_provider=configured_limit,
        effective_limit_per_provider=configured_limit,
    )
    public_result = AcademicSearchToolResult.model_validate(public_payload)
    result = AcademicSearchExecutionResult(
        candidates=execution.candidates,
        public_result=public_result,
    )
    logger.info(
        "ai.pipeline.tool.completed tool=search_academic_works status=%s raw=%s "
        "deduplicated=%s duration=%.4f",
        public_result.status.value,
        public_result.raw_results,
        public_result.after_deduplication,
        time.perf_counter() - started_at,
    )
    return result
