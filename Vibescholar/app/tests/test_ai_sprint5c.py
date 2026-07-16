"""Isolated tests for the deterministic single-round evidence-search workflow."""

import asyncio
import ast
import inspect

import pytest

from app.agents.schemas import (
    EvidenceAnalysisScope,
    EvidenceEvaluation,
    EvidenceEvaluationBatch,
    EvidenceVerdict,
    SearchToolName,
    SentenceType,
)
from app.core.config import settings
from app.llm.exceptions import LLMTimeoutError
from app.services.evidence_search_state import (
    EvidenceSearchSession,
    EvidenceSearchSessionStore,
    SearchAlreadyInProgressError,
    SearchSessionStatus,
)
from app.services.evidence_search_workflow import (
    EvidenceSearchWorkflow,
    RoundResultSource,
    summarize_evaluations,
)
from app.services.reference_filter_service import (
    ReferenceFilterCriteria,
    ReferenceFilterService,
)
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
    monkeypatch.setattr(settings, "TARGET_STRONG_EVIDENCE", 5)
    monkeypatch.setattr(settings, "MAX_SEARCH_ROUNDS", 3)
    monkeypatch.setattr(settings, "EVIDENCE_BATCH_SIZE", 5)


def run(coro):
    return asyncio.run(coro)


def reference(
    index: int,
    *,
    provider: str = "openalex",
    open_access: bool | None = True,
) -> ReferenceCandidate:
    return ReferenceCandidate(
        provider=provider,
        external_id=f"work-{index}",
        title=f"Academic work {index}",
        abstract=f"Abstract supporting candidate {index}.",
        is_open_access=open_access,
    )


def academic_outcome(
    candidates: list[ReferenceCandidate],
    *,
    status: AcademicSearchStatus = AcademicSearchStatus.SUCCESS,
) -> SearchToolExecutionOutcome:
    if status is AcademicSearchStatus.PARTIAL_SUCCESS:
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
    elif status is AcademicSearchStatus.FAILED:
        providers = [
            ProviderExecutionSummary(
                provider="openalex",
                success=False,
                results_found=0,
                error_code="service_unavailable",
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
            ),
            ProviderExecutionSummary(
                provider="semantic_scholar", success=True, results_found=0
            ),
        ]
    public = AcademicSearchToolResult(
        status=status,
        providers=providers,
        raw_results=len(candidates),
        after_deduplication=len(candidates),
        message="Typed academic result.",
        requested_limit_per_provider=settings.RESULTS_PER_PROVIDER,
        effective_limit_per_provider=settings.RESULTS_PER_PROVIDER,
    )
    execution = AcademicSearchExecutionResult(candidates=candidates, public_result=public)
    arguments = AcademicSearchInput(queries=["single academic query"])
    call = SearchToolCallRecord(
        tool_call_id="call-academic",
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


def citation_outcome(match: ReferenceCandidate) -> SearchToolExecutionOutcome:
    public = CitationResolutionToolResult(
        status=CitationResolutionStatus.RESOLVED,
        matches_found=1,
        message="Citation resolved.",
    )
    execution = CitationResolutionExecutionResult(matches=[match], public_result=public)
    arguments = CitationResolutionInput(
        citation_hints=[{"raw": "10.1000/example", "doi": "10.1000/example"}]
    )
    call = SearchToolCallRecord(
        tool_call_id="call-citation",
        tool_name=SearchToolName.RESOLVE_CITATION_METADATA,
        validated_arguments=arguments,
    )
    return SearchToolExecutionOutcome(
        sentence_type=SentenceType.CITATION_CLAIM,
        action_taken=SearchToolName.RESOLVE_CITATION_METADATA,
        tool_call_id=call.tool_call_id,
        tool_execution=execution,
        tool_call=call,
        reason=public.message,
    )


def no_action_outcome() -> SearchToolExecutionOutcome:
    return SearchToolExecutionOutcome(
        sentence_type=SentenceType.NON_SCIENTIFIC,
        action_taken=SearchToolName.NONE,
        reason="No academic search is needed.",
    )


class SearchAgentStub:
    def __init__(self, outcome, refined_outcome=None):
        self.outcome = outcome
        self.refined_outcome = refined_outcome or no_action_outcome()
        self.calls = []
        self.refinement_calls = []

    async def run_search_decision(
        self,
        sentence,
        citation_hints=None,
        academic_search_executor=None,
        citation_resolution_executor=None,
    ):
        self.calls.append(
            {
                "sentence": sentence,
                "citation_hints": citation_hints,
                "academic": academic_search_executor,
                "citation": citation_resolution_executor,
            }
        )
        return self.outcome

    async def run_refined_search_decision(
        self,
        *,
        sentence,
        previous_round,
        academic_search_executor=None,
        citation_resolution_executor=None,
    ):
        self.refinement_calls.append(
            {
                "sentence": sentence,
                "previous_round": previous_round,
                "academic": academic_search_executor,
                "citation": citation_resolution_executor,
            }
        )
        return self.refined_outcome


class EvaluatorStub:
    def __init__(self, verdicts=None, fail_on_call: int | None = None):
        self.verdicts = verdicts or {}
        self.fail_on_call = fail_on_call
        self.calls = []

    async def evaluate_batch(self, sentence, candidates):
        self.calls.append((sentence, candidates))
        if self.fail_on_call == len(self.calls):
            raise LLMTimeoutError("evaluation timed out")
        evaluations = []
        for item in candidates:
            verdict = self.verdicts.get(item.candidate_key, EvidenceVerdict.NO_SUPPORT)
            evaluations.append(
                EvidenceEvaluation(
                    candidate_key=item.candidate_key,
                    verdict=verdict,
                    confidence=0.8,
                    reason="Deterministic test evaluation.",
                    analysis_scope=(
                        EvidenceAnalysisScope.TITLE_AND_ABSTRACT
                        if item.abstract is not None
                        else EvidenceAnalysisScope.TITLE_ONLY
                    ),
                )
            )
        return EvidenceEvaluationBatch(evaluations=evaluations)


class FilterSpy(ReferenceFilterService):
    def __init__(self):
        self.calls = []

    def filter_candidates(self, candidates, criteria):
        self.calls.append((candidates, criteria))
        return super().filter_candidates(candidates, criteria)


def workflow(agent, evaluator, store=None, reference_filter=None):
    return EvidenceSearchWorkflow(
        search_agent=agent,
        evidence_evaluator=evaluator,
        reference_filter=reference_filter or ReferenceFilterService(),
        session_store=store or EvidenceSearchSessionStore(),
        academic_search_executor=object(),
        citation_resolution_executor=object(),
    )


def execute(instance, *, user_id=1, version_id=10, sentence_uuid="sentence-1", criteria=None):
    return instance.execute_round(
        user_id=user_id,
        document_version_id=version_id,
        sentence_uuid=sentence_uuid,
        sentence="A bounded scientific claim.",
        citation_hints=None,
        filter_criteria=criteria or ReferenceFilterCriteria(),
    )


def evaluated_candidate(
    item: ReferenceCandidate,
    verdict: EvidenceVerdict,
    *,
    shown: bool = False,
) -> EvidenceSearchCandidate:
    return EvidenceSearchCandidate(
        reference=item,
        provider=item.provider,
        search_round=1,
        evaluation_status=CandidateEvaluationStatus.EVALUATED,
        verdict=verdict,
        confidence=0.8,
        reason="Stored evaluation.",
        analysis_scope=EvidenceAnalysisScope.TITLE_AND_ABSTRACT,
        shown_to_user=shown,
    )


def test_summary_counts_every_verdict_deterministically():
    evaluations = [
        EvidenceEvaluation(
            candidate_key=f"key-{index}",
            verdict=verdict,
            confidence=0.8,
            reason="Counted verdict.",
            analysis_scope="title_only",
        )
        for index, verdict in enumerate(EvidenceVerdict)
    ]

    summary = summarize_evaluations(evaluations)

    assert summary.evaluated_candidates == 5
    assert summary.strong_support_count == 1
    assert summary.partial_support_count == 1
    assert summary.no_support_count == 1
    assert summary.contradicts_count == 1
    assert summary.insufficient_abstract_count == 1


def test_new_search_filters_then_evaluates_in_batches_of_at_most_five():
    async def scenario():
        candidates = [reference(index) for index in range(12)]
        agent = SearchAgentStub(academic_outcome(candidates))
        evaluator = EvaluatorStub()
        filter_spy = FilterSpy()
        instance = workflow(agent, evaluator, reference_filter=filter_spy)

        result = await execute(instance)

        assert result.source is RoundResultSource.NO_ACTION
        assert len(agent.calls) == 1
        assert len(agent.refinement_calls) == 1
        assert len(filter_spy.calls) == 1
        assert [len(call[1]) for call in evaluator.calls] == [5, 5, 2]
        assert len(result.evaluations) == 12
        assert result.round_summary.after_filters == 12
        assert result.round_summary.evaluated_candidates == 12
        assert result.refinement_recommended is False
        assert all(
            set(item.model_dump()) == {"candidate_key", "title", "abstract"}
            for _, batch in evaluator.calls
            for item in batch
        )

    run(scenario())


def test_unshown_reserve_has_precedence_and_is_not_marked_presented():
    async def scenario():
        store = EvidenceSearchSessionStore()
        key = (1, 10, "sentence-1")
        item = reference(1)
        stored = evaluated_candidate(item, EvidenceVerdict.PARTIAL_SUPPORT)
        session = EvidenceSearchSession(current_round=1)
        session.candidates[item.candidate_key] = stored
        session.evaluated_candidate_keys.add(item.candidate_key)
        session.partial_support_keys.add(item.candidate_key)
        await store.set(key, session)
        agent = SearchAgentStub(academic_outcome([reference(2)]))
        evaluator = EvaluatorStub()
        instance = workflow(agent, evaluator, store)

        first = await execute(instance)
        second = await execute(instance)

        assert first.source is second.source is RoundResultSource.UNSHOWN_RESERVE
        assert first.reserved_candidate_keys == (item.candidate_key,)
        assert session.presented_candidate_keys == set()
        assert session.candidates[item.candidate_key].shown_to_user is False
        assert agent.calls == []
        assert evaluator.calls == []

    run(scenario())


def test_pending_candidates_are_evaluated_before_any_new_search_and_not_twice():
    async def scenario():
        store = EvidenceSearchSessionStore()
        key = (1, 10, "sentence-1")
        item = reference(1)
        session = EvidenceSearchSession(current_round=1)
        session.candidates[item.candidate_key] = EvidenceSearchCandidate(
            reference=item,
            provider=item.provider,
            search_round=1,
        )
        await store.set(key, session)
        agent = SearchAgentStub(academic_outcome([reference(2)]))
        evaluator = EvaluatorStub({item.candidate_key: EvidenceVerdict.STRONG_SUPPORT})
        instance = workflow(agent, evaluator, store)

        first = await execute(instance)
        second = await execute(instance)

        assert first.source is RoundResultSource.PENDING_EVALUATIONS
        assert second.source is RoundResultSource.UNSHOWN_RESERVE
        assert len(evaluator.calls) == 1
        assert agent.calls == []
        assert item.candidate_key in session.evaluated_candidate_keys

    run(scenario())


def test_empty_and_all_filtered_results_recommend_future_refinement_without_evaluation():
    async def scenario():
        empty_agent = SearchAgentStub(academic_outcome([], status=AcademicSearchStatus.EMPTY))
        empty_evaluator = EvaluatorStub()
        empty = await execute(workflow(empty_agent, empty_evaluator))
        assert empty.source is RoundResultSource.NO_ACTION
        assert empty.refinement_recommended is False
        assert empty_evaluator.calls == []

        closed = reference(1, open_access=False)
        filtered_agent = SearchAgentStub(academic_outcome([closed]))
        filtered_evaluator = EvaluatorStub()
        filtered_store = EvidenceSearchSessionStore()
        filter_spy = FilterSpy()
        filtered_workflow = workflow(
            filtered_agent,
            filtered_evaluator,
            store=filtered_store,
            reference_filter=filter_spy,
        )
        filtered = await execute(
            filtered_workflow,
            criteria=ReferenceFilterCriteria(only_open_access=True),
        )
        assert filtered.source is RoundResultSource.NO_ACTION
        assert filtered.filter_result.total_rejected == 1
        assert filtered.filter_result.total_accepted == 0
        assert filtered_evaluator.calls == []
        assert len(filter_spy.calls) == 1
        assert filtered_evaluator.calls == []

    run(scenario())


def test_partial_success_continues_with_valid_candidates_but_total_failure_stops():
    async def scenario():
        item = reference(1)
        partial_evaluator = EvaluatorStub()
        partial = await execute(
            workflow(
                SearchAgentStub(
                    academic_outcome([item], status=AcademicSearchStatus.PARTIAL_SUCCESS)
                ),
                partial_evaluator,
            )
        )
        assert partial.session_status is SearchSessionStatus.EXHAUSTED
        assert len(partial_evaluator.calls) == 1

        filter_spy = FilterSpy()
        failed_evaluator = EvaluatorStub()
        failed = await execute(
            workflow(
                SearchAgentStub(academic_outcome([], status=AcademicSearchStatus.FAILED)),
                failed_evaluator,
                reference_filter=filter_spy,
            )
        )
        assert failed.source is RoundResultSource.FAILED
        assert failed.session_status is SearchSessionStatus.FAILED
        assert failed.failure_code == "academic_search_failed"
        assert filter_spy.calls == []
        assert failed_evaluator.calls == []
        assert failed.refinement_recommended is False

    run(scenario())


def test_citation_resolution_is_preserved_without_filter_or_semantic_evaluation():
    async def scenario():
        item = reference(1)
        filter_spy = FilterSpy()
        evaluator = EvaluatorStub()
        result = await execute(
            workflow(
                SearchAgentStub(citation_outcome(item)),
                evaluator,
                reference_filter=filter_spy,
            )
        )

        assert result.source is RoundResultSource.CITATION_RESOLUTION
        assert result.citation_resolution.matches == [item]
        assert result.evaluations == []
        assert filter_spy.calls == []
        assert evaluator.calls == []
        assert result.refinement_recommended is False

    run(scenario())


def test_no_action_does_not_filter_evaluate_or_recommend_refinement():
    async def scenario():
        filter_spy = FilterSpy()
        evaluator = EvaluatorStub()
        agent = SearchAgentStub(no_action_outcome())
        result = await execute(
            workflow(agent, evaluator, reference_filter=filter_spy)
        )

        assert result.source is RoundResultSource.NO_ACTION
        assert len(agent.calls) == 1
        assert filter_spy.calls == []
        assert evaluator.calls == []
        assert result.refinement_recommended is False

    run(scenario())


def test_target_and_round_limit_stop_before_new_inference(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "TARGET_STRONG_EVIDENCE", 1)
        store = EvidenceSearchSessionStore()
        target_session = EvidenceSearchSession(current_round=1)
        target_session.strong_support_keys.add("already-strong")
        await store.set((1, 10, "target"), target_session)
        exhausted_session = EvidenceSearchSession(current_round=settings.MAX_SEARCH_ROUNDS)
        await store.set((1, 10, "exhausted"), exhausted_session)
        agent = SearchAgentStub(academic_outcome([reference(1)]))
        instance = workflow(agent, EvaluatorStub(), store)

        target = await execute(instance, sentence_uuid="target")
        exhausted = await execute(instance, sentence_uuid="exhausted")

        assert target.target_reached is True
        assert target.session_status is SearchSessionStatus.COMPLETED
        assert exhausted.session_status is SearchSessionStatus.EXHAUSTED
        assert agent.calls == []

    run(scenario())


def test_five_strong_results_reach_target_while_partials_do_not():
    async def scenario():
        strong_candidates = [reference(index) for index in range(5)]
        strong_verdicts = {
            item.candidate_key: EvidenceVerdict.STRONG_SUPPORT
            for item in strong_candidates
        }
        strong = await execute(
            workflow(
                SearchAgentStub(academic_outcome(strong_candidates)),
                EvaluatorStub(strong_verdicts),
            )
        )
        assert strong.target_reached is True
        assert strong.session_status is SearchSessionStatus.COMPLETED

        partial_candidates = [reference(index + 10) for index in range(5)]
        partial_verdicts = {
            item.candidate_key: EvidenceVerdict.PARTIAL_SUPPORT
            for item in partial_candidates
        }
        partial = await execute(
            workflow(
                SearchAgentStub(academic_outcome(partial_candidates)),
                EvaluatorStub(partial_verdicts),
            )
        )
        assert partial.target_reached is False
        assert partial.session_status is SearchSessionStatus.EXHAUSTED
        assert partial.round_summary.strong_support_count == 0
        assert partial.round_summary.partial_support_count == 5

    run(scenario())


def test_terminal_session_with_shown_candidates_has_no_reserved_work():
    async def scenario():
        store = EvidenceSearchSessionStore()
        key = (1, 10, "shown")
        item = reference(1)
        session = EvidenceSearchSession(
            current_round=settings.MAX_SEARCH_ROUNDS,
            status=SearchSessionStatus.EXHAUSTED,
        )
        session.candidates[item.candidate_key] = evaluated_candidate(
            item,
            EvidenceVerdict.NO_SUPPORT,
            shown=True,
        )
        session.evaluated_candidate_keys.add(item.candidate_key)
        await store.set(key, session)

        result = await execute(
            workflow(SearchAgentStub(no_action_outcome()), EvaluatorStub(), store),
            sentence_uuid="shown",
        )

        assert result.source is RoundResultSource.NO_ACTION
        assert result.evaluations == []
        assert await store.get(key) is None

    run(scenario())


def test_evaluation_failure_is_atomic_and_guard_clears_in_progress():
    async def scenario():
        store = EvidenceSearchSessionStore()
        candidates = [reference(index) for index in range(6)]
        agent = SearchAgentStub(academic_outcome(candidates))
        evaluator = EvaluatorStub(fail_on_call=2)
        instance = workflow(agent, evaluator, store)

        with pytest.raises(LLMTimeoutError):
            await execute(instance)

        assert len(evaluator.calls) == 2
        assert await store.get((1, 10, "sentence-1")) is None

    run(scenario())


def test_same_key_is_exclusive_while_different_keys_can_progress_concurrently():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingAgent(SearchAgentStub):
            async def run_search_decision(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                entered.set()
                await release.wait()
                return self.outcome

        store = EvidenceSearchSessionStore()
        agent = BlockingAgent(no_action_outcome())
        instance = workflow(agent, EvaluatorStub(), store)
        first = asyncio.create_task(execute(instance))
        await entered.wait()
        with pytest.raises(SearchAlreadyInProgressError):
            await execute(instance)
        release.set()
        await first

        class TwoKeyAgent(SearchAgentStub):
            def __init__(self):
                super().__init__(no_action_outcome())
                self.both_entered = asyncio.Event()

            async def run_search_decision(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                if len(self.calls) == 2:
                    self.both_entered.set()
                await asyncio.wait_for(self.both_entered.wait(), timeout=0.2)
                return self.outcome

        parallel_agent = TwoKeyAgent()
        parallel = workflow(parallel_agent, EvaluatorStub(), EvidenceSearchSessionStore())
        await asyncio.gather(
            execute(parallel, user_id=1, sentence_uuid="one"),
            execute(parallel, user_id=2, sentence_uuid="two"),
        )
        assert len(parallel_agent.calls) == 2

    run(scenario())


def test_workflow_has_no_llm_client_http_orm_ui_router_or_prompt_logic():
    import app.services.evidence_search_workflow as module

    source = inspect.getsource(module)
    lowered = source.casefold()
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "httpx" not in imported_modules
    assert "openai" not in imported_modules
    assert not any(name.startswith("sqlalchemy") for name in imported_modules)
    assert "app.llm.ollama_client" not in imported_modules
    assert "app.services.evidence_service" not in imported_modules
    assert not any(name.startswith("app.ui") for name in imported_modules)
    assert not any(name.startswith("app.routers") for name in imported_modules)
    assert "prompts/" not in lowered
    assert '"role": "tool"' not in source
    assert ".commit(" not in lowered
