"""Tests for centralized LLM inference parameters."""

import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError
from pydantic import BaseModel

from app.core.config import Settings, settings
from app.core.logging import configure_llm_diagnostic_logging
from app.llm.exceptions import LLMTimeoutError
from app.llm.ollama_client import LLMComponent, OllamaClient


class StructuredResult(BaseModel):
    """Minimal structured response used to inspect SDK arguments."""

    value: str


class FakeCompletions:
    """Record chat completion calls without network access."""

    def __init__(self, content: str = "ok", *, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            model="test-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content, tool_calls=None),
                    finish_reason="stop",
                )
            ],
        )


class FakeSDKClient:
    """Expose the OpenAI SDK surface consumed by OllamaClient."""

    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def run(coroutine):
    """Execute one isolated asynchronous scenario."""

    return asyncio.run(coroutine)


def test_inference_settings_read_defaults_and_environment(monkeypatch):
    names = (
        "LLM_TEMPERATURE",
        "LLM_TOP_P",
        "LLM_FREQUENCY_PENALTY",
        "LLM_PRESENCE_PENALTY",
        "LLM_SEED",
        "LLM_DIAGNOSTIC_LOGGING",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    defaults = Settings()
    assert defaults.LLM_TEMPERATURE == 0.1
    assert defaults.LLM_TOP_P == 0.9
    assert defaults.LLM_FREQUENCY_PENALTY == 0.0
    assert defaults.LLM_PRESENCE_PENALTY == 0.0
    assert defaults.LLM_SEED is None
    assert defaults.LLM_DIAGNOSTIC_LOGGING is False

    monkeypatch.setenv("LLM_TEMPERATURE", "0.25")
    monkeypatch.setenv("LLM_TOP_P", "0.8")
    monkeypatch.setenv("LLM_FREQUENCY_PENALTY", "0.15")
    monkeypatch.setenv("LLM_PRESENCE_PENALTY", "-0.2")
    monkeypatch.setenv("LLM_SEED", "42")
    monkeypatch.setenv("LLM_DIAGNOSTIC_LOGGING", "true")

    configured = Settings()
    assert configured.LLM_TEMPERATURE == 0.25
    assert configured.LLM_TOP_P == 0.8
    assert configured.LLM_FREQUENCY_PENALTY == 0.15
    assert configured.LLM_PRESENCE_PENALTY == -0.2
    assert configured.LLM_SEED == 42
    assert configured.LLM_DIAGNOSTIC_LOGGING is True


def test_chat_sends_all_configured_inference_parameters(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.2)
        monkeypatch.setattr(settings, "LLM_TOP_P", 0.85)
        monkeypatch.setattr(settings, "LLM_FREQUENCY_PENALTY", 0.1)
        monkeypatch.setattr(settings, "LLM_PRESENCE_PENALTY", -0.1)
        monkeypatch.setattr(settings, "LLM_SEED", 7)
        completions = FakeCompletions()
        client = OllamaClient(FakeSDKClient(completions))

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_academic_works",
                    "parameters": {"type": "object"},
                },
            }
        ]
        await client.chat(
            [{"role": "user", "content": "claim"}],
            tools=tools,
            tool_choice="auto",
        )

        request = completions.calls[0]
        assert request["model"] == settings.OLLAMA_MODEL
        assert request["temperature"] == 0.2
        assert request["top_p"] == 0.85
        assert request["frequency_penalty"] == 0.1
        assert request["presence_penalty"] == -0.1
        assert request["seed"] == 7
        assert request["tools"] is tools
        assert request["tool_choice"] == "auto"

    run(scenario())


def test_structured_chat_sends_parameters_and_omits_disabled_seed(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.1)
        monkeypatch.setattr(settings, "LLM_TOP_P", 0.9)
        monkeypatch.setattr(settings, "LLM_FREQUENCY_PENALTY", 0.0)
        monkeypatch.setattr(settings, "LLM_PRESENCE_PENALTY", 0.0)
        monkeypatch.setattr(settings, "LLM_SEED", None)
        completions = FakeCompletions('{"value":"ok"}')
        client = OllamaClient(FakeSDKClient(completions))

        result = await client.structured_chat(
            [{"role": "user", "content": "claim"}],
            StructuredResult,
        )

        request = completions.calls[0]
        assert result == StructuredResult(value="ok")
        assert request["model"] == settings.OLLAMA_MODEL
        assert request["temperature"] == 0.1
        assert request["top_p"] == 0.9
        assert request["frequency_penalty"] == 0.0
        assert request["presence_penalty"] == 0.0
        assert "seed" not in request
        assert request["response_format"]["type"] == "json_schema"
        assert request["response_format"]["json_schema"]["schema"] == (
            StructuredResult.model_json_schema()
        )

    run(scenario())


def test_structured_chat_sends_the_same_configured_parameters_with_seed(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.35)
        monkeypatch.setattr(settings, "LLM_TOP_P", 0.75)
        monkeypatch.setattr(settings, "LLM_FREQUENCY_PENALTY", 0.2)
        monkeypatch.setattr(settings, "LLM_PRESENCE_PENALTY", -0.25)
        monkeypatch.setattr(settings, "LLM_SEED", 99)
        completions = FakeCompletions('{"value":"ok"}')
        client = OllamaClient(FakeSDKClient(completions))

        await client.structured_chat(
            [{"role": "user", "content": "claim"}],
            StructuredResult,
        )

        request = completions.calls[0]
        assert request["model"] == settings.OLLAMA_MODEL
        assert request["temperature"] == 0.35
        assert request["top_p"] == 0.75
        assert request["frequency_penalty"] == 0.2
        assert request["presence_penalty"] == -0.25
        assert request["seed"] == 99
        assert request["response_format"]["type"] == "json_schema"

    run(scenario())


def test_initialization_log_contains_only_operational_parameters(
    monkeypatch, caplog
):
    secret = "secret-ollama-key-that-must-not-be-logged"
    monkeypatch.setattr(settings, "OLLAMA_API_KEY", secret)
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "diagnostic-model")
    monkeypatch.setattr(settings, "LLM_SEED", None)
    monkeypatch.setattr(settings, "LLM_DIAGNOSTIC_LOGGING", True)

    with caplog.at_level(logging.DEBUG, logger="vibescholar"):
        OllamaClient(FakeSDKClient(FakeCompletions()))

    message = caplog.text
    assert "llm.ollama.initialized" in message
    assert "model=diagnostic-model" in message
    assert "context_configured=backend_default" in message
    assert "seed=disabled" in message
    assert secret not in message


def test_chat_logs_effective_parameters_without_messages_or_credentials(
    monkeypatch, caplog
):
    async def scenario():
        prompt_marker = "private-prompt-marker"
        secret = "private-api-key-marker"
        monkeypatch.setattr(settings, "LLM_DIAGNOSTIC_LOGGING", True)
        monkeypatch.setattr(settings, "OLLAMA_API_KEY", secret)
        monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.2)
        monkeypatch.setattr(settings, "LLM_TOP_P", 0.8)
        monkeypatch.setattr(settings, "LLM_FREQUENCY_PENALTY", 0.1)
        monkeypatch.setattr(settings, "LLM_PRESENCE_PENALTY", -0.1)
        monkeypatch.setattr(settings, "LLM_SEED", 17)
        client = OllamaClient(
            FakeSDKClient(FakeCompletions()),
            component=LLMComponent.SEARCH_AGENT,
        )

        with caplog.at_level(logging.DEBUG, logger="vibescholar"):
            await client.chat([{"role": "user", "content": prompt_marker}])

        message = caplog.text
        assert "llm.ollama.inference" in message
        assert "temperature=0.2" in message
        assert "top_p=0.8" in message
        assert "frequency_penalty=0.1" in message
        assert "presence_penalty=-0.1" in message
        assert "seed=17" in message
        assert "context_configured=backend_default" in message
        assert prompt_marker not in message
        assert secret not in message

    run(scenario())


def test_structured_chat_logs_parameters_without_payload_content(
    monkeypatch, caplog
):
    async def scenario():
        payload_marker = "private-structured-payload"
        monkeypatch.setattr(settings, "LLM_DIAGNOSTIC_LOGGING", True)
        monkeypatch.setattr(settings, "LLM_SEED", None)
        client = OllamaClient(
            FakeSDKClient(FakeCompletions('{"value":"private-result"}')),
            component=LLMComponent.EVIDENCE_EVALUATOR,
        )

        with caplog.at_level(logging.DEBUG, logger="vibescholar"):
            await client.structured_chat(
                [{"role": "user", "content": payload_marker}],
                StructuredResult,
            )

        message = caplog.text
        assert "llm.ollama.structured_inference" in message
        assert "seed=disabled" in message
        assert payload_marker not in message
        assert "private-result" not in message

    run(scenario())


def test_failed_request_log_is_operational_and_excludes_sensitive_content(
    monkeypatch, caplog
):
    async def scenario():
        markers = (
            "SYSTEM-PROMPT-SECRET",
            "SENTENCE-SECRET",
            "TITLE-SECRET",
            "ABSTRACT-SECRET",
            "10.1234/SECRET-DOI",
        )
        api_key = "API-KEY-SECRET"
        monkeypatch.setattr(settings, "LLM_DIAGNOSTIC_LOGGING", True)
        monkeypatch.setattr(settings, "OLLAMA_API_KEY", api_key)
        timeout = APITimeoutError(request=httpx.Request("POST", "http://test"))
        client = OllamaClient(
            FakeSDKClient(FakeCompletions(error=timeout)),
            component=LLMComponent.SEARCH_AGENT,
        )
        messages = [
            {"role": "system", "content": markers[0]},
            {"role": "user", "content": " ".join(markers[1:])},
        ]

        with caplog.at_level(logging.DEBUG, logger="vibescholar"):
            with pytest.raises(LLMTimeoutError):
                await client.chat(messages)

        logs = caplog.text
        assert "status=failed" in logs
        assert "component=SearchAgent" in logs
        assert "operation=chat" in logs
        assert "error_type=APITimeoutError" in logs
        assert "model=" in logs
        assert "timeout=" in logs
        for marker in (*markers, api_key):
            assert marker not in logs

    run(scenario())


def test_diagnostic_logging_false_hides_llm_debug_events(monkeypatch, caplog):
    async def scenario():
        monkeypatch.setattr(settings, "LLM_DIAGNOSTIC_LOGGING", False)
        client = OllamaClient(FakeSDKClient(FakeCompletions()))

        with caplog.at_level(logging.DEBUG):
            await client.chat([{"role": "user", "content": "private-marker"}])

        assert "ai.pipeline.llm.request" not in caplog.text
        assert "ai.pipeline.llm.response" not in caplog.text
        assert "llm.ollama.inference" not in caplog.text

    run(scenario())


def test_diagnostic_logging_true_exposes_only_llm_events_and_keeps_global_info(
    monkeypatch, caplog
):
    async def scenario():
        secret = "diagnostic-secret-key"
        message = "diagnostic-private-message"
        monkeypatch.setattr(settings, "LLM_DIAGNOSTIC_LOGGING", True)
        monkeypatch.setattr(settings, "OLLAMA_API_KEY", secret)
        global_logger = logging.getLogger("vibescholar")
        client = OllamaClient(
            FakeSDKClient(FakeCompletions()),
            component=LLMComponent.SEARCH_AGENT,
        )

        with caplog.at_level(logging.DEBUG):
            await client.chat([{"role": "user", "content": message}])

        assert global_logger.getEffectiveLevel() == logging.INFO
        assert logging.getLogger("httpx").getEffectiveLevel() != logging.DEBUG
        assert "ai.pipeline.llm.request" in caplog.text
        assert "ai.pipeline.llm.response" in caplog.text
        assert "component=SearchAgent" in caplog.text
        assert secret not in caplog.text
        assert message not in caplog.text

    try:
        run(scenario())
    finally:
        configure_llm_diagnostic_logging(False)
