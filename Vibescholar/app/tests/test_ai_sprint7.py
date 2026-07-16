"""Isolated tests for the explicit EvidenceEvaluator OpenRouter backend."""

import asyncio
import logging
from enum import Enum
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel

from app.agents.evidence_evaluator import EvidenceEvaluator
from app.agents.schemas import (
    EvidenceAnalysisScope,
    EvidenceCandidateInput,
    EvidenceEvaluation,
    EvidenceEvaluationBatch,
    EvidenceVerdict,
)
from app.core.config import Settings, settings
from app.core.logging import llm_logger
from app.llm.exceptions import (
    LLMConfigurationError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseValidationError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.factory import create_evidence_evaluator_client
from app.llm.ollama_client import LLMComponent, OllamaClient
from app.llm.openrouter_client import OpenRouterClient


class ResultKind(str, Enum):
    """Small enum used to exercise structured response validation."""

    VALID = "valid"


class StructuredResult(BaseModel):
    """Minimal strict-output model used by the client tests."""

    value: str
    kind: ResultKind


class RecordingCompletions:
    """Record SDK payloads and return or raise one configured result."""

    def __init__(self, completion=None, error: Exception | None = None):
        self.completion = completion
        self.error = error
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.completion


class FakeSDKClient:
    """Expose the OpenAI SDK chat completion boundary used by the client."""

    def __init__(self, completions: RecordingCompletions):
        self.chat = SimpleNamespace(completions=completions)


def config(**overrides):
    """Build a complete non-secret configuration object for one client test."""
    values = {
        "EVIDENCE_EVALUATOR_BACKEND": "openrouter",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY": "test-openrouter-secret",
        "OPENROUTER_MODEL": "provider/test-model:free",
        "OPENROUTER_ALLOWED_MODELS": ("provider/test-model:free",),
        "OPENROUTER_ALLOW_PAID_MODELS": False,
        "LLM_TIMEOUT_SECONDS": 45,
        "LLM_TEMPERATURE": 0.1,
        "LLM_TOP_P": 0.9,
        "LLM_FREQUENCY_PENALTY": 0.0,
        "LLM_PRESENCE_PENALTY": 0.0,
        "LLM_SEED": 42,
        "LLM_DIAGNOSTIC_LOGGING": False,
        "EVIDENCE_EVALUATOR_MAX_OUTPUT_TOKENS": 1600,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def completion(content: str, *, finish_reason: str = "stop", usage=None):
    """Create the minimal successful completion consumed by OpenRouterClient."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        ],
        usage=usage,
    )


def run(coro):
    """Run one async operation without requiring an async pytest plugin."""
    return asyncio.run(coro)


def status_error(status: int) -> APIStatusError:
    """Build a safe SDK status error without a network request."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        status,
        request=request,
        json={"error": {"message": "safe test error"}},
    )
    return APIStatusError("safe test error", response=response, body=response.json())


def test_settings_default_to_ollama_and_conservative_output_limit(monkeypatch):
    monkeypatch.delenv("EVIDENCE_EVALUATOR_BACKEND", raising=False)
    monkeypatch.delenv("EVIDENCE_EVALUATOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_ALLOWED_MODELS", raising=False)
    monkeypatch.delenv("OPENROUTER_ALLOW_PAID_MODELS", raising=False)

    configured = Settings()

    assert configured.EVIDENCE_EVALUATOR_BACKEND == "ollama"
    assert configured.EVIDENCE_EVALUATOR_MAX_OUTPUT_TOKENS == 2000
    assert configured.OPENROUTER_MODEL == ""
    assert configured.OPENROUTER_ALLOWED_MODELS == ()
    assert configured.OPENROUTER_ALLOW_PAID_MODELS is False


def test_settings_read_openrouter_variables_by_their_correct_names(monkeypatch):
    monkeypatch.setenv("EVIDENCE_EVALUATOR_BACKEND", " OPENROUTER ")
    monkeypatch.setenv("OPENROUTER_MODEL", "tencent/hy3:free")
    monkeypatch.setenv(
        "OPENROUTER_ALLOWED_MODELS",
        " tencent/hy3:free, provider/second:free, TENCENT/HY3:FREE ",
    )
    monkeypatch.setenv("OPENROUTER_ALLOW_PAID_MODELS", "false")

    configured = Settings()

    assert configured.EVIDENCE_EVALUATOR_BACKEND == "openrouter"
    assert configured.OPENROUTER_MODEL == "tencent/hy3:free"
    assert configured.OPENROUTER_ALLOWED_MODELS == (
        "tencent/hy3:free",
        "provider/second:free",
    )
    assert configured.OPENROUTER_ALLOW_PAID_MODELS is False


def test_invalid_paid_models_flag_is_validated_only_for_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_ALLOW_PAID_MODELS", "invalid")
    monkeypatch.setenv("EVIDENCE_EVALUATOR_BACKEND", "ollama")

    assert Settings().OPENROUTER_ALLOW_PAID_MODELS is False

    monkeypatch.setenv("EVIDENCE_EVALUATOR_BACKEND", "openrouter")
    with pytest.raises(ValueError, match="OPENROUTER_ALLOW_PAID_MODELS"):
        Settings()


def test_factory_rejects_unknown_evaluator_backend_with_typed_error(monkeypatch):
    monkeypatch.setenv("EVIDENCE_EVALUATOR_BACKEND", "automatic")

    with pytest.raises(LLMConfigurationError, match="EVIDENCE_EVALUATOR_BACKEND"):
        create_evidence_evaluator_client(Settings())


def test_factory_selects_only_the_explicit_backend(monkeypatch):
    import app.llm.factory as factory_module

    ollama_sentinel = object()
    openrouter_sentinel = object()
    calls = {"ollama": 0, "openrouter": 0}

    def fake_ollama(*, component):
        calls["ollama"] += 1
        assert component is LLMComponent.EVIDENCE_EVALUATOR
        return ollama_sentinel

    def fake_openrouter(*, config):
        calls["openrouter"] += 1
        return openrouter_sentinel

    monkeypatch.setattr(factory_module, "OllamaClient", fake_ollama)
    monkeypatch.setattr(factory_module, "OpenRouterClient", fake_openrouter)

    assert create_evidence_evaluator_client(
        config(EVIDENCE_EVALUATOR_BACKEND="ollama")
    ) is ollama_sentinel
    assert calls == {"ollama": 1, "openrouter": 0}

    assert create_evidence_evaluator_client(config()) is openrouter_sentinel
    assert calls == {"ollama": 1, "openrouter": 1}

    with pytest.raises(LLMConfigurationError):
        create_evidence_evaluator_client(
            config(EVIDENCE_EVALUATOR_BACKEND="unknown")
        )


def test_ollama_selection_does_not_validate_openrouter_configuration(monkeypatch):
    import app.llm.factory as factory_module

    ollama_sentinel = object()
    monkeypatch.setattr(
        factory_module,
        "OllamaClient",
        lambda *, component: ollama_sentinel,
    )

    selected = create_evidence_evaluator_client(
        config(
            EVIDENCE_EVALUATOR_BACKEND="ollama",
            OPENROUTER_API_KEY="",
            OPENROUTER_MODEL="",
            OPENROUTER_ALLOWED_MODELS=(),
            OPENROUTER_ALLOW_PAID_MODELS=False,
        )
    )

    assert selected is ollama_sentinel


def test_openrouter_sdk_configuration_is_explicit_and_secret_safe(monkeypatch):
    import app.llm.openrouter_client as module

    captured = {}
    sdk_client = FakeSDKClient(RecordingCompletions())

    def fake_async_openai(**kwargs):
        captured.update(kwargs)
        return sdk_client

    monkeypatch.setattr(module, "AsyncOpenAI", fake_async_openai)
    client = OpenRouterClient(config=config())

    assert captured == {
        "base_url": "https://openrouter.ai/api/v1/",
        "api_key": "test-openrouter-secret",
        "timeout": 45,
        "max_retries": 0,
    }
    assert "test-openrouter-secret" not in repr(client)


@pytest.mark.parametrize(
    ("key", "model", "message"),
    [
        ("", "provider/model:free", "OPENROUTER_API_KEY"),
        ("secret", "", "OPENROUTER_MODEL"),
    ],
)
def test_openrouter_requires_key_and_model_only_when_constructed(key, model, message):
    with pytest.raises(LLMConfigurationError, match=message):
        OpenRouterClient(
            FakeSDKClient(RecordingCompletions()),
            config=config(
                OPENROUTER_API_KEY=key,
                OPENROUTER_MODEL=model,
                OPENROUTER_ALLOWED_MODELS=(model,) if model else (),
            ),
        )


def test_model_outside_allowlist_is_rejected_before_sdk_construction(monkeypatch):
    import app.llm.openrouter_client as module

    monkeypatch.setattr(
        module,
        "AsyncOpenAI",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("SDK client must not be constructed")
        ),
    )

    with pytest.raises(LLMConfigurationError, match="OPENROUTER_ALLOWED_MODELS"):
        OpenRouterClient(
            config=config(
                OPENROUTER_MODEL="provider/not-allowed:free",
                OPENROUTER_ALLOWED_MODELS=("provider/allowed:free",),
            )
        )


def test_factory_rejects_disallowed_model_before_client_construction(monkeypatch):
    import app.llm.factory as factory_module

    monkeypatch.setattr(
        factory_module,
        "OpenRouterClient",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("OpenRouterClient must not be constructed")
        ),
    )

    with pytest.raises(LLMConfigurationError, match="OPENROUTER_ALLOWED_MODELS"):
        create_evidence_evaluator_client(
            config(
                OPENROUTER_MODEL="provider/not-allowed:free",
                OPENROUTER_ALLOWED_MODELS=("provider/allowed:free",),
            )
        )


def test_paid_model_is_rejected_locally_when_paid_models_are_disabled(monkeypatch):
    import app.llm.openrouter_client as module

    monkeypatch.setattr(
        module,
        "AsyncOpenAI",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("SDK client must not be constructed")
        ),
    )

    with pytest.raises(LLMConfigurationError, match="Paid OpenRouter models"):
        OpenRouterClient(
            config=config(
                OPENROUTER_MODEL="provider/paid-model",
                OPENROUTER_ALLOWED_MODELS=("provider/paid-model",),
                OPENROUTER_ALLOW_PAID_MODELS=False,
            )
        )


def test_paid_model_can_be_explicitly_enabled():
    client = OpenRouterClient(
        FakeSDKClient(RecordingCompletions()),
        config=config(
            OPENROUTER_MODEL="provider/paid-model",
            OPENROUTER_ALLOWED_MODELS=("provider/paid-model",),
            OPENROUTER_ALLOW_PAID_MODELS=True,
        ),
    )

    assert "provider/paid-model" in repr(client)


def test_structured_chat_sends_centralized_parameters_and_returns_model():
    completions = RecordingCompletions(
        completion('{"value":"ok","kind":"valid"}')
    )
    client = OpenRouterClient(FakeSDKClient(completions), config=config())

    result = run(
        client.structured_chat(
            [{"role": "user", "content": "untrusted test payload"}],
            StructuredResult,
        )
    )

    assert isinstance(result, StructuredResult)
    assert result.value == "ok"
    assert len(completions.calls) == 1
    request = completions.calls[0]
    assert request["model"] == "provider/test-model:free"
    assert request["temperature"] == 0.1
    assert request["top_p"] == 0.9
    assert request["frequency_penalty"] == 0.0
    assert request["presence_penalty"] == 0.0
    assert request["seed"] == 42
    assert request["max_tokens"] == 1600
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"] == (
        StructuredResult.model_json_schema()
    )
    assert request["extra_body"] == {
        "provider": {"require_parameters": True}
    }


def test_structured_chat_omits_seed_when_not_configured():
    completions = RecordingCompletions(
        completion('{"value":"ok","kind":"valid"}')
    )
    client = OpenRouterClient(
        FakeSDKClient(completions),
        config=config(LLM_SEED=None),
    )

    run(client.structured_chat([], StructuredResult))

    assert "seed" not in completions.calls[0]


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"value":"ok","kind":"unknown"}',
        'prefix {"value":"ok","kind":"valid"}',
    ],
)
def test_invalid_structured_content_is_rejected_without_repair(content):
    client = OpenRouterClient(
        FakeSDKClient(RecordingCompletions(completion(content))),
        config=config(),
    )

    with pytest.raises(LLMResponseValidationError):
        run(client.structured_chat([], StructuredResult))


@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (
            APITimeoutError(
                httpx.Request(
                    "POST", "https://openrouter.ai/api/v1/chat/completions"
                )
            ),
            LLMTimeoutError,
        ),
        (
            APIConnectionError(
                message="connection failed",
                request=httpx.Request(
                    "POST", "https://openrouter.ai/api/v1/chat/completions"
                ),
            ),
            LLMConnectionError,
        ),
        (status_error(401), LLMConfigurationError),
        (status_error(403), LLMConfigurationError),
        (status_error(404), LLMUnavailableError),
        (status_error(429), LLMRateLimitError),
        (status_error(503), LLMUnavailableError),
    ],
)
def test_sdk_failures_are_mapped_without_retry(sdk_error, expected_error):
    completions = RecordingCompletions(error=sdk_error)
    client = OpenRouterClient(FakeSDKClient(completions), config=config())

    with pytest.raises(expected_error) as captured:
        run(client.structured_chat([], StructuredResult))

    assert len(completions.calls) == 1
    assert "test-openrouter-secret" not in str(captured.value)


def test_diagnostic_logs_are_safe_and_include_operational_data(caplog):
    secret = "OPENROUTER_SECRET_SENTINEL"
    sentence = "SENTENCE_SENTINEL"
    title = "TITLE_SENTINEL"
    abstract = "ABSTRACT_SENTINEL"
    raw_response = '{"value":"RAW_RESPONSE_SENTINEL","kind":"valid"}'
    client = OpenRouterClient(
        FakeSDKClient(RecordingCompletions(completion(raw_response))),
        config=config(
            OPENROUTER_API_KEY=secret,
            LLM_DIAGNOSTIC_LOGGING=True,
        ),
    )

    with caplog.at_level(logging.DEBUG, logger=llm_logger.name):
        result = run(
            client.structured_chat(
                [
                    {"role": "system", "content": "SYSTEM_PROMPT_SENTINEL"},
                    {
                        "role": "user",
                        "content": f"{sentence} {title} {abstract}",
                    },
                ],
                StructuredResult,
            )
        )

    assert result.value == "RAW_RESPONSE_SENTINEL"
    logs = caplog.text
    assert "backend=OpenRouterClient" in logs
    assert "component=EvidenceEvaluator" in logs
    assert "model=provider/test-model:free" in logs
    assert "max_output_tokens=1600" in logs
    for forbidden in (
        secret,
        sentence,
        title,
        abstract,
        "SYSTEM_PROMPT_SENTINEL",
        "RAW_RESPONSE_SENTINEL",
    ):
        assert forbidden not in logs


def test_evidence_evaluator_accepts_transport_neutral_structured_clients():
    candidate = EvidenceCandidateInput(
        candidate_key="candidate:one",
        title="A title",
        abstract="An abstract.",
    )
    batch = EvidenceEvaluationBatch(
        evaluations=[
            EvidenceEvaluation(
                candidate_key=candidate.candidate_key,
                verdict=EvidenceVerdict.STRONG_SUPPORT,
                confidence=0.9,
                reason="Direct support.",
                analysis_scope=EvidenceAnalysisScope.TITLE_AND_ABSTRACT,
            )
        ]
    )

    class CompatibleClient:
        def __init__(self, backend_name):
            self.backend_name = backend_name
            self.calls = 0

        async def structured_chat(self, messages, response_model):
            self.calls += 1
            assert response_model is EvidenceEvaluationBatch
            return batch

    for backend_name in ("OllamaClient", "OpenRouterClient"):
        client = CompatibleClient(backend_name)
        result = run(
            EvidenceEvaluator(client).evaluate_batch("A claim.", [candidate])
        )
        assert result == batch
        assert client.calls == 1


def test_runtime_keeps_search_agent_on_ollama_and_selects_only_evaluator(
    monkeypatch,
):
    import app.services.evidence_search_runtime as runtime_module

    search_client = object()
    evaluator_client = object()
    components = []

    def fake_ollama(*, component):
        components.append(component)
        return search_client

    monkeypatch.setattr(settings, "USE_MOCK", False)
    monkeypatch.setattr(settings, "EVIDENCE_EVALUATOR_BACKEND", "openrouter")
    monkeypatch.setattr(runtime_module, "OllamaClient", fake_ollama)
    monkeypatch.setattr(
        runtime_module,
        "create_evidence_evaluator_client",
        lambda config: evaluator_client,
    )
    runtime_module.get_evidence_search_runtime.cache_clear()
    try:
        runtime = runtime_module.get_evidence_search_runtime()
    finally:
        runtime_module.get_evidence_search_runtime.cache_clear()

    assert components == [LLMComponent.SEARCH_AGENT]
    assert runtime.workflow._search_agent._client is search_client
    assert runtime.workflow._evidence_evaluator._client is evaluator_client


def test_mock_runtime_constructs_no_real_llm_client(monkeypatch):
    import app.services.evidence_search_runtime as runtime_module

    calls = {"ollama": 0, "evaluator_factory": 0}

    def forbidden_ollama(*args, **kwargs):
        calls["ollama"] += 1
        raise AssertionError("real Ollama client must not be constructed")

    def forbidden_factory(*args, **kwargs):
        calls["evaluator_factory"] += 1
        raise AssertionError("real evaluator client must not be constructed")

    monkeypatch.setattr(settings, "USE_MOCK", True)
    monkeypatch.setattr(runtime_module, "OllamaClient", forbidden_ollama)
    monkeypatch.setattr(
        runtime_module,
        "create_evidence_evaluator_client",
        forbidden_factory,
    )
    runtime_module.get_evidence_search_runtime.cache_clear()
    try:
        with pytest.raises(LLMConfigurationError, match="USE_MOCK"):
            runtime_module.get_evidence_search_runtime()
    finally:
        runtime_module.get_evidence_search_runtime.cache_clear()

    assert calls == {"ollama": 0, "evaluator_factory": 0}
