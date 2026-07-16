"""Opt-in, single-request smoke test for the configured OpenRouter evaluator."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from app.agents.schemas import (
    EvidenceAnalysisScope,
    EvidenceEvaluationBatch,
    EvidenceVerdict,
)
from app.agents.search_agent import SearchAgent
from app.core.config import Settings
from app.core.logging import configure_llm_diagnostic_logging
from app.llm.exceptions import LLMConfigurationError, LLMError
from app.llm.ollama_client import LLMComponent, OllamaClient
from app.llm.openrouter_client import (
    OpenRouterClient,
    validate_openrouter_configuration,
)


logger = logging.getLogger("vibescholar.openrouter_smoke")
EXPECTED_MODEL = "tencent/hy3:free"
TEST_CANDIDATE_KEY = "smoke-test-candidate"


def _opt_in_enabled() -> bool:
    """Require an explicit environment opt-in before any client construction."""
    return os.getenv("RUN_OPENROUTER_SMOKE_TEST", "").strip().casefold() == "true"


def _validate_local_settings(config: Settings) -> None:
    """Apply all local safety checks before the only permitted inference."""
    if config.EVIDENCE_EVALUATOR_BACKEND != "openrouter":
        raise LLMConfigurationError(
            "EVIDENCE_EVALUATOR_BACKEND must be openrouter for this smoke test."
        )
    if config.OPENROUTER_MODEL.strip().casefold() != EXPECTED_MODEL:
        raise LLMConfigurationError(
            f"OPENROUTER_MODEL must be exactly {EXPECTED_MODEL} for this smoke test."
        )
    validate_openrouter_configuration(config)


def _build_messages() -> list[dict[str, object]]:
    """Build a small non-sensitive evaluator request without persisting test data."""
    prompt_path = (
        Path(__file__).resolve().parents[2]
        / "prompts"
        / "evidence_evaluator_system.txt"
    )
    system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    payload = {
        "untrusted_academic_data": {
            "sentence": (
                "Convolutional neural networks can be used for object detection."
            ),
            "candidates": [
                {
                    "candidate_key": TEST_CANDIDATE_KEY,
                    "title": "Convolutional Neural Networks for Object Detection",
                    "abstract": (
                        "The study applies convolutional neural networks directly "
                        "to detecting objects in images."
                    ),
                }
            ],
        }
    }
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]


def _validate_smoke_response(response: EvidenceEvaluationBatch) -> None:
    """Validate the exact smoke-test identity and bounded structured verdict."""
    if len(response.evaluations) != 1:
        raise LLMConfigurationError(
            "The smoke-test response must contain exactly one evaluation."
        )
    evaluation = response.evaluations[0]
    if evaluation.candidate_key != TEST_CANDIDATE_KEY:
        raise LLMConfigurationError(
            "The smoke-test response did not preserve candidate_key."
        )
    if not isinstance(evaluation.verdict, EvidenceVerdict):
        raise LLMConfigurationError("The smoke-test verdict is invalid.")
    if not 0.0 <= evaluation.confidence <= 1.0:
        raise LLMConfigurationError("The smoke-test confidence is invalid.")
    if evaluation.analysis_scope is not EvidenceAnalysisScope.TITLE_AND_ABSTRACT:
        raise LLMConfigurationError("The smoke-test analysis_scope is invalid.")


async def run_smoke_test() -> int:
    """Run zero or exactly one OpenRouter inference after local validation."""
    if not _opt_in_enabled():
        logger.info(
            "openrouter.smoke.skipped reason=opt_in_disabled network_calls=0"
        )
        return 2

    try:
        config = Settings()
        _validate_local_settings(config)
        search_client = OllamaClient(component=LLMComponent.SEARCH_AGENT)
        SearchAgent(search_client)
        client = OpenRouterClient(config=config)
    except (LLMError, ValueError, OSError) as exc:
        logger.error(
            "openrouter.smoke.local_validation_failed error_type=%s network_calls=0",
            type(exc).__name__,
        )
        return 2

    configure_llm_diagnostic_logging(True)
    logger.info(
        "openrouter.smoke.local_validation_succeeded backend=OpenRouterClient "
        "model=%s api_key_present=true allowed=true paid_models=false "
        "free_slug=true search_agent_backend=OllamaClient",
        config.OPENROUTER_MODEL,
    )
    logger.info(
        "openrouter.smoke.metadata_skipped reason=models_api_not_implemented"
    )

    started_at = time.perf_counter()
    try:
        response = await client.structured_chat(
            _build_messages(),
            EvidenceEvaluationBatch,
        )
        _validate_smoke_response(response)
    except (LLMError, LLMConfigurationError, OSError, UnicodeError) as exc:
        logger.error(
            "openrouter.smoke.failed model=%s duration=%.4f "
            "error_type=%s network_calls=1 validation=false",
            config.OPENROUTER_MODEL,
            time.perf_counter() - started_at,
            type(exc).__name__,
        )
        return 1

    evaluation = response.evaluations[0]
    logger.info(
        "openrouter.smoke.succeeded model=%s backend=OpenRouterClient "
        "duration=%.4f structured_output=true verdict=%s "
        "validation=true network_calls=1 fallback=false retry=false",
        config.OPENROUTER_MODEL,
        time.perf_counter() - started_at,
        evaluation.verdict.value,
    )
    return 0


def main() -> int:
    """CLI entry point."""
    return asyncio.run(run_smoke_test())


if __name__ == "__main__":
    raise SystemExit(main())
