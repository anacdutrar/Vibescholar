"""Deterministic coordination of bounded academic evidence-search rounds.

Future composition is expected to be Router -> EvidenceService ->
EvidenceSearchWorkflow. EvidenceService remains the public facade; this module
coordinates only transient AI search state and never accesses ORM or UI layers.
"""

import time
from collections import Counter
from collections.abc import Iterable
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from app.agents.schemas import (
    CitationHint,
    EvidenceCandidateInput,
    EvidenceEvaluation,
    EvidenceEvaluationBatch,
    EvidenceVerdict,
    ProviderRoundResult,
    SearchRoundSummary,
    SearchToolName,
)
from app.core.config import settings
from app.core.logging import logger
from app.llm.exceptions import LLMError
from app.services.evidence_search_state import (
    EvidenceSearchSession,
    EvidenceSearchSessionStore,
    ProviderSearchStatistics,
    SearchSessionKey,
    SearchSessionStatus,
)
from app.services.reference_filter_service import (
    ReferenceFilterCriteria,
    ReferenceFilterResult,
    ReferenceFilterService,
)
from app.tools.academic_search import AcademicSearchExecutor
from app.tools.citation_resolution import CitationResolutionExecutor
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchInput,
    AcademicSearchStatus,
    AcademicSearchToolResult,
    CandidateEvaluationStatus,
    CitationResolutionExecutionResult,
    CitationResolutionStatus,
    EvidenceSearchCandidate,
    SearchToolExecutionOutcome,
)


class SearchDecisionAgent(Protocol):
    """Typed SearchAgent boundary required by the workflow."""

    async def run_search_decision(
        self,
        sentence: str,
        citation_hints: list[CitationHint] | None = None,
        academic_search_executor: AcademicSearchExecutor | None = None,
        citation_resolution_executor: CitationResolutionExecutor | None = None,
    ) -> SearchToolExecutionOutcome:
        """Run one model decision and at most one tool execution."""
        ...

    async def run_refined_search_decision(
        self,
        *,
        sentence: str,
        previous_round: SearchRoundSummary,
        academic_search_executor: AcademicSearchExecutor | None = None,
        citation_resolution_executor: CitationResolutionExecutor | None = None,
    ) -> SearchToolExecutionOutcome:
        """Run one refined decision using aggregate round data only."""
        ...


class EvidenceBatchEvaluator(Protocol):
    """Typed EvidenceEvaluator boundary required by the workflow."""

    async def evaluate_batch(
        self,
        sentence: str,
        candidates: list[EvidenceCandidateInput],
    ) -> EvidenceEvaluationBatch:
        """Evaluate one caller-owned batch of at most five candidates."""
        ...


class RoundResultSource(str, Enum):
    """Operational origin of one workflow result."""

    UNSHOWN_RESERVE = "unshown_reserve"
    PENDING_EVALUATIONS = "pending_evaluations"
    NEW_SEARCH = "new_search"
    CITATION_RESOLUTION = "citation_resolution"
    NO_ACTION = "no_action"
    FAILED = "failed"
    REFINEMENT_RECOMMENDED = "refinement_recommended"


class EvaluationSummary(BaseModel):
    """Deterministic counts for all evaluator verdicts in one returned result."""

    evaluated_candidates: int = Field(ge=0, description="Number of evaluations summarized.")
    strong_support_count: int = Field(ge=0, description="Directly supporting candidates.")
    partial_support_count: int = Field(ge=0, description="Partially supporting candidates.")
    no_support_count: int = Field(ge=0, description="Related candidates without claim support.")
    contradicts_count: int = Field(ge=0, description="Candidates contradicting the claim.")
    insufficient_abstract_count: int = Field(
        ge=0,
        description="Candidates with insufficient semantic metadata.",
    )

    @model_validator(mode="after")
    def validate_total(self) -> "EvaluationSummary":
        """Require the total to equal the sum of all exclusive verdict counts."""
        verdict_total = (
            self.strong_support_count
            + self.partial_support_count
            + self.no_support_count
            + self.contradicts_count
            + self.insufficient_abstract_count
        )
        if self.evaluated_candidates != verdict_total:
            raise ValueError("evaluated_candidates must equal the verdict-count total")
        return self


def summarize_evaluations(
    evaluations: Iterable[EvidenceEvaluation],
) -> EvaluationSummary:
    """Count typed verdicts without model assistance or order-dependent behavior."""
    items = list(evaluations)
    counts = Counter(item.verdict for item in items)
    return EvaluationSummary(
        evaluated_candidates=len(items),
        strong_support_count=counts[EvidenceVerdict.STRONG_SUPPORT],
        partial_support_count=counts[EvidenceVerdict.PARTIAL_SUPPORT],
        no_support_count=counts[EvidenceVerdict.NO_SUPPORT],
        contradicts_count=counts[EvidenceVerdict.CONTRADICTS],
        insufficient_abstract_count=counts[EvidenceVerdict.INSUFFICIENT_ABSTRACT],
    )


class EvidenceSearchRoundResult(BaseModel):
    """Typed result of reused work or at most one newly executed search round."""

    session_status: SearchSessionStatus = Field(description="Session lifecycle after this operation.")
    round_number: int = Field(ge=0, description="Current one-based round, or zero before any search.")
    source: RoundResultSource = Field(description="Operational source of the returned result.")
    search_outcome: SearchToolExecutionOutcome | None = Field(
        default=None,
        description="Actual SearchAgent outcome when a new decision was executed.",
    )
    filter_result: ReferenceFilterResult | None = Field(
        default=None,
        description="Deterministic filtering result for newly recovered academic candidates.",
    )
    round_summary: SearchRoundSummary | None = Field(
        default=None,
        description="Aggregate operational summary for a newly executed academic search.",
    )
    evaluation_summary: EvaluationSummary = Field(description="Counts for returned evaluations.")
    evaluations: list[EvidenceEvaluation] = Field(
        default_factory=list,
        description="Evaluations returned without implicitly marking them as presented.",
    )
    reserved_candidate_keys: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Candidate keys reserved for delivery by the future public facade.",
    )
    target_reached: bool = Field(description="Whether strong evidence reached the configured target.")
    refinement_recommended: bool = Field(
        description="Whether a future caller may request another semantic search strategy.",
    )
    failure_code: str | None = Field(
        default=None,
        description="Safe operational failure code for a typed failed result.",
    )

    @property
    def citation_resolution(self) -> CitationResolutionExecutionResult | None:
        """Expose citation matches without duplicating the execution object in serialization."""
        if self.search_outcome and isinstance(
            self.search_outcome.tool_execution,
            CitationResolutionExecutionResult,
        ):
            return self.search_outcome.tool_execution
        return None


class EvidenceSearchWorkflow:
    """Coordinate reuse and up to the configured number of sequential search rounds."""

    def __init__(
        self,
        search_agent: SearchDecisionAgent,
        evidence_evaluator: EvidenceBatchEvaluator,
        reference_filter: ReferenceFilterService,
        session_store: EvidenceSearchSessionStore,
        academic_search_executor: AcademicSearchExecutor,
        citation_resolution_executor: CitationResolutionExecutor,
    ) -> None:
        self._search_agent = search_agent
        self._evidence_evaluator = evidence_evaluator
        self._reference_filter = reference_filter
        self._session_store = session_store
        self._academic_search_executor = academic_search_executor
        self._citation_resolution_executor = citation_resolution_executor

    async def execute_round(
        self,
        *,
        user_id: int,
        document_version_id: int,
        sentence_uuid: str,
        sentence: str,
        citation_hints: list[CitationHint] | None,
        filter_criteria: ReferenceFilterCriteria,
    ) -> EvidenceSearchRoundResult:
        """Reuse stored work or execute a bounded sequential refinement cycle."""
        if not isinstance(sentence, str) or not sentence.strip():
            raise ValueError("sentence must contain non-whitespace text")
        key: SearchSessionKey = (user_id, document_version_id, sentence_uuid)
        started_at = time.perf_counter()

        async with self._session_store.search_guard(key) as session:
            try:
                reserves = self._unshown_evaluations(session)
                if reserves:
                    return self._result(
                        session,
                        RoundResultSource.UNSHOWN_RESERVE,
                        evaluations=reserves,
                    )

                accumulated_evaluations: list[EvidenceEvaluation] = []
                pending = self._pending_candidates(session)
                if pending:
                    accumulated_evaluations.extend(
                        await self._evaluate_atomically(session, sentence, pending)
                    )
                    self._update_status_after_work(session)

                last_result: EvidenceSearchRoundResult | None = None
                while True:
                    if self._target_reached(session):
                        session.status = SearchSessionStatus.COMPLETED
                        return self._aggregate_result(
                            session,
                            last_result,
                            accumulated_evaluations,
                            default_source=RoundResultSource.PENDING_EVALUATIONS,
                        )
                    if session.status is SearchSessionStatus.FAILED:
                        return self._aggregate_result(
                            session,
                            last_result,
                            accumulated_evaluations,
                            default_source=RoundResultSource.FAILED,
                            failure_code="session_failed",
                        )
                    if session.current_round >= settings.MAX_SEARCH_ROUNDS:
                        session.status = SearchSessionStatus.EXHAUSTED
                        return self._aggregate_result(
                            session,
                            last_result,
                            accumulated_evaluations,
                            default_source=RoundResultSource.NO_ACTION,
                        )

                    previous_round = (
                        session.round_history[-1]
                        if session.current_round > 0 and session.round_history
                        else None
                    )
                    if session.current_round > 0 and previous_round is None:
                        return self._aggregate_result(
                            session,
                            last_result,
                            accumulated_evaluations,
                            default_source=RoundResultSource.PENDING_EVALUATIONS,
                            refinement_recommended=True,
                        )

                    prior_result = last_result
                    last_result = await self._execute_new_search(
                        session=session,
                        sentence=sentence,
                        citation_hints=citation_hints or [],
                        filter_criteria=filter_criteria,
                        previous_round=previous_round,
                    )
                    if (
                        prior_result is not None
                        and last_result.round_summary is None
                        and last_result.source is RoundResultSource.NO_ACTION
                    ):
                        last_result = last_result.model_copy(
                            update={
                                "round_summary": prior_result.round_summary,
                                "filter_result": prior_result.filter_result,
                            }
                        )
                    accumulated_evaluations.extend(last_result.evaluations)

                    if (
                        last_result.source
                        in {
                            RoundResultSource.FAILED,
                            RoundResultSource.NO_ACTION,
                            RoundResultSource.CITATION_RESOLUTION,
                        }
                        or self._target_reached(session)
                        or session.current_round >= settings.MAX_SEARCH_ROUNDS
                    ):
                        if self._target_reached(session):
                            session.status = SearchSessionStatus.COMPLETED
                        elif session.current_round >= settings.MAX_SEARCH_ROUNDS and (
                            session.status is not SearchSessionStatus.FAILED
                        ):
                            session.status = SearchSessionStatus.EXHAUSTED
                        return self._aggregate_result(
                            session,
                            last_result,
                            accumulated_evaluations,
                            default_source=last_result.source,
                        )
            except LLMError:
                session.status = SearchSessionStatus.FAILED
                session.touch()
                raise
            finally:
                logger.info(
                    "evidence_workflow.finished user_id=%s version_id=%s round=%s status=%s duration=%.4f",
                    user_id,
                    document_version_id,
                    session.current_round,
                    session.status.value,
                    time.perf_counter() - started_at,
                )

    async def _execute_new_search(
        self,
        *,
        session: EvidenceSearchSession,
        sentence: str,
        citation_hints: list[CitationHint],
        filter_criteria: ReferenceFilterCriteria,
        previous_round: SearchRoundSummary | None,
    ) -> EvidenceSearchRoundResult:
        """Execute one initial or refined inference and process its typed outcome."""
        session.current_round += 1
        session.touch()
        if previous_round is None:
            outcome = await self._search_agent.run_search_decision(
                sentence,
                citation_hints,
                academic_search_executor=self._academic_search_executor,
                citation_resolution_executor=self._citation_resolution_executor,
            )
        else:
            outcome = await self._search_agent.run_refined_search_decision(
                sentence=sentence,
                previous_round=previous_round,
                academic_search_executor=self._academic_search_executor,
                citation_resolution_executor=self._citation_resolution_executor,
            )

        if outcome.action_taken is SearchToolName.NONE:
            session.status = SearchSessionStatus.EXHAUSTED
            session.touch()
            return self._result(
                session,
                RoundResultSource.NO_ACTION,
                search_outcome=outcome,
            )

        if isinstance(outcome.tool_execution, CitationResolutionExecutionResult):
            failed = outcome.tool_execution.public_result.status is CitationResolutionStatus.FAILED
            if failed:
                session.status = SearchSessionStatus.FAILED
            else:
                session.status = SearchSessionStatus.EXHAUSTED
                session.touch()
            return self._result(
                session,
                RoundResultSource.FAILED if failed else RoundResultSource.CITATION_RESOLUTION,
                search_outcome=outcome,
                failure_code="citation_resolution_failed" if failed else None,
            )

        if not isinstance(outcome.tool_execution, AcademicSearchExecutionResult):
            raise ValueError("search outcome does not contain an action-compatible execution")
        return await self._process_academic_search(
            session=session,
            sentence=sentence,
            outcome=outcome,
            execution=outcome.tool_execution,
            filter_criteria=filter_criteria,
        )

    async def _process_academic_search(
        self,
        *,
        session: EvidenceSearchSession,
        sentence: str,
        outcome: SearchToolExecutionOutcome,
        execution: AcademicSearchExecutionResult,
        filter_criteria: ReferenceFilterCriteria,
    ) -> EvidenceSearchRoundResult:
        """Filter, stage and evaluate only new candidates from one academic search."""
        public = execution.public_result
        previously_recovered = set(session.recovered_candidate_keys)
        self._record_search_metadata(session, outcome, execution)
        if public.status is AcademicSearchStatus.FAILED:
            session.status = SearchSessionStatus.FAILED
            round_summary = self._round_summary(session, public, 0, 0)
            session.round_history.append(round_summary)
            session.touch()
            return self._result(
                session,
                RoundResultSource.FAILED,
                search_outcome=outcome,
                round_summary=round_summary,
                failure_code="academic_search_failed",
            )

        new_candidates = [
            candidate
            for candidate in execution.candidates
            if candidate.candidate_key not in previously_recovered
        ]
        filter_result = self._reference_filter.filter_candidates(
            new_candidates,
            filter_criteria,
        )
        for reference in filter_result.accepted:
            session.candidates[reference.candidate_key] = EvidenceSearchCandidate(
                reference=reference,
                provider=reference.provider,
                search_round=session.current_round,
            )
        self._record_filter_statistics(session, filter_result)

        pending = self._pending_candidates(session)
        evaluations = (
            await self._evaluate_atomically(session, sentence, pending)
            if pending
            else []
        )
        self._update_status_after_work(session)
        refinement = self._refinement_allowed(session)
        source = (
            RoundResultSource.REFINEMENT_RECOMMENDED
            if refinement
            else RoundResultSource.NEW_SEARCH
        )
        round_summary = self._round_summary(
            session,
            public,
            filter_result.total_accepted,
            len(evaluations),
        )
        session.round_history.append(round_summary)
        session.touch()
        return self._result(
            session,
            source,
            search_outcome=outcome,
            filter_result=filter_result,
            round_summary=round_summary,
            evaluations=evaluations,
            refinement_recommended=refinement,
        )

    async def _evaluate_atomically(
        self,
        session: EvidenceSearchSession,
        sentence: str,
        candidates: list[EvidenceSearchCandidate],
    ) -> list[EvidenceEvaluation]:
        """Evaluate batches first and mutate session state only after all succeed."""
        batch_size = min(settings.EVIDENCE_BATCH_SIZE, 5)
        collected: list[EvidenceEvaluation] = []
        for offset in range(0, len(candidates), batch_size):
            batch = candidates[offset : offset + batch_size]
            inputs = [
                EvidenceCandidateInput(
                    candidate_key=candidate.reference.candidate_key,
                    title=candidate.reference.title,
                    abstract=candidate.reference.abstract,
                )
                for candidate in batch
            ]
            evaluated = await self._evidence_evaluator.evaluate_batch(sentence, inputs)
            collected.extend(evaluated.evaluations)

        candidates_by_key = {
            candidate.reference.candidate_key: candidate for candidate in candidates
        }
        for evaluation in collected:
            candidate = candidates_by_key[evaluation.candidate_key]
            session.candidates[evaluation.candidate_key] = candidate.model_copy(
                update={
                    "evaluation_status": CandidateEvaluationStatus.EVALUATED,
                    "verdict": evaluation.verdict,
                    "confidence": evaluation.confidence,
                    "reason": evaluation.reason,
                    "analysis_scope": evaluation.analysis_scope,
                }
            )
            session.evaluated_candidate_keys.add(evaluation.candidate_key)
            if evaluation.verdict is EvidenceVerdict.STRONG_SUPPORT:
                session.strong_support_keys.add(evaluation.candidate_key)
            elif evaluation.verdict is EvidenceVerdict.PARTIAL_SUPPORT:
                session.partial_support_keys.add(evaluation.candidate_key)
        session.touch()
        return collected

    @staticmethod
    def _pending_candidates(session: EvidenceSearchSession) -> list[EvidenceSearchCandidate]:
        """Return pending candidates in stable insertion order without duplicates."""
        return [
            candidate
            for key, candidate in session.candidates.items()
            if key not in session.evaluated_candidate_keys
            and candidate.evaluation_status is CandidateEvaluationStatus.PENDING
        ]

    @staticmethod
    def _unshown_evaluations(session: EvidenceSearchSession) -> list[EvidenceEvaluation]:
        """Reconstruct evaluated reserves without marking them as presented."""
        evaluations: list[EvidenceEvaluation] = []
        for key, candidate in session.candidates.items():
            if (
                key in session.presented_candidate_keys
                or candidate.shown_to_user
                or candidate.evaluation_status is not CandidateEvaluationStatus.EVALUATED
                or key not in session.strong_support_keys | session.partial_support_keys
            ):
                continue
            if (
                candidate.verdict is None
                or candidate.confidence is None
                or not candidate.reason
                or candidate.analysis_scope is None
            ):
                raise ValueError("evaluated session candidate has incomplete evaluation data")
            evaluations.append(
                EvidenceEvaluation(
                    candidate_key=key,
                    verdict=candidate.verdict,
                    confidence=candidate.confidence,
                    reason=candidate.reason,
                    analysis_scope=candidate.analysis_scope,
                )
            )
        return evaluations

    @staticmethod
    def _record_search_metadata(
        session: EvidenceSearchSession,
        outcome: SearchToolExecutionOutcome,
        execution: AcademicSearchExecutionResult,
    ) -> None:
        """Accumulate queries and provider statistics available from typed results."""
        if outcome.tool_call and isinstance(
            outcome.tool_call.validated_arguments,
            AcademicSearchInput,
        ):
            session.queries_used.extend(outcome.tool_call.validated_arguments.queries)

        deduplicated_by_provider = Counter(
            candidate.provider for candidate in execution.candidates
        )
        session.recovered_candidate_keys.update(
            candidate.candidate_key for candidate in execution.candidates
        )
        for provider_result in execution.public_result.providers:
            statistics = session.provider_statistics.setdefault(
                provider_result.provider,
                ProviderSearchStatistics(provider=provider_result.provider),
            )
            if provider_result.success:
                statistics.successful_rounds += 1
            else:
                statistics.failed_rounds += 1
            statistics.results_found += provider_result.results_found
            statistics.after_deduplication += deduplicated_by_provider[provider_result.provider]
        session.touch()

    @staticmethod
    def _record_filter_statistics(
        session: EvidenceSearchSession,
        filter_result: ReferenceFilterResult,
    ) -> None:
        accepted_by_provider = Counter(candidate.provider for candidate in filter_result.accepted)
        for provider, count in accepted_by_provider.items():
            statistics = session.provider_statistics.setdefault(
                provider,
                ProviderSearchStatistics(provider=provider),
            )
            statistics.after_filters += count
        for reason, count in filter_result.reason_counts.items():
            reason_key = reason.value
            session.filter_rejection_counts[reason_key] = (
                session.filter_rejection_counts.get(reason_key, 0) + count
            )
        session.touch()

    @staticmethod
    def _round_summary(
        session: EvidenceSearchSession,
        public_result: AcademicSearchToolResult,
        after_filters: int,
        evaluated_candidates: int,
    ) -> SearchRoundSummary:
        """Build deterministic aggregate feedback without invoking an LLM."""
        return SearchRoundSummary(
            round_number=session.current_round,
            queries_used=list(session.queries_used),
            provider_results=[
                ProviderRoundResult(
                    provider=item.provider,
                    success=item.success,
                    results_found=item.results_found,
                    error_code=item.error_code,
                )
                for item in public_result.providers
            ],
            raw_results=public_result.raw_results,
            after_deduplication=public_result.after_deduplication,
            after_filters=after_filters,
            evaluated_candidates=evaluated_candidates,
            strong_support_count=len(session.strong_support_keys),
            partial_support_count=len(session.partial_support_keys),
            missing_strong_evidence=max(
                settings.TARGET_STRONG_EVIDENCE - len(session.strong_support_keys),
                0,
            ),
        )

    @staticmethod
    def _target_reached(session: EvidenceSearchSession) -> bool:
        return len(session.strong_support_keys) >= settings.TARGET_STRONG_EVIDENCE

    def _update_status_after_work(self, session: EvidenceSearchSession) -> None:
        """Apply lifecycle precedence after one bounded operation."""
        if self._target_reached(session):
            session.status = SearchSessionStatus.COMPLETED
        elif self._pending_candidates(session):
            session.status = SearchSessionStatus.ACTIVE
        elif session.current_round >= settings.MAX_SEARCH_ROUNDS:
            session.status = SearchSessionStatus.EXHAUSTED
        else:
            session.status = SearchSessionStatus.ACTIVE
        session.touch()

    def _refinement_allowed(self, session: EvidenceSearchSession) -> bool:
        """Report future refinement eligibility without executing another round."""
        return (
            session.status is SearchSessionStatus.ACTIVE
            and not self._target_reached(session)
            and session.current_round < settings.MAX_SEARCH_ROUNDS
            and not self._pending_candidates(session)
        )

    def _aggregate_result(
        self,
        session: EvidenceSearchSession,
        last_result: EvidenceSearchRoundResult | None,
        evaluations: list[EvidenceEvaluation],
        *,
        default_source: RoundResultSource,
        failure_code: str | None = None,
        refinement_recommended: bool = False,
    ) -> EvidenceSearchRoundResult:
        """Combine only evaluations produced during this public workflow call."""
        if last_result is None:
            return self._result(
                session,
                default_source,
                evaluations=evaluations,
                refinement_recommended=refinement_recommended,
                failure_code=failure_code,
            )
        return EvidenceSearchRoundResult(
            session_status=session.status,
            round_number=session.current_round,
            source=last_result.source,
            search_outcome=last_result.search_outcome,
            filter_result=last_result.filter_result,
            round_summary=last_result.round_summary,
            evaluation_summary=summarize_evaluations(evaluations),
            evaluations=evaluations,
            reserved_candidate_keys=tuple(item.candidate_key for item in evaluations),
            target_reached=self._target_reached(session),
            refinement_recommended=refinement_recommended,
            failure_code=failure_code or last_result.failure_code,
        )

    def _result(
        self,
        session: EvidenceSearchSession,
        source: RoundResultSource,
        *,
        search_outcome: SearchToolExecutionOutcome | None = None,
        filter_result: ReferenceFilterResult | None = None,
        round_summary: SearchRoundSummary | None = None,
        evaluations: list[EvidenceEvaluation] | None = None,
        refinement_recommended: bool = False,
        failure_code: str | None = None,
    ) -> EvidenceSearchRoundResult:
        """Construct one coherent result without changing presentation state."""
        returned_evaluations = evaluations or []
        result = EvidenceSearchRoundResult(
            session_status=session.status,
            round_number=session.current_round,
            source=source,
            search_outcome=search_outcome,
            filter_result=filter_result,
            round_summary=round_summary,
            evaluation_summary=summarize_evaluations(returned_evaluations),
            evaluations=returned_evaluations,
            reserved_candidate_keys=tuple(
                evaluation.candidate_key for evaluation in returned_evaluations
            ),
            target_reached=self._target_reached(session),
            refinement_recommended=refinement_recommended,
            failure_code=failure_code,
        )
        logger.info(
            "evidence_workflow.result round=%s source=%s evaluated=%s strong=%s partial=%s status=%s",
            result.round_number,
            result.source.value,
            result.evaluation_summary.evaluated_candidates,
            len(session.strong_support_keys),
            len(session.partial_support_keys),
            result.session_status.value,
        )
        return result
