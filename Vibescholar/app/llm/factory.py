"""Specific composition factory for the EvidenceEvaluator LLM backend."""

from app.core.config import Settings, settings
from app.llm.exceptions import LLMConfigurationError
from app.llm.ollama_client import LLMComponent, OllamaClient
from app.llm.openrouter_client import (
    OpenRouterClient,
    validate_openrouter_configuration,
)
from app.llm.protocols import StructuredChatClient


def create_evidence_evaluator_client(
    config: Settings = settings,
) -> StructuredChatClient:
    """Construct only the explicitly selected EvidenceEvaluator client."""
    backend = config.EVIDENCE_EVALUATOR_BACKEND.strip().casefold()
    if backend == "ollama":
        return OllamaClient(component=LLMComponent.EVIDENCE_EVALUATOR)
    if backend == "openrouter":
        validate_openrouter_configuration(config)
        return OpenRouterClient(config=config)
    raise LLMConfigurationError(
        "EVIDENCE_EVALUATOR_BACKEND must be 'ollama' or 'openrouter'."
    )
