"""Conservative, bounded semantic evaluation of filtered reference candidates.

The future pipeline is expected to run providers, deduplication and the
ReferenceFilterService before creating batches of at most five candidates for
this evaluator. Evaluation never approves or persists evidence.
"""

import json
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.agents.schemas import (
    EvidenceAnalysisScope,
    EvidenceCandidateInput,
    EvidenceEvaluation,
    EvidenceEvaluationBatch,
)
from app.core.logging import logger
from app.llm.exceptions import LLMError, LLMResponseValidationError, LLMUnavailableError


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class StructuredChatClient(Protocol):
    """Minimal structured-output operation required from an LLM backend."""

    async def structured_chat(
        self,
        messages: Sequence[dict[str, object]],
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        """Return one response validated as the requested Pydantic model."""
        ...


class EvidenceEvaluator:
    """Evaluate each candidate independently against one academic sentence."""

    MAX_BATCH_SIZE = 5

    def __init__(
        self,
        client: StructuredChatClient,
        prompt_path: Path | None = None,
    ) -> None:
        self._client = client
        self._prompt_path = prompt_path or (
            Path(__file__).resolve().parents[2] / "prompts" / "evidence_evaluator_system.txt"
        )
        self._system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load the evaluator role once as UTF-8 without embedding it in Python."""
        try:
            prompt = self._prompt_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise LLMUnavailableError("The evidence evaluator system prompt is unavailable.") from exc
        if not prompt:
            raise LLMUnavailableError("The evidence evaluator system prompt is empty.")
        return prompt

    @staticmethod
    def _validate_inputs(
        sentence: str,
        candidates: list[EvidenceCandidateInput],
    ) -> tuple[str, list[EvidenceCandidateInput]]:
        """Validate one sentence and one caller-owned bounded batch."""
        if not isinstance(sentence, str) or not sentence.strip():
            raise ValueError("sentence must contain non-whitespace text")
        if not 1 <= len(candidates) <= EvidenceEvaluator.MAX_BATCH_SIZE:
            raise ValueError("evidence evaluation requires between one and five candidates")

        try:
            validated = [EvidenceCandidateInput.model_validate(item) for item in candidates]
        except ValidationError as exc:
            raise ValueError("evidence candidates do not satisfy the input contract") from exc
        candidate_keys = [candidate.candidate_key for candidate in validated]
        if len(set(candidate_keys)) != len(candidate_keys):
            raise ValueError("candidate_keys must be unique within one evaluation batch")
        return sentence, validated

    def _build_messages(
        self,
        sentence: str,
        candidates: list[EvidenceCandidateInput],
    ) -> list[dict[str, object]]:
        """Keep untrusted sentence and candidate metadata isolated as user JSON data."""
        payload = json.dumps(
            {
                "untrusted_academic_data": {
                    "sentence": sentence,
                    "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
                }
            },
            ensure_ascii=False,
        )
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": payload},
        ]

    @staticmethod
    def _validate_response(
        response: EvidenceEvaluationBatch,
        candidates: list[EvidenceCandidateInput],
    ) -> EvidenceEvaluationBatch:
        """Reject altered identities, missing evaluations and incompatible scopes."""
        expected_keys = [candidate.candidate_key for candidate in candidates]
        evaluations_by_key: dict[str, EvidenceEvaluation] = {}
        for evaluation in response.evaluations:
            if evaluation.candidate_key in evaluations_by_key:
                raise LLMResponseValidationError(
                    "The evaluator returned a duplicate candidate_key."
                )
            evaluations_by_key[evaluation.candidate_key] = evaluation

        actual_keys = set(evaluations_by_key)
        expected_key_set = set(expected_keys)
        if actual_keys != expected_key_set:
            raise LLMResponseValidationError(
                "The evaluator response contains missing, altered, or unknown candidate_keys."
            )

        ordered_evaluations: list[EvidenceEvaluation] = []
        for candidate in candidates:
            evaluation = evaluations_by_key[candidate.candidate_key]
            expected_scope = (
                EvidenceAnalysisScope.TITLE_AND_ABSTRACT
                if candidate.abstract is not None
                else EvidenceAnalysisScope.TITLE_ONLY
            )
            if evaluation.analysis_scope is not expected_scope:
                raise LLMResponseValidationError(
                    "The evaluator response uses an analysis scope incompatible with its input."
                )
            ordered_evaluations.append(evaluation)
        return EvidenceEvaluationBatch(evaluations=ordered_evaluations)

    async def evaluate_batch(
        self,
        sentence: str,
        candidates: list[EvidenceCandidateInput],
    ) -> EvidenceEvaluationBatch:
        """Run exactly one structured inference for one batch of up to five candidates."""
        validated_sentence, validated_candidates = self._validate_inputs(sentence, candidates)
        messages = self._build_messages(validated_sentence, validated_candidates)
        started_at = time.perf_counter()
        backend = type(self._client).__name__
        try:
            response = await self._client.structured_chat(messages, EvidenceEvaluationBatch)
            if not isinstance(response, EvidenceEvaluationBatch):
                raise LLMResponseValidationError(
                    "The LLM backend did not return an EvidenceEvaluationBatch."
                )
            validated_response = self._validate_response(response, validated_candidates)
        except ValidationError as exc:
            raise LLMResponseValidationError(
                "The evaluator response does not satisfy EvidenceEvaluationBatch."
            ) from exc
        except LLMError:
            logger.warning(
                "evidence_evaluator.failed backend=%s candidate_count=%s duration=%.4f",
                backend,
                len(validated_candidates),
                time.perf_counter() - started_at,
            )
            raise

        verdict_counts = Counter(
            evaluation.verdict.value for evaluation in validated_response.evaluations
        )
        logger.info(
            "evidence_evaluator.completed backend=%s candidate_count=%s duration=%.4f verdicts=%s",
            backend,
            len(validated_candidates),
            time.perf_counter() - started_at,
            dict(verdict_counts),
        )
        return validated_response
