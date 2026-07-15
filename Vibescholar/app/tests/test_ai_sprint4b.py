"""Isolated tests for concrete concurrent academic tool executors."""

import asyncio
import inspect
import json
from dataclasses import dataclass, field

import httpx
import pytest

from app.agents.search_agent import SearchAgent
from app.core.config import settings
from app.llm.exceptions import (
    AcademicProviderError,
    AcademicProviderErrorCode,
    ToolArgumentsValidationError,
    ToolUnavailableError,
)
from app.llm.ollama_client import LLMChatResponse, LLMToolCall
from app.providers.semantic_scholar_provider import SemanticScholarProvider
from app.services.academic_search_executor import AcademicSearchExecutor
from app.services.citation_resolution_executor import CitationResolutionExecutor
from app.tools.academic_search import search_academic_works
from app.tools.citation_resolution import resolve_citation_metadata
from app.tools.schemas import (
    AcademicSearchExecutionResult,
    AcademicSearchInput,
    AcademicSearchStatus,
    CitationResolutionExecutionResult,
    CitationResolutionInput,
    CitationResolutionStatus,
    ReferenceCandidate,
    SearchToolExecutionOutcome,
)


def run(coroutine):
    """Execute one isolated asynchronous executor scenario."""
    return asyncio.run(coroutine)


def candidate(
    provider: str,
    identifier: str,
    *,
    title: str = "Academic Evidence",
    year: int = 2024,
    doi: str | None = None,
    authors: list[str] | None = None,
    abstract: str | None = None,
    issns: tuple[str, ...] = (),
) -> ReferenceCandidate:
    """Build test-only transient metadata."""
    return ReferenceCandidate(
        provider=provider,
        external_id=identifier,
        title=title,
        year=year,
        doi=doi,
        authors=authors or ["Ana Silva"],
        abstract=abstract,
        issns=issns,
        source_url=f"https://{provider}.invalid/{identifier}",
    )


def provider_error(provider: str, code=AcademicProviderErrorCode.SERVICE_UNAVAILABLE):
    """Build one safe operational provider failure."""
    return AcademicProviderError(provider, "test", code)


@dataclass
class ProviderStub:
    """Record provider calls and return configured test-only outcomes."""

    name: str
    search_result: list[ReferenceCandidate] = field(default_factory=list)
    lookup_result: list[ReferenceCandidate] = field(default_factory=list)
    search_error: Exception | None = None
    lookup_error: Exception | None = None
    search_calls: list[tuple[str, int]] = field(default_factory=list)
    lookup_calls: list[dict] = field(default_factory=list)

    async def search_works(self, query: str, limit: int):
        self.search_calls.append((query, limit))
        if self.search_error:
            raise self.search_error
        return self.search_result

    async def lookup(self, **kwargs):
        self.lookup_calls.append(kwargs)
        if self.lookup_error:
            raise self.lookup_error
        return self.lookup_result


class ConcurrentProvider(ProviderStub):
    """Require two provider calls to overlap before either may complete."""

    def __init__(self, name, probe, result):
        super().__init__(name, search_result=result)
        self.probe = probe

    async def search_works(self, query: str, limit: int):
        self.search_calls.append((query, limit))
        self.probe["active"] += 1
        self.probe["maximum"] = max(self.probe["maximum"], self.probe["active"])
        if self.probe["active"] == 2:
            self.probe["both_entered"].set()
        await asyncio.wait_for(self.probe["both_entered"].wait(), timeout=0.2)
        self.probe["active"] -= 1
        return self.search_result


class ConcurrentLookupProvider(ProviderStub):
    """Require two citation lookups to overlap before either may complete."""

    def __init__(self, name, probe, result):
        super().__init__(name, lookup_result=result)
        self.probe = probe

    async def lookup(self, **kwargs):
        self.lookup_calls.append(kwargs)
        self.probe["active"] += 1
        self.probe["maximum"] = max(self.probe["maximum"], self.probe["active"])
        if self.probe["active"] == 2:
            self.probe["both_entered"].set()
        await asyncio.wait_for(self.probe["both_entered"].wait(), timeout=0.2)
        self.probe["active"] -= 1
        return self.lookup_result


def academic_request(queries=None, limit=5):
    """Build one validated academic request."""
    return AcademicSearchInput(queries=queries or ["scientific evidence"], limit_per_provider=limit)


def citation_request(**hint):
    """Build one validated citation request."""
    values = {"raw": "(Silva, 2024)", **hint}
    return CitationResolutionInput(citation_hints=[values])


def test_academic_executor_runs_providers_concurrently_once():
    async def scenario():
        probe = {"active": 0, "maximum": 0, "both_entered": asyncio.Event()}
        openalex = ConcurrentProvider("openalex", probe, [candidate("openalex", "W1")])
        semantic = ConcurrentProvider(
            "semantic_scholar", probe, [candidate("semantic_scholar", "P1")]
        )
        executor = AcademicSearchExecutor(openalex, semantic)
        result = await executor.execute(academic_request())
        assert result.public_result.status is AcademicSearchStatus.SUCCESS
        assert probe["maximum"] == 2
        assert len(openalex.search_calls) == len(semantic.search_calls) == 1

    run(scenario())


def test_academic_executor_requires_exactly_one_query():
    async def scenario():
        executor = AcademicSearchExecutor(ProviderStub("openalex"), ProviderStub("semantic"))
        with pytest.raises(ToolArgumentsValidationError):
            await executor.execute(academic_request(["first", "second"]))

    run(scenario())


def test_academic_executor_clamps_provider_limit_to_fifteen():
    async def scenario():
        openalex = ProviderStub("openalex")
        semantic = ProviderStub("semantic")
        executor = AcademicSearchExecutor(openalex, semantic)
        await executor.execute(academic_request(limit=settings.RESULTS_PER_PROVIDER + 20))
        assert openalex.search_calls == [("scientific evidence", settings.RESULTS_PER_PROVIDER)]
        assert semantic.search_calls == [("scientific evidence", settings.RESULTS_PER_PROVIDER)]

    run(scenario())


def test_academic_executor_never_accepts_more_than_thirty_raw_results():
    async def scenario():
        openalex_results = [
            candidate("openalex", f"W{index}", title=f"OpenAlex {index}")
            for index in range(20)
        ]
        semantic_results = [
            candidate("semantic_scholar", f"P{index}", title=f"Semantic {index}")
            for index in range(20)
        ]
        result = await AcademicSearchExecutor(
            ProviderStub("openalex", search_result=openalex_results),
            ProviderStub("semantic", search_result=semantic_results),
        ).execute(academic_request(limit=100))
        assert result.public_result.raw_results == 30
        assert len(result.candidates) == 30

    run(scenario())


def test_academic_aggregation_deduplicates_doi_and_preserves_complete_metadata():
    async def scenario():
        sparse = candidate("openalex", "W1", doi="10.1000/same")
        rich = candidate(
            "semantic_scholar",
            "P1",
            doi="https://doi.org/10.1000/SAME",
            authors=["Ana Silva", "Bruno Costa"],
            abstract="Complete abstract.",
            issns=("1234-567X", "8765-4321"),
        )
        result = await AcademicSearchExecutor(
            ProviderStub("openalex", search_result=[sparse]),
            ProviderStub("semantic", search_result=[rich]),
        ).execute(academic_request())
        assert result.public_result.raw_results == 2
        assert result.public_result.after_deduplication == 1
        assert result.candidates[0].abstract == "Complete abstract."
        assert result.candidates[0].issns == ("1234-567X", "8765-4321")

    run(scenario())


def test_academic_deduplication_falls_back_to_title_and_year():
    async def scenario():
        first = candidate("openalex", "W1", title="Neural: Networks!", doi=None)
        second = candidate("semantic_scholar", "P1", title=" neural networks ", doi=None)
        result = await AcademicSearchExecutor(
            ProviderStub("openalex", search_result=[first]),
            ProviderStub("semantic", search_result=[second]),
        ).execute(academic_request())
        assert result.public_result.raw_results == 2
        assert len(result.candidates) == 1

    run(scenario())


@pytest.mark.parametrize(
    ("openalex_result", "openalex_error", "semantic_result", "semantic_error", "status"),
    [
        ([candidate("openalex", "W1")], None, [candidate("semantic_scholar", "P1")], None, "success"),
        ([], None, [], None, "empty"),
        ([candidate("openalex", "W1")], None, [], provider_error("semantic_scholar"), "partial_success"),
        ([], provider_error("openalex"), [candidate("semantic_scholar", "P1")], None, "partial_success"),
        ([], provider_error("openalex"), [], provider_error("semantic_scholar"), "failed"),
        ([], None, [], provider_error("semantic_scholar"), "failed"),
    ],
)
def test_academic_status_composition(
    openalex_result, openalex_error, semantic_result, semantic_error, status
):
    async def scenario():
        result = await AcademicSearchExecutor(
            ProviderStub("openalex", search_result=openalex_result, search_error=openalex_error),
            ProviderStub("semantic", search_result=semantic_result, search_error=semantic_error),
        ).execute(academic_request())
        assert result.public_result.status.value == status
        assert result.public_result.raw_results == sum(
            summary.results_found for summary in result.public_result.providers
        )

    run(scenario())


def test_provider_order_controls_summaries_and_candidate_order():
    async def scenario():
        result = await AcademicSearchExecutor(
            ProviderStub("openalex", search_result=[candidate("openalex", "W1", title="First")]),
            ProviderStub(
                "semantic", search_result=[candidate("semantic_scholar", "P1", title="Second")]
            ),
            provider_order=("semantic_scholar", "openalex"),
        ).execute(academic_request())
        assert [item.provider for item in result.public_result.providers] == [
            "semantic_scholar", "openalex"
        ]
        assert [item.title for item in result.candidates] == ["Second", "First"]

    run(scenario())


def test_academic_public_result_contains_no_candidate_metadata():
    async def scenario():
        private = candidate(
            "openalex", "private-id", doi="10.1000/private", abstract="Private abstract"
        )
        result = await AcademicSearchExecutor(
            ProviderStub("openalex", search_result=[private]), ProviderStub("semantic")
        ).execute(academic_request())
        public = result.to_public_result().model_dump_json().casefold()
        for forbidden in ("private-id", "10.1000/private", "private abstract", "candidate_key"):
            assert forbidden not in public

    run(scenario())


@pytest.mark.parametrize(
    ("citation_input", "expected_key", "expected_value"),
    [
        (citation_request(doi="https://doi.org/10.1000/ABC"), "doi", "10.1000/abc"),
        (citation_request(title="Exact Work", year=2024), "title", "Exact Work"),
        (citation_request(author="Silva", year=2024), "authors", ["Silva"]),
    ],
)
def test_citation_priority_and_one_lookup_per_provider(
    citation_input, expected_key, expected_value
):
    async def scenario():
        openalex = ProviderStub("openalex")
        semantic = ProviderStub("semantic")
        await CitationResolutionExecutor(openalex, semantic).execute(citation_input)
        assert len(openalex.lookup_calls) == len(semantic.lookup_calls) == 1
        assert openalex.lookup_calls[0][expected_key] == expected_value
        assert semantic.lookup_calls[0][expected_key] == expected_value

    run(scenario())


def test_citation_executor_runs_provider_lookups_concurrently():
    async def scenario():
        probe = {"active": 0, "maximum": 0, "both_entered": asyncio.Event()}
        match = candidate("openalex", "W1", doi="10.1000/exact")
        openalex = ConcurrentLookupProvider("openalex", probe, [match])
        semantic = ConcurrentLookupProvider("semantic", probe, [])
        result = await CitationResolutionExecutor(openalex, semantic).execute(
            citation_request(doi="10.1000/exact")
        )
        assert result.public_result.status is CitationResolutionStatus.RESOLVED
        assert probe["maximum"] == 2

    run(scenario())


def test_citation_doi_resolution_deduplicates_cross_provider_matches():
    async def scenario():
        first = candidate("openalex", "W1", doi="10.1000/exact")
        second = candidate(
            "semantic_scholar", "P1", doi="10.1000/exact", abstract="More metadata"
        )
        result = await CitationResolutionExecutor(
            ProviderStub("openalex", lookup_result=[first]),
            ProviderStub("semantic", lookup_result=[second]),
        ).execute(citation_request(doi="10.1000/exact"))
        assert result.public_result.status is CitationResolutionStatus.RESOLVED
        assert len(result.matches) == 1
        assert result.matches[0].abstract == "More metadata"

    run(scenario())


def test_citation_title_requires_exact_normalized_title_and_compatible_year():
    async def scenario():
        exact = candidate("openalex", "W1", title="Exact: Work!", year=2024)
        wrong_year = candidate("semantic_scholar", "P1", title="Exact Work", year=2023)
        result = await CitationResolutionExecutor(
            ProviderStub("openalex", lookup_result=[exact]),
            ProviderStub("semantic", lookup_result=[wrong_year]),
        ).execute(citation_request(title="exact work", year=2024))
        assert result.public_result.status is CitationResolutionStatus.RESOLVED
        assert result.matches == [exact]

    run(scenario())


def test_citation_author_year_matching_is_deterministic():
    async def scenario():
        matching = candidate("openalex", "W1", authors=["Ana Silva"], year=2024)
        unrelated = candidate("semantic_scholar", "P1", authors=["Outro Autor"], year=2024)
        result = await CitationResolutionExecutor(
            ProviderStub("openalex", lookup_result=[matching]),
            ProviderStub("semantic", lookup_result=[unrelated]),
        ).execute(citation_request(author="Silva", year=2024))
        assert result.public_result.status is CitationResolutionStatus.RESOLVED
        assert result.matches == [matching]

    run(scenario())


def test_citation_ambiguous_not_found_partial_failure_and_failed():
    async def scenario():
        one = candidate(
            "openalex", "W1", title="First Work", authors=["Ana Silva"], year=2024
        )
        two = candidate(
            "semantic_scholar", "P2", title="Second Work", authors=["Carlos Silva"], year=2024
        )
        ambiguous = await CitationResolutionExecutor(
            ProviderStub("openalex", lookup_result=[one]),
            ProviderStub("semantic", lookup_result=[two]),
        ).execute(citation_request(author="Silva", year=2024))
        assert ambiguous.public_result.status is CitationResolutionStatus.AMBIGUOUS

        not_found = await CitationResolutionExecutor(
            ProviderStub("openalex"), ProviderStub("semantic")
        ).execute(citation_request(doi="10.1000/missing"))
        assert not_found.public_result.status is CitationResolutionStatus.NOT_FOUND

        partial = await CitationResolutionExecutor(
            ProviderStub(
                "openalex",
                lookup_result=[candidate("openalex", "W3", title="Exact Work", year=2024)],
            ),
            ProviderStub("semantic", lookup_error=provider_error("semantic_scholar")),
        ).execute(citation_request(title="Exact Work", year=2024))
        assert partial.public_result.status is CitationResolutionStatus.PARTIAL_FAILURE

        failed = await CitationResolutionExecutor(
            ProviderStub("openalex", lookup_error=provider_error("openalex")),
            ProviderStub("semantic", lookup_error=provider_error("semantic_scholar")),
        ).execute(citation_request(doi="10.1000/missing"))
        assert failed.public_result.status is CitationResolutionStatus.FAILED

    run(scenario())


def test_non_provider_programming_errors_are_not_hidden_by_executors():
    async def scenario():
        executor = AcademicSearchExecutor(
            ProviderStub("openalex", search_error=TypeError("programming bug")),
            ProviderStub("semantic"),
        )
        with pytest.raises(TypeError, match="programming bug"):
            await executor.execute(academic_request())

    run(scenario())


def test_concrete_executors_integrate_with_existing_tools_and_remain_injectable():
    async def scenario():
        academic = AcademicSearchExecutor(
            ProviderStub("openalex", search_result=[candidate("openalex", "W1")]),
            ProviderStub("semantic"),
        )
        citation = CitationResolutionExecutor(
            ProviderStub("openalex", lookup_result=[candidate("openalex", "W1", doi="10.1/a")]),
            ProviderStub("semantic"),
        )
        academic_result = await search_academic_works(academic_request(), academic)
        citation_result = await resolve_citation_metadata(
            citation_request(doi="10.1000/exact"), citation
        )
        assert isinstance(academic_result, AcademicSearchExecutionResult)
        assert isinstance(citation_result, CitationResolutionExecutionResult)
        with pytest.raises(ToolUnavailableError):
            await search_academic_works(academic_request(), None)

    run(scenario())


class DecisionClient:
    """Return one real tool-call transport response and record the inference."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def chat(self, messages, tools=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        return self.response


def test_search_agent_preserves_one_inference_and_internal_outcome():
    async def scenario():
        response = LLMChatResponse(
            content=None,
            model="qwen",
            finish_reason="tool_calls",
            tool_calls=(
                LLMToolCall(
                    tool_call_id="call-4b",
                    tool_name="search_academic_works",
                    arguments_json=json.dumps(
                        {"queries": ["scientific evidence"], "limit_per_provider": 5}
                    ),
                ),
            ),
        )
        client = DecisionClient(response)
        executor = AcademicSearchExecutor(
            ProviderStub("openalex", search_result=[candidate("openalex", "W1")]),
            ProviderStub("semantic"),
        )
        outcome = await SearchAgent(client).run_search_decision(
            "A scientific claim.", academic_search_executor=executor
        )
        assert isinstance(outcome, SearchToolExecutionOutcome)
        assert outcome.tool_call_id == "call-4b"
        assert outcome.action_taken.value == "search_academic_works"
        assert isinstance(outcome.tool_execution, AcademicSearchExecutionResult)
        assert len(client.calls) == 1
        assert all(message["role"] != "tool" for message in client.calls[0]["messages"])

    run(scenario())


def test_semantic_scholar_public_and_keyed_execution_through_executor():
    async def scenario():
        seen_headers = []

        async def handler(request):
            seen_headers.append(request.headers.get("x-api-key"))
            return httpx.Response(200, json={"data": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            public_provider = SemanticScholarProvider(
                client, api_key="", public_min_interval_seconds=0
            )
            keyed_provider = SemanticScholarProvider(client, api_key="configured-key")
            await AcademicSearchExecutor(
                ProviderStub("openalex"), public_provider
            ).execute(academic_request())
            await AcademicSearchExecutor(
                ProviderStub("openalex"), keyed_provider
            ).execute(academic_request())
        assert seen_headers == [None, "configured-key"]

    run(scenario())


def test_semantic_429_does_not_discard_openalex_candidates():
    async def scenario():
        async def handler(request):
            return httpx.Response(429, json={"error": "limited"}, headers={"Retry-After": "0"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            semantic = SemanticScholarProvider(
                client, api_key="", public_min_interval_seconds=0
            )
            result = await AcademicSearchExecutor(
                ProviderStub("openalex", search_result=[candidate("openalex", "W1")]),
                semantic,
            ).execute(academic_request())
        assert result.public_result.status is AcademicSearchStatus.PARTIAL_SUCCESS
        assert [item.external_id for item in result.candidates] == ["W1"]
        assert result.public_result.providers[1].error_code == "rate_limited"

    run(scenario())


def test_executors_have_no_database_llm_or_persistence_dependencies():
    import app.services.academic_search_executor as academic_module
    import app.services.citation_resolution_executor as citation_module

    for module in (academic_module, citation_module):
        source = inspect.getsource(module).casefold()
        assert "sqlalchemy" not in source
        assert "session" not in source
        assert "repository" not in source
        assert "searchagent" not in source
        assert ".commit(" not in source


def test_providers_remain_independent_and_do_not_deduplicate_individually():
    import app.providers.openalex_provider as openalex_module
    import app.providers.semantic_scholar_provider as semantic_module

    openalex_source = inspect.getsource(openalex_module).casefold()
    semantic_source = inspect.getsource(semantic_module).casefold()
    assert "semanticscholarprovider" not in openalex_source
    assert "openalexprovider" not in semantic_source
    assert "deduplicate_reference_candidates" not in openalex_source
    assert "deduplicate_reference_candidates" not in semantic_source
