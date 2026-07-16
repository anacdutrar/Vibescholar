"""Boundary function for a future citation-metadata resolution executor."""

import time
from typing import Protocol

from app.core.logging import logger
from app.llm.exceptions import ToolUnavailableError
from app.tools.schemas import (
    CitationResolutionExecutionResult,
    CitationResolutionInput,
    CitationResolutionToolResult,
)


class CitationResolutionExecutor(Protocol):
    """Minimal asynchronous dependency accepted by citation resolution."""

    async def execute(self, request: CitationResolutionInput) -> CitationResolutionExecutionResult:
        """Execute one validated request and return complete internal matches."""
        ...


async def resolve_citation_metadata(
    request: CitationResolutionInput,
    executor: CitationResolutionExecutor | None,
) -> CitationResolutionExecutionResult:
    """Delegate one resolution while preserving internal and public boundaries."""
    validated = CitationResolutionInput.model_validate(request)
    if executor is None:
        logger.warning(
            "ai.pipeline.tool.failed tool=resolve_citation_metadata status=unavailable"
        )
        raise ToolUnavailableError("The citation-resolution executor is unavailable.")
    started_at = time.perf_counter()
    logger.info(
        "ai.pipeline.tool.started tool=resolve_citation_metadata hint_count=%s",
        len(validated.citation_hints),
    )
    try:
        result = CitationResolutionExecutionResult.model_validate(
            await executor.execute(validated)
        )
    except ToolUnavailableError:
        raise
    except Exception as exc:
        logger.warning(
            "ai.pipeline.tool.failed tool=resolve_citation_metadata status=failed "
            "error_type=%s duration=%.4f",
            type(exc).__name__,
            time.perf_counter() - started_at,
        )
        return CitationResolutionExecutionResult(
            matches=[],
            public_result=CitationResolutionToolResult(
                status="failed",
                matches_found=0,
                message="The citation-resolution executor failed.",
            ),
        )
    logger.info(
        "ai.pipeline.tool.completed tool=resolve_citation_metadata status=%s "
        "matches=%s duration=%.4f",
        result.public_result.status.value,
        result.public_result.matches_found,
        time.perf_counter() - started_at,
    )
    return result
