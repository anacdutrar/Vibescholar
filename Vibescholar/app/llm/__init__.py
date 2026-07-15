"""Local language-model client contracts for VibeScholar."""

from app.llm.exceptions import (
    LLMConnectionError,
    LLMError,
    LLMResponseValidationError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.ollama_client import LLMChatResponse, OllamaClient

__all__ = [
    "LLMChatResponse",
    "LLMConnectionError",
    "LLMError",
    "LLMResponseValidationError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "OllamaClient",
]
