"""Safe request and response instrumentation for the structured LLM client."""

import asyncio
import logging
from types import SimpleNamespace

from pydantic import BaseModel

from app.core.config import settings
from app.llm.ollama_client import LLMComponent, OllamaClient


class EvidenceEvaluationBatch(BaseModel):
    """Minimal model named like the evaluator's real structured contract."""

    value: str


class InstrumentedCompletions:
    """Return configured SDK-shaped completions without network access."""

    def __init__(self, *, content: str, usage=None, tool_calls=None) -> None:
        self.content = content
        self.usage = usage
        self.tool_calls = tool_calls
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            model="test-model",
            usage=self.usage,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=self.content,
                        tool_calls=self.tool_calls,
                    ),
                    finish_reason="tool_calls" if self.tool_calls else "stop",
                )
            ],
        )


class InstrumentedSDKClient:
    """Expose only the SDK surface consumed by OllamaClient."""

    def __init__(self, completions: InstrumentedCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def run(coroutine):
    """Run one asynchronous instrumentation scenario."""

    return asyncio.run(coroutine)


def test_chat_logs_effective_parameters_tools_usage_and_safe_sizes(
    monkeypatch, caplog
):
    async def scenario():
        prompt_marker = "private-search-agent-prompt"
        secret = "private-ollama-key"
        monkeypatch.setattr(settings, "OLLAMA_API_KEY", secret)
        monkeypatch.setattr(settings, "OLLAMA_MODEL", "qwen3.5:9b")
        monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.1)
        monkeypatch.setattr(settings, "LLM_TOP_P", 0.9)
        monkeypatch.setattr(settings, "LLM_FREQUENCY_PENALTY", 0.0)
        monkeypatch.setattr(settings, "LLM_PRESENCE_PENALTY", 0.0)
        monkeypatch.setattr(settings, "LLM_SEED", 42)
        usage = SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=15,
            total_tokens=135,
        )
        tool_calls = [
            SimpleNamespace(
                type="function",
                id="call-1",
                function=SimpleNamespace(
                    name="search_academic_works",
                    arguments='{"queries":["query"],"limit_per_provider":5}',
                ),
            )
        ]
        completions = InstrumentedCompletions(
            content=None,
            usage=usage,
            tool_calls=tool_calls,
        )
        client = OllamaClient(
            InstrumentedSDKClient(completions),
            component=LLMComponent.SEARCH_AGENT,
        )
        tools = [
            {"type": "function", "function": {"name": "one", "parameters": {}}},
            {"type": "function", "function": {"name": "two", "parameters": {}}},
        ]

        with caplog.at_level(logging.DEBUG, logger="vibescholar"):
            await client.chat(
                [
                    {"role": "system", "content": prompt_marker},
                    {"role": "user", "content": "private-user-content"},
                ],
                tools=tools,
                tool_choice="auto",
            )

        logs = caplog.text
        assert "ai.pipeline.llm.request" in logs
        assert "component=SearchAgent" in logs
        assert "operation=chat" in logs
        assert "model=qwen3.5:9b" in logs
        assert "temperature=0.1" in logs
        assert "top_p=0.9" in logs
        assert "frequency_penalty=0.0" in logs
        assert "presence_penalty=0.0" in logs
        assert "seed=42" in logs
        assert "tool_choice=auto" in logs
        assert "tools=2" in logs
        assert "messages=2" in logs
        assert "characters_total=" in logs
        assert "schema_characters=0" in logs
        assert "ai.pipeline.llm.response" in logs
        assert "finish_reason=tool_calls" in logs
        assert "tool_calls_present=True" in logs
        assert "tool_calls=1" in logs
        assert "prompt_tokens=120" in logs
        assert "completion_tokens=15" in logs
        assert "total_tokens=135" in logs
        assert prompt_marker not in logs
        assert "private-user-content" not in logs
        assert secret not in logs

    run(scenario())


def test_structured_chat_without_seed_or_usage_logs_approximate_metrics(
    monkeypatch, caplog
):
    async def scenario():
        system_content = "system-private-marker"
        user_content = "user-private-marker"
        monkeypatch.setattr(settings, "LLM_SEED", None)
        completions = InstrumentedCompletions(
            content='{"value":"ok"}',
            usage=None,
        )
        client = OllamaClient(
            InstrumentedSDKClient(completions),
            component=LLMComponent.EVIDENCE_EVALUATOR,
        )

        with caplog.at_level(logging.DEBUG, logger="vibescholar"):
            result = await client.structured_chat(
                [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                EvidenceEvaluationBatch,
            )

        assert result == EvidenceEvaluationBatch(value="ok")
        logs = caplog.text
        assert "ai.pipeline.llm.request" in logs
        assert "component=EvidenceEvaluator" in logs
        assert "operation=structured_chat" in logs
        assert "seed=disabled" in logs
        assert "tools=0" in logs
        assert "structured_output=True" in logs
        assert "usage_available=False" in logs
        assert "prompt_tokens=unavailable" in logs
        assert "messages=2" in logs
        assert f"system_characters={len(system_content)}" in logs
        assert f"user_characters={len(user_content)}" in logs
        assert (
            f"characters_total={len(system_content) + len(user_content)}"
            in logs
        )
        assert "schema_characters=" in logs
        assert system_content not in logs
        assert user_content not in logs

    run(scenario())
