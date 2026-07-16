"""Typed failures exposed by local language-model integrations."""

from enum import Enum


class LLMError(Exception):
    """Base exception for controlled language-model client failures."""


class LLMConnectionError(LLMError):
    """Raised when the configured language-model service cannot be reached."""


class LLMTimeoutError(LLMError):
    """Raised when a language-model operation exceeds its configured timeout."""


class LLMResponseValidationError(LLMError):
    """Raised when a successful response violates the required output contract."""


class LLMUnavailableError(LLMError):
    """Raised when the service is reachable but the model or service is unavailable."""


class LLMConfigurationError(LLMError):
    """Raised when an explicitly selected LLM backend is not safely configured."""


class LLMRateLimitError(LLMError):
    """Raised when an LLM backend rejects a request due to rate limiting."""


class UnknownToolError(LLMError):
    """Raised when a model requests a function outside the exact whitelist."""


class MultipleToolCallsError(LLMError):
    """Raised when one inference emits more than one function tool call."""


class ToolArgumentsValidationError(LLMError):
    """Raised when function arguments violate their Pydantic input contract."""


class ToolUnavailableError(LLMError):
    """Raised when the selected function has no configured executor."""


class AcademicProviderErrorCode(str, Enum):
    """Safe operational failure codes exposed by academic providers."""

    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    INVALID_RESPONSE = "invalid_response"
    SERVICE_UNAVAILABLE = "service_unavailable"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN = "unknown"


class AcademicProviderError(Exception):
    """Controlled provider failure that never contains response bodies or credentials."""

    def __init__(
        self,
        provider: str,
        operation: str,
        code: AcademicProviderErrorCode,
        *,
        status_code: int | None = None,
    ) -> None:
        self.provider = provider
        self.operation = operation
        self.code = code
        self.status_code = status_code
        super().__init__(f"{provider} {operation} failed ({code.value})")
