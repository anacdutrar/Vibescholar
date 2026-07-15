"""Isolated tests for asynchronous OpenAlex and Semantic Scholar providers."""

import asyncio
import inspect
import logging
from collections import Counter

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.llm.exceptions import AcademicProviderError, AcademicProviderErrorCode
from app.providers.openalex_provider import OpenAlexProvider, reconstruct_openalex_abstract
from app.providers.semantic_scholar_provider import SemanticScholarProvider
from app.tools.schemas import (
    ReferenceCandidate,
    deduplicate_reference_candidates,
    is_valid_doi,
    normalize_doi,
    normalize_issn,
)


def run(coroutine):
    """Execute one isolated async provider scenario."""
    return asyncio.run(coroutine)


async def no_wait(_: float) -> None:
    """Replace provider backoff in deterministic tests."""


def openalex_work(**overrides) -> dict:
    """Build one representative OpenAlex API payload."""
    work = {
        "id": "https://openalex.org/W123",
        "display_name": "Evidence for Scientific Writing",
        "authorships": [
            {"author": {"display_name": "Ana Silva"}},
            {"author": {"display_name": "Bruno Costa"}},
        ],
        "primary_location": {
            "landing_page_url": "https://publisher.example/work",
            "is_oa": True,
            "source": {
                "display_name": "Journal of Evidence",
                "issn_l": "1234-567X",
                "issn": ["1234-567X", "8765-4321"],
            },
        },
        "publication_year": 2024,
        "doi": "https://doi.org/10.1000/EXAMPLE",
        "abstract_inverted_index": {"Writing": [1], "Scientific": [0], "matters": [2]},
        "language": "en",
        "open_access": {"is_oa": True, "oa_status": "gold"},
        "type": "article",
        "cited_by_count": 12,
        "is_retracted": False,
        "is_paratext": False,
        "relevance_score": 8.5,
    }
    work.update(overrides)
    return work


def semantic_paper(**overrides) -> dict:
    """Build one representative Semantic Scholar API payload."""
    paper = {
        "paperId": "paper-123",
        "title": "Evidence for Scientific Writing",
        "authors": [{"name": "Ana Silva"}, {"name": "Bruno Costa"}],
        "venue": "Journal of Evidence",
        "journal": {"name": "Journal of Evidence", "issn": "1234-567X"},
        "year": 2024,
        "externalIds": {"DOI": "10.1000/EXAMPLE"},
        "abstract": "Scientific writing matters.",
        "url": "https://www.semanticscholar.org/paper/paper-123",
        "openAccessPdf": {"url": "https://example.org/paper.pdf"},
        "publicationTypes": ["JournalArticle"],
        "citationCount": 9,
    }
    paper.update(overrides)
    return paper


def client_for(handler) -> httpx.AsyncClient:
    """Create an injectable client backed only by MockTransport."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_reference_candidate_provider_fields_and_validation():
    candidate = ReferenceCandidate(
        provider="OpenAlex",
        external_id="W1",
        title="Work",
        issn="1234567x",
        eissn="8765-4321",
        issns=["1234-567X", "1234567x"],
        publication_type="article",
        citation_count=0,
        is_open_access=True,
    )
    assert candidate.issn == "1234-567X"
    assert candidate.issns == ("1234-567X",)
    assert candidate.candidate_key == "openalex:w1"
    with pytest.raises(ValidationError):
        ReferenceCandidate(provider="openalex", external_id="W2", citation_count=-1)


def test_normalizers_are_pure_and_canonical():
    assert normalize_doi(" https://doi.org/10.1000/ABC ") == "10.1000/abc"
    assert normalize_doi("doi: 10.1000/ABC") == "10.1000/abc"
    assert is_valid_doi("10.1000/abc") is True
    assert is_valid_doi("not-a-doi") is False
    assert normalize_issn("ISSN: 1234-567X") == "1234-567X"
    assert normalize_issn("invalid") is None


def test_openalex_abstract_reconstruction_handles_order_repetition_and_absence():
    assert reconstruct_openalex_abstract({"beta": [2], "alpha": [0, 1]}) == "alpha alpha beta"
    assert reconstruct_openalex_abstract({"word": [3, -1], "bad": ["x"]}) == "word"
    assert reconstruct_openalex_abstract(None) is None
    assert reconstruct_openalex_abstract({}) is None


def test_openalex_search_normalizes_all_supported_fields():
    async def scenario():
        async def handler(request):
            assert request.url.params["search"] == "scientific writing"
            assert request.url.params["per_page"] == "3"
            assert request.url.params["api_key"] == "openalex-secret"
            return httpx.Response(200, json={"results": [openalex_work()]})

        async with client_for(handler) as client:
            provider = OpenAlexProvider(client, api_key="openalex-secret", sleep=no_wait)
            results = await provider.search_works(" scientific   writing ", 3)
        candidate = results[0]
        assert candidate.external_id == "W123"
        assert candidate.provider == "openalex"
        assert candidate.authors == ["Ana Silva", "Bruno Costa"]
        assert candidate.journal == "Journal of Evidence"
        assert candidate.year == 2024
        assert candidate.doi == "10.1000/example"
        assert candidate.abstract == "Scientific Writing matters"
        assert candidate.language == "en"
        assert candidate.source_url == "https://publisher.example/work"
        assert candidate.availability == "gold"
        assert candidate.is_open_access is True
        assert candidate.issn == "1234-567X"
        assert candidate.issns == ("1234-567X", "8765-4321")
        assert candidate.publication_type == "article"
        assert candidate.citation_count == 12

    run(scenario())


def test_openalex_ignores_invalid_works_but_leaves_deduplication_to_executor():
    async def scenario():
        payload = {
            "results": [
                openalex_work(display_name=""),
                openalex_work(id="W2", is_retracted=True),
                openalex_work(id="W3", is_paratext=True),
                openalex_work(),
                openalex_work(id="W999"),
            ]
        }
        async with client_for(lambda request: httpx.Response(200, json=payload)) as client:
            results = await OpenAlexProvider(client, api_key="key", sleep=no_wait).search_works("q", 15)
        assert len(results) == 2
        assert results[0].candidate_key == results[1].candidate_key

    run(scenario())


def test_openalex_lookup_prioritizes_direct_doi_and_404_is_empty():
    async def scenario():
        paths = []

        async def handler(request):
            paths.append(request.url.path)
            if "missing" in request.url.path:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json=openalex_work())

        async with client_for(handler) as client:
            provider = OpenAlexProvider(client, api_key="key", sleep=no_wait)
            found = await provider.lookup(doi="https://doi.org/10.1000/example", title="ignored")
            missing = await provider.lookup(doi="10.1000/missing")
        assert found[0].doi == "10.1000/example"
        assert missing == []
        assert paths[0].endswith("/works/doi:10.1000/example")

    run(scenario())


def test_openalex_lookup_by_title_and_author_year_uses_one_search_each():
    async def scenario():
        queries = []

        async def handler(request):
            queries.append(dict(request.url.params))
            return httpx.Response(200, json={"results": [openalex_work()]})

        async with client_for(handler) as client:
            provider = OpenAlexProvider(client, api_key="key", sleep=no_wait)
            await provider.lookup(title="A title", authors=["ignored"], year=2024)
            await provider.lookup(authors=["Ana Silva"], year=2023)
        assert queries[0]["search"] == "A title"
        assert queries[0]["filter"] == "publication_year:2024"
        assert queries[1]["search"] == "Ana Silva 2023"
        assert len(queries) == 2

    run(scenario())


def test_openalex_basic_search_works_without_key_and_omits_parameter():
    async def scenario():
        async def handler(request):
            assert "api_key" not in request.url.params
            return httpx.Response(200, json={"results": []})

        async with client_for(handler) as client:
            provider = OpenAlexProvider(client, api_key="", sleep=no_wait)
            assert await provider.search_works("query", 1) == []

    run(scenario())


def test_openalex_singleton_lookup_without_key_uses_official_short_doi_path():
    async def scenario():
        async def handler(request):
            assert request.url.raw_path.split(b"?", 1)[0] == b"/works/doi:10.1000/example"
            assert "api_key" not in request.url.params
            return httpx.Response(200, json=openalex_work())

        async with client_for(handler) as client:
            provider = OpenAlexProvider(client, api_key="", sleep=no_wait)
            result = await provider.lookup(doi="https://doi.org/10.1000/EXAMPLE")
        assert len(result) == 1

    run(scenario())


def test_openalex_doi_path_percent_encodes_reserved_suffix_characters(caplog):
    async def scenario():
        expected = (
            b"/works/doi:10.1002/%28sici%291099-0844%28199912%2917%3A4"
            b"%3C290%3A%3Aaid-cbf849%3E3.0.co%3B2-p"
        )

        async def handler(request):
            assert request.url.raw_path.split(b"?", 1)[0] == expected
            return httpx.Response(404, json={"error": "not found"})

        doi = "10.1002/(SICI)1099-0844(199912)17:4<290::AID-CBF849>3.0.CO;2-P"
        async with client_for(handler) as client:
            provider = OpenAlexProvider(client, api_key="", sleep=no_wait)
            with caplog.at_level(logging.INFO):
                assert await provider.lookup(doi=doi) == []
        assert doi.casefold() not in caplog.text.casefold()
        assert "aid-cbf849" not in caplog.text.casefold()

    run(scenario())


def test_openalex_singleton_lookup_with_key_uses_official_query_parameter():
    async def scenario():
        async def handler(request):
            assert request.url.params["api_key"] == "configured-key"
            assert request.url.raw_path.split(b"?", 1)[0] == b"/works/doi:10.1000/example"
            return httpx.Response(200, json=openalex_work())

        async with client_for(handler) as client:
            provider = OpenAlexProvider(client, api_key="configured-key", sleep=no_wait)
            assert await provider.lookup(doi="doi:10.1000/example")

    run(scenario())


def test_provider_construction_is_lazy_for_the_legacy_mock_flow():
    openalex = OpenAlexProvider(api_key="")
    semantic = SemanticScholarProvider(api_key="")
    assert openalex._client is None
    assert semantic._client is None


def test_semantic_scholar_public_search_and_normalization():
    async def scenario():
        async def handler(request):
            assert "x-api-key" not in request.headers
            assert request.url.params["limit"] == "2"
            return httpx.Response(200, json={"data": [semantic_paper()]})

        async with client_for(handler) as client:
            provider = SemanticScholarProvider(
                client, api_key="", sleep=no_wait, public_min_interval_seconds=0
            )
            results = await provider.search_works("scientific writing", 2)
        candidate = results[0]
        assert candidate.external_id == "paper-123"
        assert candidate.provider == "semantic_scholar"
        assert candidate.doi == "10.1000/example"
        assert candidate.authors == ["Ana Silva", "Bruno Costa"]
        assert candidate.journal == "Journal of Evidence"
        assert candidate.abstract == "Scientific writing matters."
        assert candidate.source_url.endswith("paper-123")
        assert candidate.is_open_access is True
        assert candidate.publication_type == "JournalArticle"
        assert candidate.citation_count == 9

    run(scenario())


def test_semantic_scholar_uses_official_api_key_header_without_leaking_it():
    async def scenario():
        secret = "semantic-secret"

        async def handler(request):
            assert request.headers["x-api-key"] == secret
            assert secret not in str(request.url)
            return httpx.Response(200, json={"data": []})

        async with client_for(handler) as client:
            provider = SemanticScholarProvider(client, api_key=secret, sleep=no_wait)
            assert await provider.search_works("query", 1) == []
            assert secret not in repr(provider)

    run(scenario())


def test_semantic_scholar_lookup_by_doi_and_empty_response():
    async def scenario():
        paths = []

        async def handler(request):
            paths.append(request.url.path)
            if "missing" in request.url.path:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json=semantic_paper())

        async with client_for(handler) as client:
            provider = SemanticScholarProvider(
                client, api_key="", sleep=no_wait, public_min_interval_seconds=0
            )
            found = await provider.lookup(doi="doi:10.1000/example")
            missing = await provider.lookup(doi="10.1000/missing")
        assert found[0].external_id == "paper-123"
        assert missing == []
        assert paths[0].endswith("/paper/DOI:10.1000/example")

    run(scenario())


def test_semantic_scholar_title_and_author_year_lookup_are_bounded():
    async def scenario():
        params_seen = []

        async def handler(request):
            params_seen.append(dict(request.url.params))
            return httpx.Response(200, json={"data": []})

        async with client_for(handler) as client:
            provider = SemanticScholarProvider(
                client, api_key="key", sleep=no_wait, public_min_interval_seconds=0
            )
            await provider.lookup(title="Exact title", authors=["ignored"], year=2022)
            await provider.lookup(authors=["Ana Silva"], year=2021)
        assert params_seen[0]["query"] == "Exact title"
        assert params_seen[0]["year"] == "2022"
        assert params_seen[1]["query"] == "Ana Silva 2021"

    run(scenario())


@pytest.mark.parametrize(
    ("provider_kind", "status", "expected", "attempts"),
    [
        ("openalex", 401, AcademicProviderErrorCode.UNAUTHORIZED, 1),
        ("openalex", 403, AcademicProviderErrorCode.FORBIDDEN, 1),
        ("openalex", 429, AcademicProviderErrorCode.RATE_LIMITED, 2),
        ("openalex", 503, AcademicProviderErrorCode.SERVICE_UNAVAILABLE, 2),
        ("semantic", 401, AcademicProviderErrorCode.UNAUTHORIZED, 1),
        ("semantic", 403, AcademicProviderErrorCode.FORBIDDEN, 1),
        ("semantic", 429, AcademicProviderErrorCode.RATE_LIMITED, 2),
        ("semantic", 502, AcademicProviderErrorCode.SERVICE_UNAVAILABLE, 2),
    ],
)
def test_safe_http_error_mapping_and_retry_limits(provider_kind, status, expected, attempts):
    async def scenario():
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(status, json={"sensitive": "must not escape"})

        async with client_for(handler) as client:
            if provider_kind == "openalex":
                provider = OpenAlexProvider(client, api_key="secret", sleep=no_wait)
            else:
                provider = SemanticScholarProvider(
                    client, api_key="secret", sleep=no_wait, public_min_interval_seconds=0
                )
            with pytest.raises(AcademicProviderError) as captured:
                await provider.search_works("query", 1)
        assert captured.value.code is expected
        assert calls == attempts
        assert "secret" not in str(captured.value)
        assert "must not escape" not in str(captured.value)

    run(scenario())


@pytest.mark.parametrize("provider_kind", ["openalex", "semantic"])
def test_timeout_retries_once_and_connection_error_does_not_retry(provider_kind):
    async def scenario():
        timeout_calls = 0

        async def timeout_handler(request):
            nonlocal timeout_calls
            timeout_calls += 1
            raise httpx.ReadTimeout("private timeout detail", request=request)

        async with client_for(timeout_handler) as client:
            provider = (
                OpenAlexProvider(client, api_key="key", sleep=no_wait)
                if provider_kind == "openalex"
                else SemanticScholarProvider(
                    client, api_key="", sleep=no_wait, public_min_interval_seconds=0
                )
            )
            with pytest.raises(AcademicProviderError) as captured:
                await provider.search_works("query", 1)
        assert captured.value.code is AcademicProviderErrorCode.TIMEOUT
        assert timeout_calls == 2

        connection_calls = 0

        async def connection_handler(request):
            nonlocal connection_calls
            connection_calls += 1
            raise httpx.ConnectError("private transport detail", request=request)

        async with client_for(connection_handler) as client:
            provider = (
                OpenAlexProvider(client, api_key="key", sleep=no_wait)
                if provider_kind == "openalex"
                else SemanticScholarProvider(
                    client, api_key="", sleep=no_wait, public_min_interval_seconds=0
                )
            )
            with pytest.raises(AcademicProviderError) as captured:
                await provider.search_works("query", 1)
        assert captured.value.code is AcademicProviderErrorCode.CONNECTION_ERROR
        assert connection_calls == 1

    run(scenario())


@pytest.mark.parametrize("provider_kind", ["openalex", "semantic"])
def test_invalid_json_is_controlled_and_not_retried(provider_kind):
    async def scenario():
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, content=b"not-json")

        async with client_for(handler) as client:
            provider = (
                OpenAlexProvider(client, api_key="key", sleep=no_wait)
                if provider_kind == "openalex"
                else SemanticScholarProvider(
                    client, api_key="", sleep=no_wait, public_min_interval_seconds=0
                )
            )
            with pytest.raises(AcademicProviderError) as captured:
                await provider.search_works("query", 1)
        assert captured.value.code is AcademicProviderErrorCode.INVALID_RESPONSE
        assert calls == 1

    run(scenario())


def test_bad_request_is_not_retried():
    async def scenario():
        calls = Counter()

        async def handler(request):
            calls["count"] += 1
            return httpx.Response(400, json={"error": "bad request"})

        async with client_for(handler) as client:
            provider = SemanticScholarProvider(
                client, api_key="", sleep=no_wait, public_min_interval_seconds=0
            )
            with pytest.raises(AcademicProviderError):
                await provider.search_works("query", 1)
        assert calls["count"] == 1

    run(scenario())


def test_semantic_scholar_serializes_requests_in_one_process():
    async def scenario():
        active = 0
        maximum = 0

        async def handler(request):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return httpx.Response(200, json={"data": []})

        async with client_for(handler) as client:
            provider = SemanticScholarProvider(
                client, api_key="", sleep=no_wait, public_min_interval_seconds=0
            )
            await asyncio.gather(
                provider.search_works("first", 1),
                provider.search_works("second", 1),
            )
        assert maximum == 1

    run(scenario())


def test_semantic_public_interval_is_async_and_replaceable():
    async def scenario():
        waits = []
        moments = iter([0.0, 0.25, 0.25])

        async def record_wait(delay):
            waits.append(delay)

        async with client_for(lambda request: httpx.Response(200, json={"data": []})) as client:
            provider = SemanticScholarProvider(
                client,
                api_key="",
                sleep=record_wait,
                clock=lambda: next(moments),
                public_min_interval_seconds=1.0,
            )
            await provider.search_works("first", 1)
            await provider.search_works("second", 1)
        assert waits == [0.75]

    run(scenario())


def test_transient_deduplication_prefers_and_merges_complete_candidate():
    sparse = ReferenceCandidate(
        provider="openalex",
        external_id="W1",
        title="A Study",
        year=2024,
        doi="10.1000/same",
        authors=["Ana"],
    )
    complete = ReferenceCandidate(
        provider="semantic_scholar",
        external_id="P1",
        title="A Study",
        year=2024,
        doi="https://doi.org/10.1000/SAME",
        authors=["Ana", "Bruno"],
        abstract="Complete abstract.",
        source_url="https://example.org/work",
        issns=("1234-567X",),
        citation_count=4,
    )
    result = deduplicate_reference_candidates([sparse, complete])
    assert len(result) == 1
    assert result[0].abstract == "Complete abstract."
    assert result[0].authors == ["Ana", "Bruno"]
    assert result[0].issns == ("1234-567X",)


def test_transient_deduplication_falls_back_to_normalized_title_and_year():
    first = ReferenceCandidate(provider="openalex", external_id="W1", title="Neural: Networks!", year=2020)
    second = ReferenceCandidate(
        provider="semantic_scholar",
        external_id="P1",
        title=" neural networks ",
        year=2020,
        abstract="Metadata retained.",
    )
    assert len(deduplicate_reference_candidates([first, second])) == 1


def test_limits_are_clamped_and_empty_lists_are_valid():
    async def scenario():
        seen = []

        async def handler(request):
            seen.append(dict(request.url.params))
            body = {"results": []} if "openalex" in request.url.host else {"data": []}
            return httpx.Response(200, json=body)

        async with client_for(handler) as client:
            openalex = OpenAlexProvider(
                client, base_url="https://api.openalex.org", api_key="key", sleep=no_wait
            )
            semantic = SemanticScholarProvider(
                client,
                base_url="https://api.semanticscholar.org/graph/v1",
                api_key="",
                sleep=no_wait,
                public_min_interval_seconds=0,
            )
            assert await openalex.search_works("query", settings.RESULTS_PER_PROVIDER + 10) == []
            assert await semantic.search_works("query", settings.RESULTS_PER_PROVIDER + 10) == []
        assert all(
            str(settings.RESULTS_PER_PROVIDER) in {item.get("per_page"), item.get("limit")}
            for item in seen
        )

    run(scenario())


def test_provider_modules_have_no_orm_persistence_or_blocking_sleep():
    import app.providers.openalex_provider as openalex_module
    import app.providers.semantic_scholar_provider as semantic_module

    for module in (openalex_module, semantic_module):
        source = inspect.getsource(module).casefold()
        assert "sqlalchemy" not in source
        assert "projectreference" not in source
        assert "evidencesuggestion" not in source
        assert "time.sleep" not in source
        assert ".commit(" not in source


def test_api_keys_do_not_appear_in_provider_logs_or_errors(caplog):
    async def scenario():
        secret = "provider-private-key"
        async with client_for(lambda request: httpx.Response(401, json={"key": secret})) as client:
            provider = OpenAlexProvider(client, api_key=secret, sleep=no_wait)
            with caplog.at_level(logging.INFO):
                with pytest.raises(AcademicProviderError) as captured:
                    await provider.search_works("private query", 1)
        assert secret not in str(captured.value)
        assert secret not in repr(provider)
        assert secret not in caplog.text
        assert "private query" not in caplog.text

    run(scenario())
