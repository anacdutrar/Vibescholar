"""Structured-output client for the explicitly selected OpenRouter evaluator backend."""

import json
import time
from collections.abc import Sequence
from typing import TypeVar

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, settings
from app.core.logging import configure_llm_diagnostic_logging, llm_logger
from app.llm.exceptions import (
    LLMConfigurationError,
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMResponseValidationError,
    LLMTimeoutError,
    LLMUnavailableError,
)


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


def validate_openrouter_configuration(config: Settings) -> None:
    """Reject unsafe evaluator configuration before constructing the SDK client."""
    api_key = config.OPENROUTER_API_KEY.strip()
    model = config.OPENROUTER_MODEL.strip()
    allowed_models = {
        allowed.strip().casefold()
        for allowed in config.OPENROUTER_ALLOWED_MODELS
        if allowed.strip()
    }
    if not api_key:
        raise LLMConfigurationError(
            "OPENROUTER_API_KEY is required when the evidence evaluator uses OpenRouter."
        )
    if not model:
        raise LLMConfigurationError(
            "OPENROUTER_MODEL is required when the evidence evaluator uses OpenRouter."
        )
    if model.casefold() not in allowed_models:
        raise LLMConfigurationError(
            "OPENROUTER_MODEL must be included in OPENROUTER_ALLOWED_MODELS."
        )
    if not config.OPENROUTER_ALLOW_PAID_MODELS and not model.casefold().endswith(":free"):
        raise LLMConfigurationError(
            "Paid OpenRouter models are disabled by OPENROUTER_ALLOW_PAID_MODELS."
        )


class OpenRouterClient:
    """Perform one validated structured evaluator request through OpenRouter."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        *,
        config: Settings = settings,
    ) -> None:
        validate_openrouter_configuration(config)
        self._config = config
        self._model = config.OPENROUTER_MODEL.strip()
        self._timeout = config.LLM_TIMEOUT_SECONDS
        self._base_url = self._normalized_base_url(config.OPENROUTER_BASE_URL)
        self._max_output_tokens = config.EVIDENCE_EVALUATOR_MAX_OUTPUT_TOKENS
        api_key = config.OPENROUTER_API_KEY.strip()
        configure_llm_diagnostic_logging(config.LLM_DIAGNOSTIC_LOGGING)
        self._client = client or AsyncOpenAI(
            base_url=self._base_url,
            api_key=api_key,
            timeout=self._timeout,
            max_retries=0,
        )

    def __repr__(self) -> str:
        """Return safe diagnostics without credentials."""
        return (
            "OpenRouterClient("
            f"base_url={self._base_url!r}, model={self._model!r}, api_key=<redacted>)"
        )

    @staticmethod
    def _normalized_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise LLMConfigurationError("OPENROUTER_BASE_URL must not be empty.")
        return f"{normalized}/"

    def _request_arguments(
        self,
        messages: Sequence[dict[str, object]],
        response_model: type[BaseModel],
    ) -> dict:
        """Build one strict JSON Schema request from centralized settings."""
        arguments = {
            "model": self._model,
            "messages": messages,
            "temperature": self._config.LLM_TEMPERATURE,
            "top_p": self._config.LLM_TOP_P,
            "frequency_penalty": self._config.LLM_FREQUENCY_PENALTY,
            "presence_penalty": self._config.LLM_PRESENCE_PENALTY,
            "max_tokens": self._max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            },
            # OpenRouter must route only to a provider that supports every
            # requested parameter, including strict structured output.
            "extra_body": {"provider": {"require_parameters": True}},
        }
        if self._config.LLM_SEED is not None:
            arguments["seed"] = self._config.LLM_SEED
        return arguments

    @staticmethod
    def _serialized_size(value: object) -> int:
        """Measure transport characters without logging or retaining content."""
        if isinstance(value, str):
            return len(value)
        if value is None:
            return 0
        try:
            return len(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
            )
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _request_metrics(
        cls,
        messages: Sequence[dict[str, object]],
        response_format: dict,
    ) -> dict[str, int]:
        system_characters = 0
        user_characters = 0
        total_characters = 0
        for message in messages:
            characters = cls._serialized_size(message.get("content"))
            total_characters += characters
            if message.get("role") == "system":
                system_characters += characters
            elif message.get("role") == "user":
                user_characters += characters
        schema = response_format["json_schema"]["schema"]
        return {
            "messages": len(messages),
            "characters_total": total_characters,
            "system_characters": system_characters,
            "user_characters": user_characters,
            "schema_characters": cls._serialized_size(schema),
        }

    def _log_request(self, arguments: dict) -> dict[str, int]:
        metrics = self._request_metrics(
            arguments["messages"],
            arguments["response_format"],
        )
        llm_logger.debug(
            "ai.pipeline.llm.request component=EvidenceEvaluator backend=OpenRouterClient "
            "operation=structured_chat model=%s timeout=%s temperature=%s top_p=%s "
            "frequency_penalty=%s presence_penalty=%s seed=%s max_output_tokens=%s "
            "tools=0 structured_output=true messages=%s characters_total=%s "
            "system_characters=%s user_characters=%s schema_characters=%s",
            arguments["model"],
            self._timeout,
            arguments["temperature"],
            arguments["top_p"],
            arguments["frequency_penalty"],
            arguments["presence_penalty"],
            arguments.get("seed", "disabled"),
            arguments["max_tokens"],
            metrics["messages"],
            metrics["characters_total"],
            metrics["system_characters"],
            metrics["user_characters"],
            metrics["schema_characters"],
        )
        return metrics

    @staticmethod
    def _log_response(completion, *, duration: float, metrics: dict[str, int]) -> None:
        choice = completion.choices[0]
        usage = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        usage_available = all(
            isinstance(value, int)
            for value in (prompt_tokens, completion_tokens, total_tokens)
        )
        llm_logger.debug(
            "ai.pipeline.llm.response component=EvidenceEvaluator backend=OpenRouterClient "
            "operation=structured_chat duration=%.4f finish_reason=%s tool_calls=0 "
            "structured_output=true usage_available=%s prompt_tokens=%s "
            "completion_tokens=%s total_tokens=%s messages=%s characters_total=%s "
            "system_characters=%s user_characters=%s schema_characters=%s",
            duration,
            choice.finish_reason or "unknown",
            usage_available,
            prompt_tokens if usage_available else "unavailable",
            completion_tokens if usage_available else "unavailable",
            total_tokens if usage_available else "unavailable",
            metrics["messages"],
            metrics["characters_total"],
            metrics["system_characters"],
            metrics["user_characters"],
            metrics["schema_characters"],
        )

    def _log_failure(self, arguments: dict, *, duration: float, exc: Exception) -> None:
        llm_logger.debug(
            "ai.pipeline.llm.response component=EvidenceEvaluator backend=OpenRouterClient "
            "operation=structured_chat status=failed duration=%.4f error_type=%s "
            "model=%s timeout=%s temperature=%s top_p=%s frequency_penalty=%s "
            "presence_penalty=%s seed=%s max_output_tokens=%s",
            duration,
            type(exc).__name__,
            arguments["model"],
            self._timeout,
            arguments["temperature"],
            arguments["top_p"],
            arguments["frequency_penalty"],
            arguments["presence_penalty"],
            arguments.get("seed", "disabled"),
            arguments["max_tokens"],
        )

    @staticmethod
    def _raise_mapped_error(exc: Exception) -> None:
        if isinstance(exc, APITimeoutError):
            raise LLMTimeoutError("The OpenRouter request exceeded the configured timeout.") from exc
        if isinstance(exc, APIConnectionError):
            raise LLMConnectionError("The configured OpenRouter service could not be reached.") from exc
        if isinstance(exc, APIResponseValidationError):
            raise LLMResponseValidationError(
                "OpenRouter returned an invalid protocol response."
            ) from exc
        if isinstance(exc, APIStatusError):
            status = exc.status_code
            if status in {401, 402, 403}:
                raise LLMConfigurationError(
                    "OpenRouter rejected the configured credentials or account configuration."
                ) from exc
            if status in {408, 504}:
                raise LLMTimeoutError("The OpenRouter request timed out.") from exc
            if status == 429:
                raise LLMRateLimitError("OpenRouter rate limit reached.") from exc
            if status == 404:
                raise LLMUnavailableError(
                    "The configured OpenRouter model is unavailable."
                ) from exc
            if status in {400, 412, 422}:
                raise LLMConfigurationError(
                    "The configured OpenRouter model does not accept the required structured request."
                ) from exc
            if status >= 500:
                raise LLMUnavailableError("The OpenRouter service is unavailable.") from exc
            raise LLMError(f"The OpenRouter request failed with HTTP status {status}.") from exc
        raise LLMError("The OpenRouter request failed unexpectedly.") from exc

    async def structured_chat(
        self,
        messages: Sequence[dict[str, object]],
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        """Return one strict Pydantic response using exactly one SDK request."""
        arguments = self._request_arguments(messages, response_model)
        metrics = self._log_request(arguments)
        started_at = time.perf_counter()
        try:
            completion = await self._client.chat.completions.create(**arguments)
        except Exception as exc:
            self._log_failure(
                arguments,
                duration=time.perf_counter() - started_at,
                exc=exc,
            )
            self._raise_mapped_error(exc)

        try:
            choice = completion.choices[0]
            content = choice.message.content
            if not isinstance(content, str) or not content:
                raise ValueError("structured content is missing")
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise LLMResponseValidationError(
                "OpenRouter returned an incomplete structured response."
            ) from exc

        self._log_response(
            completion,
            duration=time.perf_counter() - started_at,
            metrics=metrics,
        )
        try:
            return response_model.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            raise LLMResponseValidationError(
                f"OpenRouter response does not satisfy {response_model.__name__}."
            ) from exc
