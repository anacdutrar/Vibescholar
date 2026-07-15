"""Boundary function for a future citation-metadata resolution executor."""

from typing import Protocol

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
        raise ToolUnavailableError("The citation-resolution executor is unavailable.")
    try:
        return CitationResolutionExecutionResult.model_validate(
            await executor.execute(validated)
        )
    except ToolUnavailableError:
        raise
    except Exception:
        return CitationResolutionExecutionResult(
            matches=[],
            public_result=CitationResolutionToolResult(
                status="failed",
                matches_found=0,
                message="The citation-resolution executor failed.",
            ),
        )
