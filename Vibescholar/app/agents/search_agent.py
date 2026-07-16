"""Initial and refinement academic-search decisions over one injected LLM client."""

import json
import time
from pathlib import Path

from pydantic import ValidationError

from app.agents.schemas import CitationHint, SearchPlan, SearchRoundSummary
from app.core.logging import logger
from app.llm.exceptions import (
    LLMResponseValidationError,
    LLMUnavailableError,
    MultipleToolCallsError,
    ToolArgumentsValidationError,
    ToolUnavailableError,
    UnknownToolError,
)
from app.llm.ollama_client import OllamaClient
from app.tools.academic_search import AcademicSearchExecutor, search_academic_works
from app.tools.citation_resolution import CitationResolutionExecutor, resolve_citation_metadata
from app.tools.schemas import (
    AcademicSearchInput,
    CitationResolutionInput,
    SearchToolCallRecord,
    SearchToolExecutionOutcome,
)
from app.agents.schemas import SearchToolName, SentenceType


class SearchAgent:
    """Produce initial plans and single-inference native tool decisions."""

    MAX_SENTENCE_CHARACTERS = 12_000

    def __init__(
        self,
        client: OllamaClient,
        prompt_path: Path | None = None,
        refinement_prompt_path: Path | None = None,
    ) -> None:
        self._client = client
        self._prompt_path = prompt_path or (
            Path(__file__).resolve().parents[2] / "prompts" / "search_agent_system.txt"
        )
        self._refinement_prompt_path = refinement_prompt_path or (
            Path(__file__).resolve().parents[2] / "prompts" / "search_refinement_system.txt"
        )
        self._system_prompt = self._load_prompt(self._prompt_path, "SearchAgent")
        self._refinement_system_prompt = self._load_prompt(
            self._refinement_prompt_path,
            "SearchAgent refinement",
        )

    @staticmethod
    def _load_prompt(prompt_path: Path, label: str) -> str:
        try:
            prompt = prompt_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise LLMUnavailableError(f"The {label} system prompt is unavailable.") from exc
        if not prompt:
            raise LLMUnavailableError(f"The {label} system prompt is empty.")
        return prompt

    @staticmethod
    def _tool_definitions() -> list[dict]:
        """Build the exact two function tools exposed to the model."""
        return [
            {
                "type": "function",
                "function": {
                    "name": SearchToolName.SEARCH_ACADEMIC_WORKS.value,
                    "description": (
                        "Use when a scientific claim needs new academic references. "
                        "The application will query all enabled academic providers."
                    ),
                    "parameters": AcademicSearchInput.model_json_schema(),
                    "strict": True,
                },
            },
            {
                "type": "function",
                "function": {
                    "name": SearchToolName.RESOLVE_CITATION_METADATA.value,
                    "description": (
                        "Use when an explicit citation or partial citation metadata "
                        "must be resolved."
                    ),
                    "parameters": CitationResolutionInput.model_json_schema(),
                    "strict": True,
                },
            },
        ]

    def _build_messages(
        self,
        sentence: str,
        citation_hints: list[CitationHint],
    ) -> list[dict]:
        """Keep the sentence and hints isolated as user-provided JSON data."""
        payload = json.dumps(
            {
                "sentence": sentence,
                "citation_hints": [hint.model_dump(mode="json") for hint in citation_hints],
            },
            ensure_ascii=False,
        )
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": payload},
        ]

    def _validate_input(self, sentence: str) -> None:
        """Reject unusable input before invoking the model."""
        if not isinstance(sentence, str) or not sentence.strip():
            raise ValueError("sentence must contain non-whitespace text")
        if len(sentence) > self.MAX_SENTENCE_CHARACTERS:
            raise ValueError(
                f"sentence must contain at most {self.MAX_SENTENCE_CHARACTERS} characters"
            )

    def _build_refinement_messages(
        self,
        sentence: str,
        previous_round: SearchRoundSummary,
    ) -> list[dict]:
        """Send only the sentence and aggregate previous-round data as untrusted input."""
        payload = json.dumps(
            {
                "sentence": sentence,
                "previous_round": previous_round.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        return [
            {"role": "system", "content": self._refinement_system_prompt},
            {"role": "user", "content": payload},
        ]

    async def plan_initial_search(
        self,
        sentence: str,
        citation_hints: list[CitationHint] | None = None,
    ) -> SearchPlan:
        """Return exactly one validated SearchPlan for the supplied sentence."""
        self._validate_input(sentence)
        hints = citation_hints or []
        messages = self._build_messages(sentence, hints)
        logger.debug(
            "search_agent.plan_initial_search sentence_length=%s citation_hints=%s",
            len(sentence),
            len(hints),
        )
        plan = await self._client.structured_chat(messages, SearchPlan)
        if not isinstance(plan, SearchPlan):
            raise LLMResponseValidationError("OllamaClient did not return a validated SearchPlan.")
        return plan

    async def run_search_decision(
        self,
        sentence: str,
        citation_hints: list[CitationHint] | None = None,
        academic_search_executor: AcademicSearchExecutor | None = None,
        citation_resolution_executor: CitationResolutionExecutor | None = None,
    ) -> SearchToolExecutionOutcome:
        """Perform one inference and execute at most one validated function tool."""
        self._validate_input(sentence)
        hints = citation_hints or []
        messages = self._build_messages(sentence, hints)
        return await self._run_tool_decision(
            messages,
            academic_search_executor=academic_search_executor,
            citation_resolution_executor=citation_resolution_executor,
            allow_citation_resolution=True,
        )

    async def run_refined_search_decision(
        self,
        *,
        sentence: str,
        previous_round: SearchRoundSummary,
        academic_search_executor: AcademicSearchExecutor | None = None,
        citation_resolution_executor: CitationResolutionExecutor | None = None,
    ) -> SearchToolExecutionOutcome:
        """Perform one native tool-calling inference for an academic refinement round."""
        self._validate_input(sentence)
        summary = SearchRoundSummary.model_validate(previous_round)
        messages = self._build_refinement_messages(sentence, summary)
        return await self._run_tool_decision(
            messages,
            academic_search_executor=academic_search_executor,
            citation_resolution_executor=citation_resolution_executor,
            allow_citation_resolution=False,
        )

    async def _run_tool_decision(
        self,
        messages: list[dict],
        *,
        academic_search_executor: AcademicSearchExecutor | None,
        citation_resolution_executor: CitationResolutionExecutor | None,
        allow_citation_resolution: bool,
    ) -> SearchToolExecutionOutcome:
        """Run exactly one inference and execute at most one authorized tool."""
        started_at = time.perf_counter()
        decision_kind = "initial" if allow_citation_resolution else "refinement"
        logger.info(
            "ai.pipeline.search_agent.started decision=%s tool_count=%s",
            decision_kind,
            len(self._tool_definitions()),
        )
        response = await self._client.chat(
            messages,
            tools=self._tool_definitions(),
            tool_choice="auto",
        )

        if len(response.tool_calls) > 1:
            raise MultipleToolCallsError("The model returned more than one tool call.")

        if not response.tool_calls:
            if not isinstance(response.content, str):
                raise LLMResponseValidationError("A no-tool decision requires a SearchPlan response.")
            try:
                plan = SearchPlan.model_validate_json(response.content)
            except (ValidationError, ValueError) as exc:
                raise LLMResponseValidationError(
                    "The no-tool decision does not satisfy SearchPlan."
                ) from exc
            if plan.should_search or plan.selected_tool is not SearchToolName.NONE:
                raise LLMResponseValidationError(
                    "A no-tool decision must use should_search=false and selected_tool=none."
                )
            outcome = SearchToolExecutionOutcome(
                sentence_type=plan.sentence_type,
                action_taken=SearchToolName.NONE,
                reason=plan.reason,
            )
            logger.info(
                "ai.pipeline.search_agent.completed decision=%s action=none tool_called=false "
                "duration=%.4f termination=no_action",
                decision_kind,
                time.perf_counter() - started_at,
            )
            return outcome

        sdk_call = response.tool_calls[0]

        try:
            if sdk_call.tool_name == SearchToolName.SEARCH_ACADEMIC_WORKS.value:
                arguments = AcademicSearchInput.model_validate_json(sdk_call.arguments_json)
                tool_name = SearchToolName.SEARCH_ACADEMIC_WORKS
                sentence_type = SentenceType.SCIENTIFIC_CLAIM
            elif sdk_call.tool_name == SearchToolName.RESOLVE_CITATION_METADATA.value:
                if not allow_citation_resolution:
                    raise ToolArgumentsValidationError(
                        "Citation resolution is incompatible with academic search refinement."
                    )
                arguments = CitationResolutionInput.model_validate_json(sdk_call.arguments_json)
                tool_name = SearchToolName.RESOLVE_CITATION_METADATA
                sentence_type = SentenceType.CITATION_CLAIM
            else:
                raise UnknownToolError("The model requested an unauthorized tool.")
        except UnknownToolError:
            raise
        except (ValidationError, ValueError) as exc:
            raise ToolArgumentsValidationError("The tool-call arguments are invalid.") from exc

        call_record = SearchToolCallRecord(
            tool_call_id=sdk_call.tool_call_id,
            tool_name=tool_name,
            validated_arguments=arguments,
        )

        try:
            if tool_name is SearchToolName.SEARCH_ACADEMIC_WORKS:
                tool_execution = await search_academic_works(arguments, academic_search_executor)
            else:
                tool_execution = await resolve_citation_metadata(arguments, citation_resolution_executor)
        except ToolUnavailableError:
            raise

        outcome = SearchToolExecutionOutcome(
            sentence_type=sentence_type,
            action_taken=tool_name,
            tool_call_id=sdk_call.tool_call_id,
            tool_execution=tool_execution,
            reason=tool_execution.to_public_result().message,
            tool_call=call_record,
        )
        public_result = tool_execution.to_public_result()
        logger.info(
            "ai.pipeline.search_agent.completed decision=%s action=%s tool_called=true "
            "status=%s duration=%.4f termination=tool_completed",
            decision_kind,
            tool_name.value,
            public_result.status.value,
            time.perf_counter() - started_at,
        )
        return outcome
