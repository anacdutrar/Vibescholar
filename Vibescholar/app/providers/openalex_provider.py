"""Asynchronous access to the official OpenAlex Works API."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote

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
# httpx logs complete request URLs at INFO; OpenAlex requires its key in the query string.
logging.getLogger("httpx").setLevel(logging.WARNING)

_WORK_FIELDS = ",".join(
    (
        "id", "display_name", "authorships", "primary_location", "publication_year",
        "doi", "abstract_inverted_index", "language", "open_access", "type",
        "cited_by_count", "is_retracted", "is_paratext", "relevance_score",
    )
)
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

# Current OpenAlex policy permits anonymous basic search and free singleton lookup
# within the smaller no-key daily budget. A key is optional here and increases that
# budget. Key-required semantic search and content-download operations are not part
# of this provider.


def reconstruct_openalex_abstract(
    inverted_index: Mapping[str, list[int]] | None,
) -> str | None:
    """Reconstruct plaintext from OpenAlex token positions without inventing words."""
    if not inverted_index:
        return None
    positioned: dict[int, str] = {}
    for token, positions in inverted_index.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                positioned.setdefault(position, token)
    if not positioned:
        return None
    return " ".join(positioned[position] for position in sorted(positioned))


class OpenAlexProvider:
    """Normalize OpenAlex search and lookup responses into transient candidates."""

    provider_name = "openalex"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = (base_url or settings.OPENALEX_BASE_URL).rstrip("/")
        self._api_key = settings.OPENALEX_API_KEY if api_key is None else api_key
        self._timeout = timeout_seconds or settings.ACADEMIC_PROVIDER_TIMEOUT_SECONDS
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep

    def __repr__(self) -> str:
        """Return a credential-free diagnostic representation."""
        return "OpenAlexProvider(api_key=<redacted>)"

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
        """Search OpenAlex works once and return normalized, local-only candidates."""
        query = self._validated_query(query)
        effective_limit = self._validated_limit(limit)
        payload = await self._request(
            "search",
            "/works",
            params={
                "search": query,
                "per_page": effective_limit,
                "select": _WORK_FIELDS,
            },
        )
        results = payload.get("results", []) if payload else []
        if not isinstance(results, list):
            raise self._error("search", AcademicProviderErrorCode.INVALID_RESPONSE)
        candidates = self._normalize_many(results, effective_limit)
        logger.info(
            "ai.pipeline.provider.completed provider=%s operation=search status=success received=%d normalized=%d",
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
        started_at = time.perf_counter()
        effective_limit = self._validated_limit(limit)
        normalized_doi = normalize_doi(doi) if is_valid_doi(doi) else None
        if normalized_doi:
            encoded_doi = quote(normalized_doi, safe="/")
            payload = await self._request(
                "lookup",
                f"/works/doi:{encoded_doi}",
                params={"select": _WORK_FIELDS},
                not_found_is_empty=True,
            )
            candidates = self._normalize_many(
                [payload] if payload else [], effective_limit
            )
            logger.info(
                "ai.pipeline.provider.completed provider=%s operation=lookup criterion=doi "
                "status=success normalized=%d duration=%.4f",
                self.provider_name,
                len(candidates),
                time.perf_counter() - started_at,
            )
            return candidates

        clean_title = " ".join((title or "").strip().split())
        clean_authors = normalize_authors(authors)
        if clean_title:
            query = clean_title
        elif clean_authors and year is not None:
            query = " ".join((*clean_authors, str(year)))
        else:
            raise ValueError("lookup requires DOI, title, or authors with year")

        params: dict[str, Any] = {
            "search": query,
            "per_page": effective_limit,
            "select": _WORK_FIELDS,
        }
        if year is not None:
            params["filter"] = f"publication_year:{year}"
        payload = await self._request("lookup", "/works", params=params)
        results = payload.get("results", []) if payload else []
        if not isinstance(results, list):
            raise self._error("lookup", AcademicProviderErrorCode.INVALID_RESPONSE)
        candidates = self._normalize_many(results, effective_limit)
        logger.info(
            "ai.pipeline.provider.completed provider=%s operation=lookup criterion=%s "
            "status=success received=%d normalized=%d duration=%.4f",
            self.provider_name,
            "title" if clean_title else "author_year",
            len(results),
            len(candidates),
            time.perf_counter() - started_at,
        )
        return candidates

    def _validated_query(self, query: str) -> str:
        query = " ".join(query.strip().split())
        if not query:
            raise ValueError("query must not be empty")
        return query

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
        request_params = dict(params)
        if self._api_key:
            request_params["api_key"] = self._api_key
        started = time.perf_counter()
        for attempt in range(2):
            try:
                response = await self._http_client().get(
                    f"{self._base_url}{path}",
                    params=request_params,
                )
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    logger.info(
                        "ai.pipeline.provider.retry provider=%s operation=%s code=timeout retry=true",
                        self.provider_name,
                        operation,
                    )
                    await self._sleep(0)
                    continue
                raise self._error(operation, AcademicProviderErrorCode.TIMEOUT) from exc
            except httpx.RequestError as exc:
                raise self._error(operation, AcademicProviderErrorCode.CONNECTION_ERROR) from exc

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt == 0:
                logger.info(
                    "ai.pipeline.provider.retry provider=%s operation=%s code=%s retry=true",
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
                "ai.pipeline.provider.request provider=%s operation=%s duration=%.4f status=success retry=%s",
                self.provider_name,
                operation,
                time.perf_counter() - started,
                attempt > 0,
            )
            return payload
        raise self._error(operation, AcademicProviderErrorCode.UNKNOWN)

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
            "ai.pipeline.provider.failed provider=%s operation=%s code=%s",
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
        works: list[Any],
        limit: int,
    ) -> list[ReferenceCandidate]:
        candidates: list[ReferenceCandidate] = []
        for work in works:
            candidate = self._normalize_work(work)
            if candidate is not None:
                candidates.append(candidate)
        return candidates[:limit]

    def _normalize_work(self, work: Any) -> ReferenceCandidate | None:
        if not isinstance(work, Mapping) or work.get("is_retracted") or work.get("is_paratext"):
            return None
        title = " ".join(str(work.get("display_name") or work.get("title") or "").split())
        if not title:
            return None
        primary_location = work.get("primary_location") or {}
        if not isinstance(primary_location, Mapping):
            primary_location = {}
        source = primary_location.get("source") or {}
        if not isinstance(source, Mapping):
            source = {}
        open_access = work.get("open_access") or {}
        if not isinstance(open_access, Mapping):
            open_access = {}
        authors = []
        for authorship in work.get("authorships") or []:
            if isinstance(authorship, Mapping) and isinstance(authorship.get("author"), Mapping):
                authors.append(authorship["author"].get("display_name", ""))

        source_issns = tuple(
            value
            for value in (normalize_issn(item) for item in source.get("issn") or [])
            if value
        )
        work_id = str(work.get("id") or "").strip()
        external_id = work_id.rsplit("/", 1)[-1] if work_id else None
        is_oa = open_access.get("is_oa")
        if is_oa is None:
            is_oa = primary_location.get("is_oa")
        return ReferenceCandidate(
            external_id=external_id,
            provider=self.provider_name,
            title=title,
            authors=authors,
            journal=source.get("display_name"),
            year=work.get("publication_year"),
            doi=normalize_doi(work.get("doi")),
            abstract=reconstruct_openalex_abstract(work.get("abstract_inverted_index")),
            availability=open_access.get("oa_status"),
            language=work.get("language"),
            source_url=primary_location.get("landing_page_url") or work_id or None,
            provider_relevance_score=work.get("relevance_score"),
            issn=source.get("issn_l"),
            eissn=None,
            issns=source_issns,
            publication_type=work.get("type"),
            citation_count=work.get("cited_by_count"),
            is_open_access=is_oa if isinstance(is_oa, bool) else None,
        )
