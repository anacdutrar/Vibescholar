"""Isolated tests for semantic refinement and bounded multi-round coordination."""

import asyncio
import ast
import inspect
import json

import pytest

from app.agents.schemas import (
    EvidenceAnalysisScope,
    EvidenceEvaluation,
    EvidenceEvaluationBatch,
    EvidenceVerdict,
    ProviderRoundResult,
    SearchPlan,
    SearchRoundSummary,
    SearchToolName,
    SentenceType,
)
from app.agents.search_agent import SearchAgent
from app.core.config import settings
from app.llm.exceptions import LLMTimeoutError, LLMUnavailableError, ToolArgumentsValidationError
from app.llm.ollama_client import LLMChatResponse, LLMToolCall
from app.services.evidence_search_state import (
    EvidenceSearchSession,
    EvidenceSearchSessionStore,
    SearchSessionStatus,
)
from app.services.evidence_search_workflow import EvidenceSearchWorkflow, RoundResultSource
from app.services.reference_filter_service import ReferenceFilterCriteria, ReferenceFilterService
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchInput,
    AcademicSearchStatus,
    AcademicSearchToolResult,
    CandidateEvaluationStatus,
    CitationResolutionExecutionResult,
    CitationResolutionInput,
    CitationResolutionStatus,
    CitationResolutionToolResult,
    EvidenceSearchCandidate,
    ProviderExecutionSummary,
    ReferenceCandidate,
    SearchToolCallRecord,
    SearchToolExecutionOutcome,
)


@pytest.fixture(autouse=True)
def stable_limits(monkeypatch):
    monkeypatch.setattr(settings, "MAX_SEARCH_ROUNDS", 3)
    monkeypatch.setattr(settings, "TARGET_STRONG_EVIDENCE", 5)
    monkeypatch.setattr(settings, "EVIDENCE_BATCH_SIZE", 5)


def run(coro):
    return asyncio.run(coro)


def reference(index: int) -> ReferenceCandidate:
    return ReferenceCandidate(
        provider="openalex",
        external_id=f"round-work-{index}",
        title=f"Round evidence {index}",
        abstract=f"Academic abstract {index}.",
    )


def academic_outcome(
    candidates: list[ReferenceCandidate],
    *,
    query: str,
    status: AcademicSearchStatus = AcademicSearchStatus.SUCCESS,
) -> SearchToolExecutionOutcome:
    if status is AcademicSearchStatus.FAILED:
        providers = [
            ProviderExecutionSummary(
                provider="openalex",
                success=False,
                results_found=0,
                error_code="service_unavailable",
            )
        ]
    elif status is AcademicSearchStatus.PARTIAL_SUCCESS:
        providers = [
            ProviderExecutionSummary(
                provider="openalex", success=True, results_found=len(candidates)
            ),
            ProviderExecutionSummary(
                provider="semantic_scholar",
                success=False,
                results_found=0,
                error_code="rate_limited",
            ),
        ]
    else:
        providers = [
            ProviderExecutionSummary(
                provider="openalex", success=True, results_found=len(candidates)
            )
        ]
    public = AcademicSearchToolResult(
        status=status,
        providers=providers,
        raw_results=len(candidates),
        after_deduplication=len(candidates),
        message="Academic round completed.",
        requested_limit_per_provider=settings.RESULTS_PER_PROVIDER,
        effective_limit_per_provider=settings.RESULTS_PER_PROVIDER,
    )
    execution = AcademicSearchExecutionResult(candidates=candidates, public_result=public)
    arguments = AcademicSearchInput(queries=[query])
    call = SearchToolCallRecord(
        tool_call_id=f"call-{query}",
        tool_name=SearchToolName.SEARCH_ACADEMIC_WORKS,
        validated_arguments=arguments,
    )
    return SearchToolExecutionOutcome(
        sentence_type=SentenceType.SCIENTIFIC_CLAIM,
        action_taken=SearchToolName.SEARCH_ACADEMIC_WORKS,
        tool_call_id=call.tool_call_id,
        tool_execution=execution,
        tool_call=call,
        reason=public.message,
    )


def no_action_outcome() -> SearchToolExecutionOutcome:
    return SearchToolExecutionOutcome(
        sentence_type=SentenceType.SCIENTIFIC_CLAIM,
        action_taken=SearchToolName.NONE,
        reason="No further semantic query is useful.",
    )


class SequenceAgent:
    def __init__(self, initial, refined=()):
        self.initial = initial
        self.refined = list(refined)
        self.initial_calls = []
        self.refined_calls = []

    async def run_search_decision(self, sentence, citation_hints=None, **executors):
        self.initial_calls.append((sentence, citation_hints, executors))
        if isinstance(self.initial, Exception):
            raise self.initial
        return self.initial

    async def run_refined_search_decision(self, *, sentence, previous_round, **executors):
        self.refined_calls.append((sentence, previous_round, executors))
        outcome = self.refined.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Evaluator:
    def __init__(self, verdicts=None):
        self.verdicts = verdicts or {}
        self.calls = []

    async def evaluate_batch(self, sentence, candidates):
        self.calls.append((sentence, candidates))
        return EvidenceEvaluationBatch(
            evaluations=[
                EvidenceEvaluation(
                    candidate_key=item.candidate_key,
                    verdict=self.verdicts.get(item.candidate_key, EvidenceVerdict.NO_SUPPORT),
                    confidence=0.9,
                    reason="Deterministic test verdict.",
                    analysis_scope=(
                        EvidenceAnalysisScope.TITLE_AND_ABSTRACT
                        if item.abstract
                        else EvidenceAnalysisScope.TITLE_ONLY
                    ),
                )
                for item in candidates
            ]
        )


def workflow(agent, evaluator, store=None):
    return EvidenceSearchWorkflow(
        search_agent=agent,
        evidence_evaluator=evaluator,
        reference_filter=ReferenceFilterService(),
        session_store=store or EvidenceSearchSessionStore(),
        academic_search_executor=object(),
        citation_resolution_executor=object(),
    )


async def execute(instance, sentence_uuid="sentence-6b"):
    return await instance.execute_round(
        user_id=1,
        document_version_id=10,
        sentence_uuid=sentence_uuid,
        sentence="A scientific claim requiring evidence.",
        citation_hints=None,
        filter_criteria=ReferenceFilterCriteria(),
    )


def test_empty_refines_once_and_reaches_target_with_aggregate_summary():
    async def scenario():
        strong = [reference(index) for index in range(5)]
        verdicts = {item.candidate_key: EvidenceVerdict.STRONG_SUPPORT for item in strong}
        agent = SequenceAgent(
            academic_outcome([], query="initial", status=AcademicSearchStatus.EMPTY),
            [academic_outcome(strong, query="refined")],
        )
        evaluator = Evaluator(verdicts)
        store = EvidenceSearchSessionStore()

        result = await execute(workflow(agent, evaluator, store))
        session = await store.get((1, 10, "sentence-6b"))

        assert result.target_reached is True
        assert result.session_status is SearchSessionStatus.COMPLETED
        assert len(agent.initial_calls) == 1
        assert len(agent.refined_calls) == 1
        assert len(session.round_history) == 2
        assert [item.round_number for item in session.round_history] == [1, 2]
        assert session.round_history[0].raw_results == 0
        assert session.round_history[1].strong_support_count == 5
        assert session.queries_used == ["initial", "refined"]
        assert session.provider_statistics["openalex"].successful_rounds == 2

    run(scenario())


def test_few_strong_results_refine_and_new_reserves_do_not_stop_loop():
    async def scenario():
        first = [reference(index) for index in range(2)]
        second = [reference(index) for index in range(2, 5)]
        verdicts = {
            item.candidate_key: EvidenceVerdict.STRONG_SUPPORT for item in [*first, *second]
        }
        agent = SequenceAgent(
            academic_outcome(first, query="first"),
            [academic_outcome(second, query="second")],
        )
        result = await execute(workflow(agent, Evaluator(verdicts)))

        assert result.target_reached is True
        assert len(result.evaluations) == 5
        assert len(agent.refined_calls) == 1
        assert all(call[1].round_number == 1 for call in agent.refined_calls)

    run(scenario())


def test_partial_support_never_satisfies_target_and_stops_at_three_rounds():
    async def scenario():
        rounds = [[reference(index)] for index in range(3)]
        verdicts = {
            item.candidate_key: EvidenceVerdict.PARTIAL_SUPPORT
            for group in rounds
            for item in group
        }
        agent = SequenceAgent(
            academic_outcome(rounds[0], query="q1"),
            [
                academic_outcome(rounds[1], query="q2", status=AcademicSearchStatus.PARTIAL_SUCCESS),
                academic_outcome(rounds[2], query="q3"),
            ],
        )
        store = EvidenceSearchSessionStore()
        result = await execute(workflow(agent, Evaluator(verdicts), store))
        session = await store.get((1, 10, "sentence-6b"))

        assert result.target_reached is False
        assert result.session_status is SearchSessionStatus.EXHAUSTED
        assert result.round_number == 3
        assert len(agent.initial_calls) == 1
        assert len(agent.refined_calls) == 2
        assert len(result.evaluations) == 3
        assert len(session.partial_support_keys) == 3
        assert len(session.round_history) == 3

    run(scenario())


def test_one_round_with_thirty_candidates_uses_at_most_six_evaluator_batches():
    async def scenario():
        candidates = [reference(index) for index in range(30)]
        agent = SequenceAgent(
            academic_outcome(candidates, query="bounded"),
            [no_action_outcome()],
        )
        evaluator = Evaluator()

        result = await execute(workflow(agent, evaluator))

        assert len(agent.initial_calls) == 1
        assert len(agent.refined_calls) == 1
        assert [len(batch) for _, batch in evaluator.calls] == [5, 5, 5, 5, 5, 5]
        assert len(result.evaluations) == 30

    run(scenario())


def test_failed_and_llm_failures_never_trigger_another_refinement():
    async def scenario():
        failed_agent = SequenceAgent(
            academic_outcome([], query="failed", status=AcademicSearchStatus.FAILED),
            [no_action_outcome()],
        )
        failed = await execute(workflow(failed_agent, Evaluator()))
        assert failed.source is RoundResultSource.FAILED
        assert failed.session_status is SearchSessionStatus.FAILED
        assert failed_agent.refined_calls == []

        for error in (LLMTimeoutError("timeout"), LLMUnavailableError("unavailable")):
            initial_agent = SequenceAgent(error, [no_action_outcome()])
            with pytest.raises(type(error)):
                await execute(
                    workflow(initial_agent, Evaluator()),
                    sentence_uuid=f"initial-{type(error).__name__}",
                )
            assert initial_agent.refined_calls == []

            agent = SequenceAgent(
                academic_outcome([], query="empty", status=AcademicSearchStatus.EMPTY),
                [error, no_action_outcome()],
            )
            with pytest.raises(type(error)):
                await execute(workflow(agent, Evaluator()), sentence_uuid=type(error).__name__)
            assert len(agent.refined_calls) == 1

    run(scenario())


def test_preexisting_reserve_returns_before_search_and_pending_is_evaluated_first():
    async def scenario():
        reserve_store = EvidenceSearchSessionStore()
        reserve = reference(1)
        reserve_session = EvidenceSearchSession(current_round=1)
        reserve_session.candidates[reserve.candidate_key] = EvidenceSearchCandidate(
            reference=reserve,
            provider=reserve.provider,
            search_round=1,
            evaluation_status=CandidateEvaluationStatus.EVALUATED,
            verdict=EvidenceVerdict.PARTIAL_SUPPORT,
            confidence=0.8,
            reason="Stored reserve.",
            analysis_scope=EvidenceAnalysisScope.TITLE_AND_ABSTRACT,
        )
        reserve_session.evaluated_candidate_keys.add(reserve.candidate_key)
        reserve_session.partial_support_keys.add(reserve.candidate_key)
        await reserve_store.set((1, 10, "reserve"), reserve_session)
        reserve_agent = SequenceAgent(no_action_outcome())
        reserve_result = await execute(
            workflow(reserve_agent, Evaluator(), reserve_store), "reserve"
        )
        assert reserve_result.source is RoundResultSource.UNSHOWN_RESERVE
        assert reserve_agent.initial_calls == reserve_agent.refined_calls == []

        pending_store = EvidenceSearchSessionStore()
        pending = reference(2)
        pending_session = EvidenceSearchSession(current_round=1)
        pending_session.candidates[pending.candidate_key] = EvidenceSearchCandidate(
            reference=pending,
            provider=pending.provider,
            search_round=1,
        )
        pending_session.round_history.append(summary(1, ["initial"], strong=0))
        await pending_store.set((1, 10, "pending"), pending_session)
        new_strong = [reference(index) for index in range(3, 7)]
        verdicts = {pending.candidate_key: EvidenceVerdict.STRONG_SUPPORT} | {
            item.candidate_key: EvidenceVerdict.STRONG_SUPPORT for item in new_strong
        }
        pending_agent = SequenceAgent(
            no_action_outcome(),
            [academic_outcome(new_strong, query="refined")],
        )
        evaluator = Evaluator(verdicts)
        pending_result = await execute(
            workflow(pending_agent, evaluator, pending_store), "pending"
        )
        assert pending_result.target_reached is True
        assert pending_agent.initial_calls == []
        assert len(pending_agent.refined_calls) == 1
        assert evaluator.calls[0][1][0].candidate_key == pending.candidate_key

    run(scenario())


def summary(round_number, queries, strong=0):
    return SearchRoundSummary(
        round_number=round_number,
        queries_used=queries,
        provider_results=[
            ProviderRoundResult(provider="openalex", success=True, results_found=0)
        ],
        raw_results=0,
        after_deduplication=0,
        after_filters=0,
        evaluated_candidates=0,
        strong_support_count=strong,
        partial_support_count=0,
        missing_strong_evidence=max(5 - strong, 0),
    )


class RecordingClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def chat(self, messages, *, tools=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        return self.response


class Executor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        return self.result


def test_search_agent_refinement_uses_one_native_tool_call_and_aggregate_data_only():
    async def scenario():
        item = reference(1)
        execution = academic_outcome([item], query="new query").tool_execution
        client = RecordingClient(
            LLMChatResponse(
                content=None,
                model="qwen",
                finish_reason="tool_calls",
                tool_calls=(
                    LLMToolCall(
                        tool_call_id="refined-call",
                        tool_name="search_academic_works",
                        arguments_json=json.dumps(
                            {"queries": ["new query"]}
                        ),
                    ),
                ),
            )
        )
        executor = Executor(execution)
        agent = SearchAgent(client)
        previous = summary(1, ["old query"])

        outcome = await agent.run_refined_search_decision(
            sentence="Original scientific sentence.",
            previous_round=previous,
            academic_search_executor=executor,
        )

        assert outcome.action_taken is SearchToolName.SEARCH_ACADEMIC_WORKS
        assert outcome.tool_call_id == "refined-call"
        assert len(client.calls) == 1
        assert len(executor.calls) == 1
        assert all(message["role"] != "tool" for message in client.calls[0]["messages"])
        payload = json.loads(client.calls[0]["messages"][1]["content"])
        assert set(payload) == {"sentence", "previous_round"}
        assert set(payload["previous_round"]) == set(SearchRoundSummary.model_fields)
        serialized = json.dumps(payload)
        assert "candidate_key" not in serialized
        assert "abstract" not in serialized
        assert "doi" not in serialized.casefold()

    run(scenario())


def test_refinement_rejects_citation_tool_before_executor_and_workflow_has_no_prompt_logic():
    async def scenario():
        client = RecordingClient(
            LLMChatResponse(
                content=None,
                model="qwen",
                finish_reason="tool_calls",
                tool_calls=(
                    LLMToolCall(
                        tool_call_id="citation-call",
                        tool_name="resolve_citation_metadata",
                        arguments_json=CitationResolutionInput(
                            citation_hints=[{"raw": "(Silva, 2024)", "author": "Silva", "year": 2024}]
                        ).model_dump_json(),
                    ),
                ),
            )
        )
        citation_result = CitationResolutionExecutionResult(
            matches=[],
            public_result=CitationResolutionToolResult(
                status=CitationResolutionStatus.NOT_FOUND,
                matches_found=0,
                message="No match.",
            ),
        )
        executor = Executor(citation_result)
        with pytest.raises(ToolArgumentsValidationError):
            await SearchAgent(client).run_refined_search_decision(
                sentence="A claim.",
                previous_round=summary(1, ["old"]),
                citation_resolution_executor=executor,
            )
        assert executor.calls == []
        assert len(client.calls) == 1

    run(scenario())

    import app.services.evidence_search_workflow as module

    source = inspect.getsource(module)
    imports = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }
    assert "app.agents.search_agent" not in imports
    assert "app.agents.evidence_evaluator" not in imports
    assert "app.llm.ollama_client" not in imports
    assert "openai" not in imports
    assert "prompt" not in source.casefold()
    assert '"role": "tool"' not in source
