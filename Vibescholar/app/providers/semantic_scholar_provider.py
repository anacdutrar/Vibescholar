"""Asynchronous access to the official Semantic Scholar Academic Graph API."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from app.core.config import settings
from app.llm.exceptions import AcademicProviderError, AcademicProviderErrorCode
from app.tools.schemas import (
    ReferenceCandidate,
    is_valid_doi,
    normalize_authors,
    normalize_doi,
    normalize_issn,
)

logger = logging.getLogger(__name__)

_PAPER_FIELDS = ",".join(
    (
        "paperId", "title", "authors", "venue", "journal", "year", "externalIds",
        "abstract", "url", "openAccessPdf", "publicationTypes", "citationCount",
    )
)
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


class SemanticScholarProvider:
    """Normalize Semantic Scholar paper responses into transient candidates."""

    provider_name = "semantic_scholar"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        public_min_interval_seconds: float = 1.0,
    ) -> None:
        self._base_url = (base_url or settings.SEMANTIC_SCHOLAR_BASE_URL).rstrip("/")
        self._api_key = settings.SEMANTIC_SCHOLAR_API_KEY if api_key is None else api_key
        self._timeout = timeout_seconds or settings.ACADEMIC_PROVIDER_TIMEOUT_SECONDS
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep
        self._clock = clock
        self._minimum_interval = 0.0 if self._api_key else max(public_min_interval_seconds, 0.0)
        self._request_lock = asyncio.Lock()
        self._last_request_started: float | None = None

    def __repr__(self) -> str:
        """Return a credential-free diagnostic representation."""
        return "SemanticScholarProvider(api_key=<redacted>)"

    async def aclose(self) -> None:
        """Close the internally owned HTTP client."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http_client(self) -> httpx.AsyncClient:
        """Create one reusable client lazily when no client was injected."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def search_works(self, query: str, limit: int) -> list[ReferenceCandidate]:
        """Search the paper relevance endpoint once with a bounded result count."""
        query = " ".join(query.strip().split())
        if not query:
            raise ValueError("query must not be empty")
        effective_limit = self._validated_limit(limit)
        payload = await self._request(
            "search",
            "/paper/search",
            params={"query": query, "limit": effective_limit, "fields": _PAPER_FIELDS},
        )
        results = payload.get("data", []) if payload else []
        if not isinstance(results, list):
            raise self._error("search", AcademicProviderErrorCode.INVALID_RESPONSE)
        candidates = self._normalize_many(results, effective_limit)
        logger.info(
            "academic_provider.completed provider=%s operation=search status=success received=%d normalized=%d",
            self.provider_name,
            len(results),
            len(candidates),
        )
        return candidates

    async def lookup(
        self,
        *,
        doi: str | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
        year: int | None = None,
        limit: int = 5,
    ) -> list[ReferenceCandidate]:
        """Resolve metadata by DOI, then title, then author/year using one request."""
        effective_limit = self._validated_limit(limit)
        normalized_doi = normalize_doi(doi) if is_valid_doi(doi) else None
        if normalized_doi:
            payload = await self._request(
                "lookup",
                f"/paper/DOI:{normalized_doi}",
                params={"fields": _PAPER_FIELDS},
                not_found_is_empty=True,
            )
            return self._normalize_many([payload] if payload else [], effective_limit)

        clean_title = " ".join((title or "").strip().split())
        clean_authors = normalize_authors(authors)
        if clean_title:
            query = clean_title
        elif clean_authors and year is not None:
            query = " ".join((*clean_authors, str(year)))
        else:
            raise ValueError("lookup requires DOI, title, or authors with year")
        params: dict[str, Any] = {
            "query": query,
            "limit": effective_limit,
            "fields": _PAPER_FIELDS,
        }
        if year is not None:
            params["year"] = str(year)
        payload = await self._request("lookup", "/paper/search", params=params)
        results = payload.get("data", []) if payload else []
        if not isinstance(results, list):
            raise self._error("lookup", AcademicProviderErrorCode.INVALID_RESPONSE)
        return self._normalize_many(results, effective_limit)

    @staticmethod
    def _validated_limit(limit: int) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return min(limit, settings.RESULTS_PER_PROVIDER)

    async def _request(
        self,
        operation: str,
        path: str,
        *,
        params: Mapping[str, Any],
        not_found_is_empty: bool = False,
    ) -> dict[str, Any] | None:
        started = time.perf_counter()
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        async with self._request_lock:
            for attempt in range(2):
                await self._wait_for_request_slot()
                try:
                    response = await self._http_client().get(
                        f"{self._base_url}{path}",
                        params=dict(params),
                        headers=headers,
                    )
                except httpx.TimeoutException as exc:
                    if attempt == 0:
                        logger.info(
                            "academic_provider.retry provider=%s operation=%s code=timeout retry=true",
                            self.provider_name,
                            operation,
                        )
                        continue
                    raise self._error(operation, AcademicProviderErrorCode.TIMEOUT) from exc
                except httpx.RequestError as exc:
                    raise self._error(operation, AcademicProviderErrorCode.CONNECTION_ERROR) from exc

                if response.status_code in _RETRYABLE_STATUS_CODES and attempt == 0:
                    logger.info(
                        "academic_provider.retry provider=%s operation=%s code=%s retry=true",
                        self.provider_name,
                        operation,
                        self._status_error_code(response.status_code).value,
                    )
                    await self._sleep(self._retry_delay(response))
                    continue
                if response.status_code == 404 and not_found_is_empty:
                    return None
                if response.status_code != 200:
                    raise self._error(
                        operation,
                        self._status_error_code(response.status_code),
                        response.status_code,
                    )
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise self._error(operation, AcademicProviderErrorCode.INVALID_RESPONSE) from exc
                if not isinstance(payload, dict):
                    raise self._error(operation, AcademicProviderErrorCode.INVALID_RESPONSE)
                logger.info(
                    "academic_provider.request provider=%s operation=%s duration=%.4f status=success retry=%s",
                    self.provider_name,
                    operation,
                    time.perf_counter() - started,
                    attempt > 0,
                )
                return payload
        raise self._error(operation, AcademicProviderErrorCode.UNKNOWN)

    async def _wait_for_request_slot(self) -> None:
        now = self._clock()
        if self._last_request_started is not None:
            remaining = self._minimum_interval - (now - self._last_request_started)
            if remaining > 0:
                await self._sleep(remaining)
                now = self._clock()
        self._last_request_started = now

    @staticmethod
    def _retry_delay(response: httpx.Response) -> float:
        value = response.headers.get("Retry-After", "")
        try:
            return min(max(float(value), 0.0), 60.0)
        except ValueError:
            return 0.25

    @staticmethod
    def _status_error_code(status_code: int) -> AcademicProviderErrorCode:
        if status_code == 401:
            return AcademicProviderErrorCode.UNAUTHORIZED
        if status_code == 403:
            return AcademicProviderErrorCode.FORBIDDEN
        if status_code == 404:
            return AcademicProviderErrorCode.NOT_FOUND
        if status_code == 429:
            return AcademicProviderErrorCode.RATE_LIMITED
        if status_code >= 500:
            return AcademicProviderErrorCode.SERVICE_UNAVAILABLE
        return AcademicProviderErrorCode.UNKNOWN

    def _error(
        self,
        operation: str,
        code: AcademicProviderErrorCode,
        status_code: int | None = None,
    ) -> AcademicProviderError:
        logger.warning(
            "academic_provider.failed provider=%s operation=%s code=%s",
            self.provider_name,
            operation,
            code.value,
        )
        return AcademicProviderError(
            self.provider_name,
            operation,
            code,
            status_code=status_code,
        )

    def _normalize_many(
        self,
        papers: list[Any],
        limit: int,
    ) -> list[ReferenceCandidate]:
        candidates: list[ReferenceCandidate] = []
        for paper in papers:
            candidate = self._normalize_paper(paper)
            if candidate is not None:
                candidates.append(candidate)
        return candidates[:limit]

    def _normalize_paper(self, paper: Any) -> ReferenceCandidate | None:
        if not isinstance(paper, Mapping):
            return None
        title = " ".join(str(paper.get("title") or "").split())
        if not title:
            return None
        external_ids = paper.get("externalIds") or {}
        if not isinstance(external_ids, Mapping):
            external_ids = {}
        journal = paper.get("journal") or {}
        if not isinstance(journal, Mapping):
            journal = {}
        open_access_pdf = paper.get("openAccessPdf")
        has_open_access = isinstance(open_access_pdf, Mapping) and bool(open_access_pdf.get("url"))
        publication_types = paper.get("publicationTypes") or []
        if not isinstance(publication_types, list):
            publication_types = []
        authors = [
            author.get("name", "")
            for author in paper.get("authors") or []
            if isinstance(author, Mapping)
        ]
        issn = normalize_issn(journal.get("issn"))
        return ReferenceCandidate(
            external_id=paper.get("paperId"),
            provider=self.provider_name,
            title=title,
            authors=authors,
            journal=journal.get("name") or paper.get("venue"),
            year=paper.get("year"),
            doi=normalize_doi(external_ids.get("DOI")),
            abstract=paper.get("abstract"),
            availability="open_access" if has_open_access else "closed",
            language=paper.get("language"),
            source_url=paper.get("url"),
            issn=issn,
            eissn=None,
            issns=(issn,) if issn else (),
            publication_type=publication_types[0] if publication_types else None,
            citation_count=paper.get("citationCount"),
            is_open_access=has_open_access,
        )
