"""Controlled handling of unauthorized SearchAgent function calls."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.agents.schemas import SearchToolName
from app.agents.search_agent import SearchAgent
from app.app import fastapi_app
from app.core.config import settings
from app.llm.exceptions import UnknownToolError
from app.llm.ollama_client import LLMChatResponse, LLMToolCall
from app.routers import grounding as grounding_router
from app.services.evidence_search_state import (
    EvidenceSearchSessionStore,
    SearchSessionStatus,
)
from app.services.evidence_search_workflow import (
    EvidenceSearchRoundResult,
    EvidenceSearchWorkflow,
    RoundResultSource,
    summarize_evaluations,
)
from app.services.evidence_service import EvidenceService
from app.services.grounding_service import GroundingService
from app.services.reference_filter_service import (
    ReferenceFilterCriteria,
    ReferenceFilterService,
)
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchStatus,
    AcademicSearchToolResult,
    ProviderExecutionSummary,
)


def run(coroutine):
    """Execute one isolated asynchronous scenario."""
    return asyncio.run(coroutine)


class ChatClientStub:
    """Return one transport-neutral chat response without network access."""

    def __init__(self, response: LLMChatResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.response


class ExecutorStub:
    """Record tool execution and return one valid empty academic result."""

    def __init__(self) -> None:
        self.execute = AsyncMock(
            return_value=AcademicSearchExecutionResult(
                candidates=[],
                public_result=AcademicSearchToolResult(
                    status=AcademicSearchStatus.EMPTY,
                    providers=[
                        ProviderExecutionSummary(
                            provider="openalex",
                            success=True,
                            results_found=0,
                        )
                    ],
                    raw_results=0,
                    after_deduplication=0,
                    message="No candidates found.",
                    requested_limit_per_provider=settings.RESULTS_PER_PROVIDER,
                    effective_limit_per_provider=settings.RESULTS_PER_PROVIDER,
                ),
            )
        )


class RaisingSearchAgent:
    """Raise the controlled error before any injected executor can run."""

    def __init__(self) -> None:
        self.initial_calls = 0
        self.refinement_calls = 0

    async def run_search_decision(self, *args, **kwargs):
        self.initial_calls += 1
        raise UnknownToolError("The model requested an unauthorized tool.")

    async def run_refined_search_decision(self, **kwargs):
        self.refinement_calls += 1
        raise AssertionError("unknown initial tools must terminate the workflow")


class EvaluatorSpy:
    """Fail if an unauthorized tool reaches semantic evaluation."""

    def __init__(self) -> None:
        self.calls = 0

    async def evaluate_batch(self, sentence, candidates):
        self.calls += 1
        raise AssertionError("unknown tools must not reach the evaluator")


class WorkflowResultStub:
    """Return one configured workflow result and record facade calls."""

    def __init__(self, result: EvidenceSearchRoundResult) -> None:
        self.result = result
        self.calls = 0

    async def execute_round(self, **kwargs):
        self.calls += 1
        return self.result


class SequencedGroundingService:
    """Fail once with an unauthorized tool, then prove the router remains usable."""

    def __init__(self) -> None:
        self.calls = 0

    async def search_sentence_evidence(self, sentence_id, user_id):
        self.calls += 1
        if self.calls == 1:
            raise UnknownToolError("internal unauthorized tool details")
        return []


def tool_response(name: str) -> LLMChatResponse:
    """Build one exact OpenAI-compatible function decision."""
    return LLMChatResponse(
        content=None,
        model="qwen-test",
        finish_reason="tool_calls",
        tool_calls=(
            LLMToolCall(
                tool_call_id="call-1",
                tool_name=name,
                arguments_json=json.dumps({"queries": ["single query"]}),
            ),
        ),
    )


def test_official_tool_name_is_accepted_and_executed_once():
    client = ChatClientStub(tool_response("search_academic_works"))
    executor = ExecutorStub()
    agent = SearchAgent(client)

    outcome = run(
        agent.run_search_decision(
            "A scientific claim.",
            academic_search_executor=executor,
        )
    )

    assert outcome.action_taken is SearchToolName.SEARCH_ACADEMIC_WORKS
    assert len(client.calls) == 1
    executor.execute.assert_awaited_once()


@pytest.mark.parametrize("tool_name", ["delete_database", "search_academic_work"])
def test_unknown_and_similar_tool_names_are_strictly_rejected(
    tool_name, caplog
):
    client = ChatClientStub(tool_response(tool_name))
    executor = ExecutorStub()
    agent = SearchAgent(client)

    with caplog.at_level(logging.INFO, logger="vibescholar"):
        with pytest.raises(UnknownToolError):
            run(
                agent.run_search_decision(
                    "A scientific claim.",
                    academic_search_executor=executor,
                )
            )

    executor.execute.assert_not_awaited()
    assert len(client.calls) == 1
    log_text = caplog.text
    assert f"requested_tool_name={tool_name}" in log_text
    assert "allowed_tool_names=('search_academic_works', 'resolve_citation_metadata')" in log_text
    assert "termination=unauthorized_tool" in log_text
    assert "single query" not in log_text
    assert "A scientific claim." not in log_text


def test_workflow_converts_unknown_tool_to_failed_without_downstream_execution():
    agent = RaisingSearchAgent()
    evaluator = EvaluatorSpy()
    academic_executor = ExecutorStub()
    citation_executor = ExecutorStub()
    workflow = EvidenceSearchWorkflow(
        search_agent=agent,
        evidence_evaluator=evaluator,
        reference_filter=ReferenceFilterService(),
        session_store=EvidenceSearchSessionStore(),
        academic_search_executor=academic_executor,
        citation_resolution_executor=citation_executor,
    )

    result = run(
        workflow.execute_round(
            user_id=1,
            document_version_id=1,
            sentence_uuid="unknown-tool",
            sentence="A scientific claim.",
            citation_hints=None,
            filter_criteria=ReferenceFilterCriteria(),
        )
    )

    assert result.session_status is SearchSessionStatus.FAILED
    assert result.source is RoundResultSource.FAILED
    assert result.failure_code == "unauthorized_tool"
    assert result.search_outcome is None
    assert agent.initial_calls == 1
    assert agent.refinement_calls == 0
    assert evaluator.calls == 0
    academic_executor.execute.assert_not_awaited()
    citation_executor.execute.assert_not_awaited()


def test_evidence_service_rethrows_failed_outcome_as_controlled_typed_error(
    monkeypatch
):
    monkeypatch.setattr(settings, "USE_MOCK", False)
    monkeypatch.setattr(
        "app.services.evidence_service.ProjectSettingsRepository.get_by_project_id",
        lambda db, project_id: SimpleNamespace(
            publication_year_min=None,
            publication_year_max=None,
            only_open_access=False,
            max_suggestions=5,
        ),
    )
    result = EvidenceSearchRoundResult(
        session_status=SearchSessionStatus.FAILED,
        round_number=1,
        source=RoundResultSource.FAILED,
        evaluation_summary=summarize_evaluations([]),
        target_reached=False,
        refinement_recommended=False,
        failure_code="unauthorized_tool",
    )
    workflow = WorkflowResultStub(result)
    service = EvidenceService(
        workflow=workflow,
        session_store=EvidenceSearchSessionStore(),
    )

    with pytest.raises(UnknownToolError):
        run(
            service.search(
                object(),
                "A scientific claim.",
                1,
                user_id=1,
                document_version_id=1,
                sentence_uuid="unknown-tool",
            )
        )

    assert workflow.calls == 1


def test_router_returns_controlled_error_and_remains_usable():
    service = SequencedGroundingService()
    fastapi_app.dependency_overrides[grounding_router.get_current_user] = (
        lambda: SimpleNamespace(id=17)
    )
    fastapi_app.dependency_overrides[GroundingService] = lambda: service
    client = TestClient(fastapi_app, raise_server_exceptions=True)
    try:
        failed = client.post(
            "/api/sentences/search/evidence",
            json={"sentence_id": 23},
        )
        subsequent = client.post(
            "/api/sentences/search/evidence",
            json={"sentence_id": 23},
        )
    finally:
        client.close()
        fastapi_app.dependency_overrides.clear()

    assert failed.status_code == 502
    assert failed.json() == {
        "detail": "O modelo retornou uma resposta inválida."
    }
    assert "internal unauthorized tool details" not in failed.text
    assert subsequent.status_code == 200
    assert subsequent.json() == []
    assert service.calls == 2
