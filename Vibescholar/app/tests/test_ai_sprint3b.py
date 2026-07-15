"""Sprint 3B tests for typed internal and safe public tool results."""

import asyncio
import inspect
import json
import logging
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agents.schemas import SearchPlan
from app.agents.search_agent import SearchAgent
from app.core.config import settings
from app.llm.exceptions import ToolUnavailableError
from app.llm.ollama_client import LLMChatResponse, LLMToolCall
from app.tools.academic_search import search_academic_works
from app.tools.citation_resolution import resolve_citation_metadata
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchInput,
    AcademicSearchStatus,
    AcademicSearchToolResult,
    CitationResolutionExecutionResult,
    CitationResolutionInput,
    CitationResolutionStatus,
    CitationResolutionToolResult,
    ProviderExecutionSummary,
    ReferenceCandidate,
    SearchToolExecutionOutcome,
)


def run(coroutine):
    """Execute one isolated asynchronous scenario."""
    return asyncio.run(coroutine)


def sensitive_candidate(identifier: str = "internal-1") -> ReferenceCandidate:
    """Build rich test-only metadata that must never enter a public result."""
    return ReferenceCandidate(
        provider="test-provider",
        external_id=identifier,
        title="Internal Academic Title",
        authors=["Internal Author"],
        journal="Internal Journal",
        year=2024,
        doi="10.9999/internal-doi",
        abstract="Internal abstract with confidential provider metadata.",
        availability="open",
        language="en",
        source_url="https://provider.invalid/internal-1",
        provider_relevance_score=0.87,
    )


def provider(provider: str = "provider-a", *, success: bool = True, results: int = 1):
    """Build one safe provider execution summary."""
    return ProviderExecutionSummary(
        provider=provider,
        success=success,
        results_found=results,
        error_code=None if success else "TEMPORARY_FAILURE",
    )


def academic_public(
    *,
    status: str = "success",
    providers: list[ProviderExecutionSummary] | None = None,
    raw: int = 1,
    deduplicated: int = 1,
    requested: int = 5,
    effective: int = 5,
) -> AcademicSearchToolResult:
    """Build a configurable public academic result."""
    return AcademicSearchToolResult(
        status=status,
        providers=providers if providers is not None else [provider(results=raw)],
        raw_results=raw,
        after_deduplication=deduplicated,
        message="Academic search completed.",
        requested_limit_per_provider=requested,
        effective_limit_per_provider=effective,
    )


def academic_execution() -> AcademicSearchExecutionResult:
    """Build one successful internal academic result."""
    return AcademicSearchExecutionResult(
        candidates=[sensitive_candidate()],
        public_result=academic_public(),
    )


def citation_execution(status: str = "resolved", count: int = 1) -> CitationResolutionExecutionResult:
    """Build one internally consistent citation-resolution result."""
    return CitationResolutionExecutionResult(
        matches=[sensitive_candidate(f"match-{index}") for index in range(count)],
        public_result=CitationResolutionToolResult(
            status=status,
            matches_found=count,
            message="Citation resolution completed.",
        ),
    )


class AcademicExecutorStub:
    """Minimal specific academic executor used only by tests."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.execute = AsyncMock(return_value=result, side_effect=error)


class CitationExecutorStub:
    """Minimal specific citation executor used only by tests."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.execute = AsyncMock(return_value=result, side_effect=error)


class DecisionClient:
    """Return one transport-level decision and record inference inputs."""

    def __init__(self, response: LLMChatResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        return self.response


def tool_response(name: str, arguments: dict, call_id: str = "call-3b") -> LLMChatResponse:
    """Build one typed transport response containing a real tool call."""
    return LLMChatResponse(
        content=None,
        model="qwen3.5:9b",
        finish_reason="tool_calls",
        tool_calls=(
            LLMToolCall(
                tool_call_id=call_id,
                tool_name=name,
                arguments_json=json.dumps(arguments),
            ),
        ),
    )


def test_operational_enums_have_exact_values():
    assert {item.value for item in AcademicSearchStatus} == {
        "success", "partial_success", "empty", "failed"
    }
    assert {item.value for item in CitationResolutionStatus} == {
        "resolved", "ambiguous", "not_found", "partial_failure", "failed"
    }


def test_valid_academic_operational_states():
    success = academic_public()
    partial = academic_public(
        status="partial_success",
        providers=[provider("provider-a", results=1), provider("provider-b", success=False, results=0)],
    )
    empty = academic_public(status="empty", providers=[provider(results=0)], raw=0, deduplicated=0)
    failed = academic_public(
        status="failed",
        providers=[provider(success=False, results=0)],
        raw=0,
        deduplicated=0,
    )
    assert success.status is AcademicSearchStatus.SUCCESS
    assert partial.status is AcademicSearchStatus.PARTIAL_SUCCESS
    assert empty.status is AcademicSearchStatus.EMPTY
    assert failed.status is AcademicSearchStatus.FAILED


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "success", "providers": [provider(results=0)], "raw": 0, "deduplicated": 0},
        {"status": "empty", "providers": [provider(results=1)], "raw": 1, "deduplicated": 1},
        {"status": "partial_success", "providers": [provider(results=1)]},
        {
            "status": "partial_success",
            "providers": [provider("provider-a", results=0), provider("provider-b", success=False, results=1)],
            "raw": 1,
            "deduplicated": 1,
        },
        {"status": "failed", "providers": [provider(results=1)], "raw": 1, "deduplicated": 1},
    ],
)
def test_inconsistent_academic_statuses_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        academic_public(**kwargs)


def test_academic_counts_limits_and_error_codes_are_validated():
    with pytest.raises(ValidationError):
        academic_public(raw=1, deduplicated=2)
    with pytest.raises(ValidationError):
        academic_public(requested=2, effective=3)
    with pytest.raises(ValidationError):
        academic_public(
            requested=settings.RESULTS_PER_PROVIDER + 1,
            effective=settings.RESULTS_PER_PROVIDER + 1,
        )
    with pytest.raises(ValidationError):
        ProviderExecutionSummary(
            provider="provider-a",
            success=False,
            results_found=0,
            error_code="Traceback: secret value",
        )


@pytest.mark.parametrize(
    ("status", "count", "valid"),
    [
        ("resolved", 1, True),
        ("resolved", 0, False),
        ("ambiguous", 2, True),
        ("ambiguous", 1, False),
        ("not_found", 0, True),
        ("not_found", 1, False),
        ("failed", 0, True),
        ("failed", 1, False),
        ("partial_failure", 0, True),
        ("partial_failure", 2, True),
    ],
)
def test_citation_status_matches_count_semantics(status, count, valid):
    if valid:
        result = CitationResolutionToolResult(status=status, matches_found=count, message="Safe message.")
        assert result.matches_found == count
    else:
        with pytest.raises(ValidationError):
            CitationResolutionToolResult(status=status, matches_found=count, message="Safe message.")


def test_internal_results_require_public_count_alignment():
    with pytest.raises(ValidationError):
        AcademicSearchExecutionResult(candidates=[], public_result=academic_public())
    with pytest.raises(ValidationError):
        CitationResolutionExecutionResult(
            matches=[],
            public_result=CitationResolutionToolResult(
                status="resolved", matches_found=1, message="Resolved."
            ),
        )


def test_academic_public_conversion_never_contains_candidate_metadata():
    internal = academic_execution()
    public = internal.to_public_result()
    serialized = public.model_dump_json().casefold()
    assert public is internal.public_result
    for forbidden in (
        "internal academic title",
        "internal abstract",
        "10.9999/internal-doi",
        "internal-1",
        "candidate_key",
        "provider_relevance_score",
        "source_url",
        "issn",
        "qualis",
    ):
        assert forbidden not in serialized


def test_citation_public_conversion_never_contains_match_metadata():
    internal = citation_execution()
    public = internal.to_public_result()
    serialized = public.model_dump_json().casefold()
    assert public is internal.public_result
    assert "matches" not in public.model_dump()
    assert "doi" not in serialized
    assert "candidate_key" not in serialized
    assert "abstract" not in serialized
    assert "source_url" not in serialized


def test_academic_executor_is_injected_and_receives_effective_limit():
    async def scenario():
        requested = settings.RESULTS_PER_PROVIDER + 50
        executor = AcademicExecutorStub(academic_execution())
        result = await search_academic_works(
            AcademicSearchInput(queries=["academic evidence"], limit_per_provider=requested),
            executor,
        )
        request = executor.execute.await_args.args[0]
        assert isinstance(result, AcademicSearchExecutionResult)
        assert request.limit_per_provider == settings.RESULTS_PER_PROVIDER
        assert result.public_result.requested_limit_per_provider == requested
        assert result.public_result.effective_limit_per_provider == settings.RESULTS_PER_PROVIDER
        executor.execute.assert_awaited_once()

    run(scenario())


def test_citation_executor_is_injected_and_internal_matches_are_preserved():
    async def scenario():
        executor = CitationExecutorStub(citation_execution())
        result = await resolve_citation_metadata(
            CitationResolutionInput(citation_hints=[{"raw": "(Author, 2024)"}]),
            executor,
        )
        assert isinstance(result, CitationResolutionExecutionResult)
        assert result.matches[0].doi == "10.9999/internal-doi"
        executor.execute.assert_awaited_once()

    run(scenario())


def test_missing_executors_remain_controlled_errors():
    async def scenario():
        with pytest.raises(ToolUnavailableError):
            await search_academic_works(
                AcademicSearchInput(queries=["query"], limit_per_provider=1), None
            )
        with pytest.raises(ToolUnavailableError):
            await resolve_citation_metadata(
                CitationResolutionInput(citation_hints=[{"raw": "[1]"}]), None
            )

    run(scenario())


def test_executor_failure_becomes_safe_typed_internal_result(caplog):
    async def scenario():
        secret = "private-api-key"
        executor = AcademicExecutorStub(error=ValueError(secret))
        with caplog.at_level(logging.ERROR):
            result = await search_academic_works(
                AcademicSearchInput(queries=["query"], limit_per_provider=1), executor
            )
        assert result.public_result.status is AcademicSearchStatus.FAILED
        assert result.candidates == []
        assert secret not in result.public_result.message
        assert secret not in caplog.text

    run(scenario())


def test_search_agent_builds_academic_outcome_from_internal_result():
    async def scenario():
        client = DecisionClient(
            tool_response(
                "search_academic_works",
                {"queries": ["academic evidence"], "limit_per_provider": 3},
                "academic-call",
            )
        )
        executor = AcademicExecutorStub(academic_execution())
        outcome = await SearchAgent(client).run_search_decision(
            "A scientific claim.", academic_search_executor=executor
        )
        assert isinstance(outcome, SearchToolExecutionOutcome)
        assert outcome.action_taken.value == "search_academic_works"
        assert outcome.tool_call_id == "academic-call"
        assert isinstance(outcome.tool_execution, AcademicSearchExecutionResult)
        assert outcome.tool_execution.candidates[0].doi == "10.9999/internal-doi"
        assert outcome.reason == outcome.tool_execution.to_public_result().message
        assert len(client.calls) == 1
        assert all(message["role"] != "tool" for message in client.calls[0]["messages"])
        sent_messages = json.dumps(client.calls[0]["messages"]).casefold()
        assert "internal academic title" not in sent_messages
        assert "10.9999/internal-doi" not in sent_messages

    run(scenario())


def test_search_agent_builds_citation_outcome_from_internal_result():
    async def scenario():
        client = DecisionClient(
            tool_response(
                "resolve_citation_metadata",
                {"citation_hints": [{"raw": "(Author, 2024)", "author": "Author", "year": 2024}]},
                "citation-call",
            )
        )
        outcome = await SearchAgent(client).run_search_decision(
            "A claim (Author, 2024).",
            citation_resolution_executor=CitationExecutorStub(citation_execution()),
        )
        assert outcome.action_taken.value == "resolve_citation_metadata"
        assert outcome.tool_call_id == "citation-call"
        assert isinstance(outcome.tool_execution, CitationResolutionExecutionResult)
        assert len(client.calls) == 1

    run(scenario())


def test_none_outcome_contains_no_internal_execution():
    async def scenario():
        plan = SearchPlan(
            sentence_type="non_scientific",
            should_search=False,
            selected_tool="none",
            queries=[],
            confidence=0.9,
            reason="No academic action is required.",
        )
        client = DecisionClient(
            LLMChatResponse(content=plan.model_dump_json(), model="qwen3.5:9b", finish_reason="stop")
        )
        outcome = await SearchAgent(client).run_search_decision("Editorial heading.")
        assert outcome.action_taken.value == "none"
        assert outcome.tool_call_id is None
        assert outcome.tool_execution is None
        assert outcome.tool_was_called is False
        assert len(client.calls) == 1

    run(scenario())


def test_outcome_rejects_wrong_or_missing_execution_type():
    with pytest.raises(ValidationError):
        SearchToolExecutionOutcome(
            sentence_type="scientific_claim",
            action_taken="search_academic_works",
            tool_call_id="call",
            tool_execution=citation_execution(),
            tool_call={
                "tool_call_id": "call",
                "tool_name": "search_academic_works",
                "validated_arguments": {"queries": ["query"], "limit_per_provider": 1},
            },
            reason="Invalid mismatch.",
        )


def test_tools_have_no_http_database_or_hardcoded_candidates():
    import app.tools.academic_search as academic_module
    import app.tools.citation_resolution as citation_module

    for module in (academic_module, citation_module):
        source = inspect.getsource(module).casefold()
        assert "httpx" not in source
        assert "requests" not in source
        assert "sqlalchemy" not in source
        assert "referencecandidate(" not in source
        assert "openalex" not in source
        assert "semantic scholar" not in source
