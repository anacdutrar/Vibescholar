"""Regression tests for the one-query-per-search-round contract."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agents.schemas import SearchPlan, SearchRoundSummary, SearchToolName
from app.agents.search_agent import SearchAgent
from app.llm.exceptions import ToolArgumentsValidationError
from app.llm.ollama_client import LLMChatResponse, LLMToolCall
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchInput,
    AcademicSearchStatus,
    AcademicSearchToolResult,
    ProviderExecutionSummary,
)


def run(coroutine):
    """Execute one asynchronous test scenario."""
    return asyncio.run(coroutine)


class RecordingClient:
    """Return configured chat responses without performing network calls."""

    def __init__(self, responses: list[LLMChatResponse]) -> None:
        self.responses = list(responses)
        self.chat_calls: list[dict] = []

    async def chat(self, messages, **kwargs):
        self.chat_calls.append({"messages": messages, **kwargs})
        return self.responses.pop(0)


class RecordingExecutor:
    """Expose the specific asynchronous executor boundary used by the tool."""

    def __init__(self) -> None:
        self.execute = AsyncMock(side_effect=empty_execution)


def academic_tool_response(query: str, *, call_id: str) -> LLMChatResponse:
    """Build one native academic-search tool call."""
    return LLMChatResponse(
        content=None,
        model="qwen-test",
        finish_reason="tool_calls",
        tool_calls=(
            LLMToolCall(
                tool_call_id=call_id,
                tool_name=SearchToolName.SEARCH_ACADEMIC_WORKS.value,
                arguments_json=json.dumps(
                    {"queries": [query], "limit_per_provider": 5}
                ),
            ),
        ),
    )


def empty_execution(request: AcademicSearchInput) -> AcademicSearchExecutionResult:
    """Build a valid empty execution matching the validated request."""
    return AcademicSearchExecutionResult(
        candidates=[],
        public_result=AcademicSearchToolResult(
            status=AcademicSearchStatus.EMPTY,
            providers=[
                ProviderExecutionSummary(
                    provider="test-provider",
                    success=True,
                    results_found=0,
                )
            ],
            raw_results=0,
            after_deduplication=0,
            message="No candidates found.",
            requested_limit_per_provider=request.limit_per_provider,
            effective_limit_per_provider=request.limit_per_provider,
        ),
    )


def test_tool_json_schema_requires_exactly_one_query():
    schema = AcademicSearchInput.model_json_schema()
    queries_schema = schema["properties"]["queries"]

    assert queries_schema["minItems"] == 1
    assert queries_schema["maxItems"] == 1

    tool = SearchAgent._tool_definitions()[0]
    exposed_queries = tool["function"]["parameters"]["properties"]["queries"]
    assert exposed_queries["minItems"] == 1
    assert exposed_queries["maxItems"] == 1


def test_academic_search_input_accepts_one_normalized_query():
    request = AcademicSearchInput(
        queries=["  scientific evidence  "],
        limit_per_provider=5,
    )

    assert request.queries == ["scientific evidence"]


@pytest.mark.parametrize("queries", [[], ["first", "second"], ["a", "b", "c"]])
def test_academic_search_input_rejects_query_counts_other_than_one(queries):
    with pytest.raises(ValidationError):
        AcademicSearchInput(queries=queries, limit_per_provider=5)


def test_search_plan_uses_the_same_single_query_contract():
    plan = SearchPlan(
        sentence_type="scientific_claim",
        should_search=True,
        selected_tool="search_academic_works",
        queries=["principal query"],
        confidence=0.9,
        reason="Academic evidence is required.",
    )
    assert plan.queries == ["principal query"]

    with pytest.raises(ValidationError):
        SearchPlan(
            sentence_type="scientific_claim",
            should_search=True,
            selected_tool="search_academic_works",
            queries=["first", "second"],
            confidence=0.9,
            reason="Academic evidence is required.",
        )


def test_initial_and_refined_decisions_each_use_one_inference_and_one_query():
    async def scenario():
        client = RecordingClient(
            [
                academic_tool_response("initial principal query", call_id="initial-call"),
                academic_tool_response("different refined query", call_id="refined-call"),
            ]
        )
        executor = RecordingExecutor()
        agent = SearchAgent(client)

        initial = await agent.run_search_decision(
            "A scientific sentence requiring evidence.",
            academic_search_executor=executor,
        )
        refined = await agent.run_refined_search_decision(
            sentence="A scientific sentence requiring evidence.",
            previous_round=SearchRoundSummary(
                round_number=1,
                queries_used=["initial principal query"],
                provider_results=[],
                raw_results=0,
                after_deduplication=0,
                after_filters=0,
                evaluated_candidates=0,
                strong_support_count=0,
                partial_support_count=0,
                missing_strong_evidence=5,
            ),
            academic_search_executor=executor,
        )

        assert initial.tool_call.validated_arguments.queries == [
            "initial principal query"
        ]
        assert refined.tool_call.validated_arguments.queries == [
            "different refined query"
        ]
        assert len(client.chat_calls) == 2
        assert executor.execute.await_count == 2

    run(scenario())


def test_multiple_queries_are_rejected_before_provider_execution():
    async def scenario():
        response = academic_tool_response("unused", call_id="invalid-call")
        invalid_call = LLMToolCall(
            tool_call_id=response.tool_calls[0].tool_call_id,
            tool_name=response.tool_calls[0].tool_name,
            arguments_json=json.dumps(
                {"queries": ["first", "second"], "limit_per_provider": 5}
            ),
        )
        client = RecordingClient(
            [
                LLMChatResponse(
                    content=None,
                    model="qwen-test",
                    finish_reason="tool_calls",
                    tool_calls=(invalid_call,),
                )
            ]
        )
        executor = RecordingExecutor()
        agent = SearchAgent(client)

        with pytest.raises(ToolArgumentsValidationError):
            await agent.run_search_decision(
                "A scientific sentence requiring evidence.",
                academic_search_executor=executor,
            )

        assert len(client.chat_calls) == 1
        executor.execute.assert_not_awaited()

    run(scenario())


def test_prompts_state_the_single_query_rule():
    prompts_root = Path(__file__).resolve().parents[2] / "prompts"

    for filename in ("search_agent_system.txt", "search_refinement_system.txt"):
        content = (prompts_root / filename).read_text(encoding="utf-8").casefold()
        assert "exatamente uma query" in content
        assert "múltiplas queries" in content or "multiplas queries" in content
        assert "rodadas futuras" in content
