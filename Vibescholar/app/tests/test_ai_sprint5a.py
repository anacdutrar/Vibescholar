"""Isolated tests for deterministic transient reference filtering."""

import ast
import inspect

import pytest
from pydantic import ValidationError

from app.services.reference_filter_service import (
    FilterReason,
    ReferenceFilterCriteria,
    ReferenceFilterService,
)
from app.tools.schemas import ReferenceCandidate


def candidate(
    external_id: str,
    *,
    year: int | None = 2024,
    is_open_access: bool | None = True,
    doi: str | None = None,
    abstract: str | None = None,
) -> ReferenceCandidate:
    """Build one frozen transient candidate with stable identity."""
    return ReferenceCandidate(
        external_id=external_id,
        provider="test_provider",
        title=f"Reference {external_id}",
        authors=["Test Author"],
        year=year,
        doi=doi,
        abstract=abstract,
        source_url=f"https://example.test/{external_id}",
        provider_relevance_score=0.9,
        is_open_access=is_open_access,
    )


def test_empty_list_produces_coherent_empty_result():
    result = ReferenceFilterService().filter_candidates([], ReferenceFilterCriteria())

    assert result.accepted == []
    assert result.rejected == []
    assert result.total_received == result.total_accepted == result.total_rejected == 0
    assert result.reason_counts == {}


def test_all_candidates_are_accepted_without_enabled_filters():
    candidates = [candidate("one"), candidate("two", is_open_access=False)]

    result = ReferenceFilterService().filter_candidates(candidates, ReferenceFilterCriteria())

    assert result.accepted == candidates
    assert result.total_accepted == 2
    assert result.total_rejected == 0


@pytest.mark.parametrize(
    ("criteria", "item", "reason"),
    [
        (
            ReferenceFilterCriteria(publication_year_min=2020),
            candidate("old", year=2019),
            FilterReason.PUBLICATION_BEFORE_MINIMUM,
        ),
        (
            ReferenceFilterCriteria(publication_year_max=2020),
            candidate("future", year=2021),
            FilterReason.PUBLICATION_AFTER_MAXIMUM,
        ),
        (
            ReferenceFilterCriteria(only_open_access=True),
            candidate("closed", is_open_access=False),
            FilterReason.NOT_OPEN_ACCESS,
        ),
    ],
)
def test_each_effective_filter_has_a_typed_rejection(criteria, item, reason):
    result = ReferenceFilterService().filter_candidates([item], criteria)

    assert result.accepted == []
    assert result.rejected[0].candidate_key == item.candidate_key
    assert result.rejected[0].reasons == (reason,)
    assert result.reason_counts == {reason: 1}


def test_unknown_year_and_open_access_are_not_assumed_to_fail():
    unknown = candidate("unknown", year=None, is_open_access=None)
    criteria = ReferenceFilterCriteria(
        publication_year_min=2020,
        publication_year_max=2024,
        only_open_access=True,
    )

    result = ReferenceFilterService().filter_candidates([unknown], criteria)

    assert result.accepted == [unknown]
    assert result.rejected == []


def test_candidate_can_have_multiple_rejection_reasons():
    item = candidate("old-closed", year=2018, is_open_access=False)
    criteria = ReferenceFilterCriteria(publication_year_min=2020, only_open_access=True)

    result = ReferenceFilterService().filter_candidates([item], criteria)

    assert result.rejected[0].reasons == (
        FilterReason.PUBLICATION_BEFORE_MINIMUM,
        FilterReason.NOT_OPEN_ACCESS,
    )
    assert result.reason_counts == {
        FilterReason.PUBLICATION_BEFORE_MINIMUM: 1,
        FilterReason.NOT_OPEN_ACCESS: 1,
    }


def test_relative_order_identity_and_candidate_data_are_preserved_without_mutation():
    first = candidate("first")
    rejected = candidate("rejected", year=2010)
    last = candidate("last")
    candidates = [first, rejected, last]
    snapshots = [item.model_dump() for item in candidates]

    result = ReferenceFilterService().filter_candidates(
        candidates,
        ReferenceFilterCriteria(publication_year_min=2020),
    )

    assert result.accepted == [first, last]
    assert result.rejected[0].candidate_key == rejected.candidate_key
    assert [item.model_dump() for item in candidates] == snapshots
    assert result.accepted[0] is first
    assert result.accepted[1] is last


def test_counts_partition_each_candidate_once_and_reason_counts_are_coherent():
    accepted = candidate("accepted")
    old = candidate("old", year=2010)
    closed = candidate("closed", is_open_access=False)

    result = ReferenceFilterService().filter_candidates(
        [accepted, old, closed],
        ReferenceFilterCriteria(publication_year_min=2020, only_open_access=True),
    )

    assert result.total_received == 3
    assert result.total_accepted == 1
    assert result.total_rejected == 2
    assert {item.candidate_key for item in result.accepted}.isdisjoint(
        item.candidate_key for item in result.rejected
    )
    assert result.reason_counts == {
        FilterReason.PUBLICATION_BEFORE_MINIMUM: 1,
        FilterReason.NOT_OPEN_ACCESS: 1,
    }


def test_rejected_serialization_exposes_no_complete_bibliographic_metadata():
    private = candidate(
        "private-id",
        year=2010,
        doi="10.1000/private",
        abstract="Private abstract",
    )

    result = ReferenceFilterService().filter_candidates(
        [private],
        ReferenceFilterCriteria(publication_year_min=2020),
    )
    payload = result.rejected[0].model_dump(mode="json")

    assert set(payload) == {"candidate_key", "reasons"}
    assert payload["candidate_key"] == private.candidate_key
    for forbidden_field in (
        "title",
        "abstract",
        "doi",
        "issn",
        "source_url",
        "provider_relevance_score",
    ):
        assert forbidden_field not in payload


def test_inverted_year_range_is_rejected():
    with pytest.raises(ValidationError):
        ReferenceFilterCriteria(publication_year_min=2025, publication_year_max=2020)


def test_service_has_no_io_database_llm_provider_or_refinement_behavior():
    import app.services.reference_filter_service as module

    source = inspect.getsource(module)
    lowered = source.casefold()
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not any(name.startswith("sqlalchemy") for name in imported_modules)
    assert "httpx" not in imported_modules
    assert not any(name.startswith("app.providers") for name in imported_modules)
    assert not any(name.startswith("app.agents") for name in imported_modules)
    assert not any(name.startswith("app.llm") for name in imported_modules)
    assert "refine_search" not in lowered
    assert "searchagent" not in lowered
    assert ".commit(" not in lowered
