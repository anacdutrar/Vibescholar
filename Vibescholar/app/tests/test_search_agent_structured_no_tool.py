"""Structured SearchPlan fallback for native no-tool decisions."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.schemas import SearchPlan, SearchToolName
from app.agents.search_agent import SearchAgent
from app.app import fastapi_app
from app.llm.exceptions import LLMResponseValidationError
from app.llm.ollama_client import LLMChatResponse, LLMToolCall
from app.routers import grounding as grounding_router
from app.services.grounding_service import GroundingService
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchToolResult,
    ProviderExecutionSummary,
    ReferenceCandidate,
)


def run(coroutine):
    return asyncio.run(coroutine)


def no_action_plan() -> SearchPlan:
    return SearchPlan(
        sentence_type="non_scientific",
        should_search=False,
        selected_tool="none",
        queries=[],
        confidence=0.9,
        reason="No academic search is required.",
    )


def search_plan() -> SearchPlan:
    return SearchPlan(
        sentence_type="scientific_claim",
        should_search=True,
        selected_tool="search_academic_works",
        queries=["bounded academic query"],
        confidence=0.9,
        reason="Academic evidence is required.",
    )


class DecisionClient:
    model_name = "qwen-test"

    def __init__(self, chat_response, structured_result=None, structured_error=None):
        self.chat_response = chat_response
        self.structured_result = structured_result
        self.structured_error = structured_error
        self.chat_calls = []
        self.structured_calls = []

    async def chat(self, messages, tools=None, tool_choice=None):
        self.chat_calls.append((messages, tools, tool_choice))
        return self.chat_response

    async def structured_chat(self, messages, response_model):
        self.structured_calls.append((messages, response_model))
        if self.structured_error is not None:
            raise self.structured_error
        return self.structured_result


def stopped_with_free_text() -> LLMChatResponse:
    return LLMChatResponse(
        content="This free-form response must be ignored.",
        model="qwen-test",
        finish_reason="stop",
    )


def test_no_tool_uses_structured_search_plan_and_ignores_free_text(caplog):
    client = DecisionClient(stopped_with_free_text(), no_action_plan())

    with caplog.at_level("INFO", logger="vibescholar"):
        outcome = run(SearchAgent(client).run_search_decision("Editorial heading."))

    assert outcome.action_taken is SearchToolName.NONE
    assert len(client.chat_calls) == 1
    assert len(client.structured_calls) == 1
    assert client.structured_calls[0][1] is SearchPlan
    assert "operation=structured_plan" in caplog.text
    assert "structured_output=true" in caplog.text


def test_structured_plan_requesting_search_cannot_replace_real_tool_call():
    client = DecisionClient(stopped_with_free_text(), search_plan())
    executor = AsyncMock()

    with pytest.raises(LLMResponseValidationError):
        run(
            SearchAgent(client).run_search_decision(
                "Scientific claim.", academic_search_executor=executor
            )
        )

    executor.assert_not_awaited()


@pytest.mark.parametrize("structured_result", [None, {"selected_tool": "none"}])
def test_invalid_structured_search_plan_is_rejected(structured_result):
    client = DecisionClient(stopped_with_free_text(), structured_result)

    with pytest.raises(LLMResponseValidationError):
        run(SearchAgent(client).run_search_decision("Editorial heading."))


def test_backend_validation_error_is_mapped_to_llm_response_validation_error():
    with pytest.raises(ValidationError) as captured:
        SearchPlan.model_validate({"should_search": False})
    client = DecisionClient(stopped_with_free_text(), structured_error=captured.value)

    with pytest.raises(LLMResponseValidationError):
        run(SearchAgent(client).run_search_decision("Editorial heading."))


def test_native_tool_call_still_executes_without_structured_plan():
    response = LLMChatResponse(
        content=None,
        model="qwen-test",
        finish_reason="tool_calls",
        tool_calls=(
            LLMToolCall(
                tool_call_id="call-1",
                tool_name="search_academic_works",
                arguments_json=json.dumps({"queries": ["one query"]}),
            ),
        ),
    )
    client = DecisionClient(response)
    execution = AcademicSearchExecutionResult(
        candidates=[
            ReferenceCandidate(provider="test", external_id="work-1", title="Test work")
        ],
        public_result=AcademicSearchToolResult(
            status="success",
            providers=[
                ProviderExecutionSummary(provider="test", success=True, results_found=1)
            ],
            raw_results=1,
            after_deduplication=1,
            message="Search completed.",
            requested_limit_per_provider=1,
            effective_limit_per_provider=1,
        ),
    )
    executor = SimpleNamespace(execute=AsyncMock(return_value=execution))

    outcome = run(
        SearchAgent(client).run_search_decision(
            "Scientific claim.", academic_search_executor=executor
        )
    )

    assert outcome.action_taken is SearchToolName.SEARCH_ACADEMIC_WORKS
    assert outcome.tool_call_id == "call-1"
    assert len(client.chat_calls) == 1
    assert client.structured_calls == []
    executor.execute.assert_awaited_once()


def test_router_returns_success_for_correct_structured_no_tool_decision():
    client = DecisionClient(stopped_with_free_text(), no_action_plan())
    agent = SearchAgent(client)

    class AgentBackedGroundingService:
        async def search_sentence_evidence(self, sentence_id, user_id):
            outcome = await agent.run_search_decision("Editorial heading.")
            assert outcome.action_taken is SearchToolName.NONE
            return []

    fastapi_app.dependency_overrides[grounding_router.get_current_user] = lambda: SimpleNamespace(
        id=17
    )
    fastapi_app.dependency_overrides[GroundingService] = AgentBackedGroundingService
    test_client = TestClient(fastapi_app, raise_server_exceptions=True)
    try:
        response = test_client.post(
            "/api/sentences/search/evidence", json={"sentence_id": 23}
        )
    finally:
        test_client.close()
        fastapi_app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []

