"""Async OpenAI-compatible client isolated to a local Ollama service."""

from dataclasses import dataclass
from enum import Enum
import json
import time
from typing import Sequence, TypeVar

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolParam,
)
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import configure_llm_diagnostic_logging, llm_logger
from app.llm.exceptions import (
    LLMConnectionError,
    LLMError,
    LLMResponseValidationError,
    LLMTimeoutError,
    LLMUnavailableError,
)


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class LLMComponent(str, Enum):
    """Explicit application component responsible for an LLM inference."""

    SEARCH_AGENT = "SearchAgent"
    EVIDENCE_EVALUATOR = "EvidenceEvaluator"
    UNSPECIFIED = "Unspecified"


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """Minimal transport-neutral representation of one SDK function call."""

    tool_call_id: str
    tool_name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class LLMChatResponse:
    """Minimal transport-neutral representation of one chat completion."""

    content: str | None
    model: str
    finish_reason: str | None
    tool_calls: tuple[LLMToolCall, ...] = ()


class OllamaClient:
    """Encapsulate one-request Ollama chat operations through the OpenAI SDK."""

    _CONTEXT_CONFIGURATION = "backend_default"

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        *,
        component: LLMComponent = LLMComponent.UNSPECIFIED,
    ) -> None:
        self._model = settings.OLLAMA_MODEL
        self._timeout = settings.LLM_TIMEOUT_SECONDS
        self._base_url = self._openai_base_url(settings.OLLAMA_BASE_URL)
        self._component = LLMComponent(component)
        configure_llm_diagnostic_logging(settings.LLM_DIAGNOSTIC_LOGGING)
        self._client = client or AsyncOpenAI(
            base_url=self._base_url,
            api_key=settings.OLLAMA_API_KEY or "ollama",
            timeout=self._timeout,
            max_retries=0,
        )
        self._log_operational_parameters("initialized")

    def __repr__(self) -> str:
        """Return diagnostics without exposing configured credentials."""
        return (
            "OllamaClient("
            f"base_url={self._base_url!r}, model={self._model!r}, "
            f"component={self._component.value!r}, api_key=<redacted>)"
        )

    @staticmethod
    def _openai_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("OLLAMA_BASE_URL must not be empty")
        if not normalized.casefold().endswith("/v1"):
            normalized = f"{normalized}/v1"
        return f"{normalized}/"

    @staticmethod
    def _safe_error_text(exc: APIStatusError) -> str:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, str):
                return error.casefold()
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str):
                    return message.casefold()
        return ""

    def _is_model_unavailable(self, exc: APIStatusError) -> bool:
        error_text = self._safe_error_text(exc)
        markers = ("model", "not found", "not available", "pull", "load")
        return (
            exc.status_code in {400, 404}
            and "model" in error_text
            and any(marker in error_text for marker in markers[1:])
        )

    def _chat_request_arguments(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        *,
        tools: Sequence[ChatCompletionToolParam] | None = None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None = None,
        response_format: dict | None = None,
    ) -> dict:
        """Build one OpenAI-compatible request from centralized inference settings."""
        arguments = {
            "model": self._model,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE,
            "top_p": settings.LLM_TOP_P,
            "frequency_penalty": settings.LLM_FREQUENCY_PENALTY,
            "presence_penalty": settings.LLM_PRESENCE_PENALTY,
        }
        if settings.LLM_SEED is not None:
            arguments["seed"] = settings.LLM_SEED
        if tools is not None:
            arguments["tools"] = tools
        if tool_choice is not None:
            arguments["tool_choice"] = tool_choice
        if response_format is not None:
            arguments["response_format"] = response_format
        return arguments

    def _log_operational_parameters(
        self,
        event: str,
        request_arguments: dict | None = None,
    ) -> None:
        """Log only non-sensitive effective inference controls at DEBUG level."""
        arguments = request_arguments or {}
        llm_logger.debug(
            "llm.ollama.%s model=%s timeout_seconds=%s temperature=%s top_p=%s "
            "frequency_penalty=%s presence_penalty=%s seed=%s context_configured=%s",
            event,
            arguments.get("model", self._model),
            self._timeout,
            arguments.get("temperature", settings.LLM_TEMPERATURE),
            arguments.get("top_p", settings.LLM_TOP_P),
            arguments.get("frequency_penalty", settings.LLM_FREQUENCY_PENALTY),
            arguments.get("presence_penalty", settings.LLM_PRESENCE_PENALTY),
            arguments.get("seed", "disabled"),
            self._CONTEXT_CONFIGURATION,
        )

    @staticmethod
    def _content_character_count(value: object) -> int:
        """Count the transport representation without retaining or logging content."""
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
    def _request_size_metrics(
        cls,
        messages: Sequence[ChatCompletionMessageParam],
        *,
        tools: Sequence[ChatCompletionToolParam] | None = None,
        response_format: dict | None = None,
    ) -> dict[str, int]:
        """Return approximate message sizes without exposing their contents."""
        system_characters = 0
        user_characters = 0
        total_characters = 0
        for message in messages:
            content_characters = cls._content_character_count(message.get("content"))
            total_characters += content_characters
            if message.get("role") == "system":
                system_characters += content_characters
            elif message.get("role") == "user":
                user_characters += content_characters
        schema = None
        if isinstance(response_format, dict):
            json_schema = response_format.get("json_schema")
            if isinstance(json_schema, dict):
                schema = json_schema.get("schema")
        return {
            "message_count": len(messages),
            "characters_total": total_characters,
            "system_characters": system_characters,
            "user_characters": user_characters,
            "tool_count": len(tools or ()),
            "schema_characters": cls._content_character_count(schema),
        }

    def _log_request(
        self,
        request_arguments: dict,
        *,
        operation: str,
        structured_output: bool,
    ) -> dict[str, int]:
        """Log effective request controls and return safe size metrics."""
        messages = request_arguments["messages"]
        metrics = self._request_size_metrics(
            messages,
            tools=request_arguments.get("tools"),
            response_format=request_arguments.get("response_format"),
        )
        tool_choice = request_arguments.get("tool_choice")
        safe_tool_choice = tool_choice if isinstance(tool_choice, str) else (
            "configured" if tool_choice is not None else "none"
        )
        llm_logger.debug(
            "ai.pipeline.llm.request component=%s backend=%s operation=%s "
            "model=%s timeout=%s "
            "temperature=%s top_p=%s frequency_penalty=%s presence_penalty=%s "
            "seed=%s tool_choice=%s tools=%s structured_output=%s messages=%s "
            "characters_total=%s system_characters=%s user_characters=%s "
            "schema_characters=%s context_configured=%s",
            self._component.value,
            type(self).__name__,
            operation,
            request_arguments["model"],
            self._timeout,
            request_arguments["temperature"],
            request_arguments["top_p"],
            request_arguments["frequency_penalty"],
            request_arguments["presence_penalty"],
            request_arguments.get("seed", "disabled"),
            safe_tool_choice,
            len(request_arguments.get("tools") or []),
            structured_output,
            metrics["message_count"],
            metrics["characters_total"],
            metrics["system_characters"],
            metrics["user_characters"],
            metrics["schema_characters"],
            self._CONTEXT_CONFIGURATION,
        )
        return metrics

    def _log_response(
        self,
        completion,
        response: LLMChatResponse,
        *,
        operation: str,
        structured_output: bool,
        duration: float,
        request_metrics: dict[str, int],
    ) -> None:
        """Log response metadata and token usage without model-generated content."""
        usage = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        usage_available = all(
            isinstance(value, int)
            for value in (prompt_tokens, completion_tokens, total_tokens)
        )
        llm_logger.debug(
            "ai.pipeline.llm.response component=%s backend=%s operation=%s duration=%.4f "
            "finish_reason=%s tool_calls_present=%s tool_calls=%s "
            "structured_output=%s usage_available=%s prompt_tokens=%s "
            "completion_tokens=%s total_tokens=%s messages=%s "
            "characters_total=%s system_characters=%s user_characters=%s "
            "schema_characters=%s",
            self._component.value,
            type(self).__name__,
            operation,
            duration,
            response.finish_reason or "unknown",
            bool(response.tool_calls),
            len(response.tool_calls),
            structured_output,
            usage_available,
            prompt_tokens if usage_available else "unavailable",
            completion_tokens if usage_available else "unavailable",
            total_tokens if usage_available else "unavailable",
            request_metrics["message_count"],
            request_metrics["characters_total"],
            request_metrics["system_characters"],
            request_metrics["user_characters"],
            request_metrics["schema_characters"],
        )

    def _log_failure(
        self,
        request_arguments: dict,
        *,
        operation: str,
        structured_output: bool,
        duration: float,
        exc: Exception,
    ) -> None:
        """Log a failed request using only safe operational metadata."""
        llm_logger.debug(
            "ai.pipeline.llm.response component=%s backend=%s operation=%s "
            "status=failed duration=%.4f error_type=%s structured_output=%s "
            "model=%s timeout=%s temperature=%s top_p=%s "
            "frequency_penalty=%s presence_penalty=%s seed=%s",
            self._component.value,
            type(self).__name__,
            operation,
            duration,
            type(exc).__name__,
            structured_output,
            request_arguments["model"],
            self._timeout,
            request_arguments["temperature"],
            request_arguments["top_p"],
            request_arguments["frequency_penalty"],
            request_arguments["presence_penalty"],
            request_arguments.get("seed", "unset"),
        )

    def _raise_mapped_error(self, exc: Exception) -> None:
        if isinstance(exc, APITimeoutError):
            raise LLMTimeoutError("The Ollama request exceeded the configured timeout.") from exc
        if isinstance(exc, APIConnectionError):
            raise LLMConnectionError("The configured Ollama service could not be reached.") from exc
        if isinstance(exc, APIResponseValidationError):
            raise LLMResponseValidationError("Ollama returned an invalid protocol response.") from exc
        if isinstance(exc, APIStatusError):
            if self._is_model_unavailable(exc):
                raise LLMUnavailableError("The configured Ollama model is unavailable.") from exc
            if exc.status_code >= 500:
                raise LLMUnavailableError("The Ollama service is currently unavailable.") from exc
            raise LLMError(f"The Ollama request failed with HTTP status {exc.status_code}.") from exc
        raise LLMError("The Ollama request failed unexpectedly.") from exc

    @staticmethod
    def _extract_response(completion) -> LLMChatResponse:
        try:
            choice = completion.choices[0]
            content = choice.message.content
            sdk_tool_calls = getattr(choice.message, "tool_calls", None) or []
            tool_calls: list[LLMToolCall] = []
            for tool_call in sdk_tool_calls:
                if getattr(tool_call, "type", None) != "function":
                    raise ValueError("unsupported tool-call type")
                function = tool_call.function
                if not all(
                    isinstance(value, str) and value
                    for value in (tool_call.id, function.name, function.arguments)
                ):
                    raise ValueError("incomplete function tool call")
                tool_calls.append(
                    LLMToolCall(
                        tool_call_id=tool_call.id,
                        tool_name=function.name,
                        arguments_json=function.arguments,
                    )
                )
            if content is not None and not isinstance(content, str):
                raise ValueError("chat content has an unsupported type")
            if content is None and not tool_calls:
                raise ValueError("chat content and tool calls are missing")
            return LLMChatResponse(
                content=content,
                model=str(completion.model),
                finish_reason=choice.finish_reason,
                tool_calls=tuple(tool_calls),
            )
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise LLMResponseValidationError("Ollama returned an incomplete chat response.") from exc

    async def chat(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        tools: Sequence[ChatCompletionToolParam] | None = None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None = None,
    ) -> LLMChatResponse:
        """Send exactly one chat request and return a minimal typed response."""
        request_arguments = self._chat_request_arguments(
            messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        self._log_operational_parameters("inference", request_arguments)
        request_metrics = self._log_request(
            request_arguments,
            operation="chat",
            structured_output=False,
        )
        started_at = time.perf_counter()
        try:
            completion = await self._client.chat.completions.create(**request_arguments)
        except Exception as exc:
            self._log_failure(
                request_arguments,
                operation="chat",
                structured_output=False,
                duration=time.perf_counter() - started_at,
                exc=exc,
            )
            self._raise_mapped_error(exc)
        response = self._extract_response(completion)
        self._log_response(
            completion,
            response,
            operation="chat",
            structured_output=False,
            duration=time.perf_counter() - started_at,
            request_metrics=request_metrics,
        )
        return response

    async def structured_chat(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        """Request JSON Schema output and validate it exclusively with Pydantic."""
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": response_model.model_json_schema(),
            },
        }
        request_arguments = self._chat_request_arguments(
            messages,
            response_format=response_format,
        )
        self._log_operational_parameters("structured_inference", request_arguments)
        request_metrics = self._log_request(
            request_arguments,
            operation="structured_chat",
            structured_output=True,
        )
        started_at = time.perf_counter()
        try:
            completion = await self._client.chat.completions.create(
                **request_arguments
            )
        except Exception as exc:
            self._log_failure(
                request_arguments,
                operation="structured_chat",
                structured_output=True,
                duration=time.perf_counter() - started_at,
                exc=exc,
            )
            self._raise_mapped_error(exc)

        raw_response = self._extract_response(completion)
        self._log_response(
            completion,
            raw_response,
            operation="structured_chat",
            structured_output=True,
            duration=time.perf_counter() - started_at,
            request_metrics=request_metrics,
        )
        try:
            return response_model.model_validate_json(raw_response.content)
        except (ValidationError, ValueError) as exc:
            raise LLMResponseValidationError(
                f"Ollama response does not satisfy {response_model.__name__}."
            ) from exc

    async def health(self, strict: bool = False) -> bool:
        """Check service and configured-model availability without generating text."""
        try:
            models = await self._client.models.list()
        except Exception as exc:
            try:
                self._raise_mapped_error(exc)
            except LLMError:
                if strict:
                    raise
                return False

        available = {
            str(model.id).strip().casefold()
            for model in getattr(models, "data", [])
            if getattr(model, "id", None)
        }
        model_available = self._model.strip().casefold() in available
        if not model_available and strict:
            raise LLMUnavailableError("The configured Ollama model is unavailable.")
        return model_available
