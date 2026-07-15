"""Async OpenAI-compatible client isolated to a local Ollama service."""

from dataclasses import dataclass
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
from app.llm.exceptions import (
    LLMConnectionError,
    LLMError,
    LLMResponseValidationError,
    LLMTimeoutError,
    LLMUnavailableError,
)


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


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

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._model = settings.OLLAMA_MODEL
        self._timeout = settings.LLM_TIMEOUT_SECONDS
        self._base_url = self._openai_base_url(settings.OLLAMA_BASE_URL)
        self._client = client or AsyncOpenAI(
            base_url=self._base_url,
            api_key=settings.OLLAMA_API_KEY or None,
            timeout=self._timeout,
            max_retries=0,
            _enforce_credentials=bool(settings.OLLAMA_API_KEY),
        )

    def __repr__(self) -> str:
        """Return diagnostics without exposing configured credentials."""
        return f"OllamaClient(base_url={self._base_url!r}, model={self._model!r}, api_key=<redacted>)"

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
        request_arguments = {
            "model": self._model,
            "messages": messages,
        }
        if tools is not None:
            request_arguments["tools"] = tools
        if tool_choice is not None:
            request_arguments["tool_choice"] = tool_choice
        try:
            completion = await self._client.chat.completions.create(**request_arguments)
        except Exception as exc:
            self._raise_mapped_error(exc)
        return self._extract_response(completion)

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
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format=response_format,
            )
        except Exception as exc:
            self._raise_mapped_error(exc)

        raw_response = self._extract_response(completion)
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
