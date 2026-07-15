"""Isolated tests for AI contracts and in-memory search state."""

import asyncio
import inspect
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.schemas import (
    CitationHint,
    EvidenceAnalysisScope,
    EvidenceEvaluation,
    EvidenceEvaluationBatch,
    EvidenceVerdict,
    SearchPlan,
    SearchToolName,
    SentenceType,
)
from app.core.config import Settings
from app.services.evidence_search_state import (
    EvidenceSearchSession,
    EvidenceSearchSessionStore,
    SearchAlreadyInProgressError,
    SearchSessionStatus,
    SearchStoreCapacityError,
)
from app.tools.schemas import EvidenceSearchCandidate, ReferenceCandidate, build_candidate_key


def run(coroutine):
    """Execute one isolated asynchronous store scenario."""
    return asyncio.run(coroutine)


def valid_plan(**overrides) -> SearchPlan:
    """Build a valid academic-search plan with optional field overrides."""
    values = {
        "sentence_type": SentenceType.SCIENTIFIC_CLAIM,
        "should_search": True,
        "selected_tool": SearchToolName.SEARCH_ACADEMIC_WORKS,
        "topic": "scientific writing",
        "tags": ["methodology"],
        "queries": ["scientific writing methodology"],
        "citation_hints": [],
        "confidence": 0.8,
        "reason": "The sentence contains a scientific claim.",
    }
    values.update(overrides)
    return SearchPlan(**values)


def test_enum_contracts_have_expected_values():
    assert {item.value for item in SentenceType} == {
        "scientific_claim", "citation_claim", "non_scientific", "invalid"
    }
    assert {item.value for item in SearchToolName} == {
        "none", "search_academic_works", "resolve_citation_metadata"
    }
    assert {item.value for item in EvidenceVerdict} == {
        "strong_support", "partial_support", "no_support", "contradicts", "insufficient_abstract"
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"should_search": False, "selected_tool": "search_academic_works"},
        {"should_search": True, "selected_tool": "none"},
        {"should_search": False, "selected_tool": "none", "queries": ["not allowed"]},
        {"selected_tool": "search_academic_works", "queries": []},
        {"selected_tool": "search_academic_works", "queries": ["a", "b", "c", "d", "e", "f"]},
        {"queries": ["valid", "  "]},
        {"queries": ["Same query", " same QUERY "]},
    ],
)
def test_inconsistent_search_plans_are_rejected(overrides):
    with pytest.raises(ValidationError):
        valid_plan(**overrides)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_outside_unit_interval_is_rejected(confidence):
    with pytest.raises(ValidationError):
        valid_plan(confidence=confidence)


def test_citation_resolution_accepts_hint_without_query():
    plan = valid_plan(
        sentence_type="citation_claim",
        selected_tool="resolve_citation_metadata",
        queries=[],
        citation_hints=[CitationHint(raw="(Silva, 2024)", author="Silva", year=2024)],
    )
    assert plan.queries == []
    assert plan.citation_hints[0].year == 2024


def test_candidate_and_evaluation_ids_are_preserved():
    reference = ReferenceCandidate(provider="OpenAlex", external_id="W123", title="A Study")
    candidate = EvidenceSearchCandidate(reference=reference, provider="openalex", search_round=1)
    evaluation = EvidenceEvaluation(
        candidate_key=candidate.reference.candidate_key,
        verdict="strong_support",
        confidence=0.9,
        reason="The abstract directly supports the claim.",
        analysis_scope=EvidenceAnalysisScope.TITLE_AND_ABSTRACT,
    )
    batch = EvidenceEvaluationBatch(evaluations=[evaluation])
    assert reference.external_id == "W123"
    assert batch.evaluations[0].candidate_key == "openalex:w123"


def test_candidate_key_normalization_and_fallbacks():
    assert build_candidate_key(provider="OpenAlex", doi=" https://doi.org/10.1000/ABC ") == "doi:10.1000/abc"
    assert build_candidate_key(provider="Semantic_Scholar", external_id=" Corpus-42 ") == "semantic_scholar:corpus-42"
    assert (
        build_candidate_key(provider="OpenAlex", title="  Neural   Networks  ", year=2024)
        == "openalex:title:neural networks:2024"
    )
    with pytest.raises(ValueError):
        build_candidate_key(provider="openalex", title="  ")


def test_store_separates_keys_and_instances():
    async def scenario():
        first = EvidenceSearchSessionStore()
        second = EvidenceSearchSessionStore()
        keys = [(1, 10, "a"), (2, 10, "a"), (1, 11, "a"), (1, 10, "b")]
        for index, key in enumerate(keys):
            await first.set(key, EvidenceSearchSession(current_round=index + 1))
        assert [await first.get(key) for key in keys]
        assert await second.get(keys[0]) is None
        assert await first.size() == 4
        assert await second.size() == 0

    run(scenario())


def test_search_session_key_hash_is_stable():
    first = (7, 12, "b646f53a-cae0-4b35-89f3-f07f28d5370e")
    second = tuple([7, 12, "b646f53a-cae0-4b35-89f3-f07f28d5370e"])
    assert first == second
    assert hash(first) == hash(second)
    assert {first: "session"}[second] == "session"


def test_same_key_is_exclusive_and_guard_releases_after_exception():
    async def scenario():
        store = EvidenceSearchSessionStore()
        key = (1, 1, "sentence")
        with pytest.raises(RuntimeError, match="operation failed"):
            async with store.search_guard(key):
                with pytest.raises(SearchAlreadyInProgressError):
                    async with store.search_guard(key):
                        pytest.fail("second guard must not be entered")
                raise RuntimeError("operation failed")
        async with store.search_guard(key) as session:
            assert session.search_in_progress is True
        assert key not in store._locks

    run(scenario())


def test_different_keys_do_not_block_each_other():
    async def scenario():
        store = EvidenceSearchSessionStore()
        first_entered = asyncio.Event()
        second_entered = asyncio.Event()
        release = asyncio.Event()

        async def hold(key, entered):
            async with store.search_guard(key):
                entered.set()
                await release.wait()

        first_task = asyncio.create_task(hold((1, 1, "a"), first_entered))
        await first_entered.wait()
        second_task = asyncio.create_task(hold((1, 1, "b"), second_entered))
        await asyncio.wait_for(second_entered.wait(), timeout=0.2)
        release.set()
        await asyncio.gather(first_task, second_task)

    run(scenario())


def test_expiration_cleanup_and_valid_session_retention():
    async def scenario():
        store = EvidenceSearchSessionStore(ttl_seconds=10)
        expired_key = (1, 1, "expired")
        valid_key = (1, 1, "valid")
        expired = EvidenceSearchSession()
        valid = EvidenceSearchSession()
        await store.set(expired_key, expired)
        await store.set(valid_key, valid)
        expired.updated_at = datetime.now(UTC) - timedelta(seconds=11)
        valid.updated_at = datetime.now(UTC) - timedelta(seconds=2)
        assert await store.cleanup_expired() == 1
        assert await store.get(expired_key) is None
        assert await store.get(valid_key) is valid

    run(scenario())


def test_clear_document_and_clear_user_are_scoped():
    async def scenario():
        store = EvidenceSearchSessionStore()
        keys = [(1, 10, "a"), (2, 10, "b"), (1, 11, "c"), (3, 12, "d")]
        for key in keys:
            await store.set(key, EvidenceSearchSession())
        assert await store.clear_document(10) == 2
        assert await store.get(keys[0]) is None
        assert await store.get(keys[1]) is None
        assert await store.get(keys[2]) is not None
        assert await store.clear_user(1) == 1
        assert await store.get(keys[2]) is None
        assert await store.get(keys[3]) is not None

    run(scenario())


def test_capacity_evicts_oldest_idle_session():
    async def scenario():
        store = EvidenceSearchSessionStore(max_sessions=2)
        first = EvidenceSearchSession()
        await store.set((1, 1, "first"), first)
        first.updated_at = datetime.now(UTC) - timedelta(minutes=2)
        await store.set((1, 1, "second"), EvidenceSearchSession())
        await store.set((1, 1, "third"), EvidenceSearchSession())
        assert await store.size() == 2
        assert await store.get((1, 1, "first")) is None

    run(scenario())


def test_capacity_and_ttl_never_remove_session_in_use():
    async def scenario():
        store = EvidenceSearchSessionStore(ttl_seconds=1, max_sessions=1)
        active_key = (1, 1, "active")
        async with store.search_guard(active_key) as active:
            active.updated_at = datetime.now(UTC) - timedelta(hours=1)
            assert await store.cleanup_expired() == 0
            with pytest.raises(SearchStoreCapacityError):
                await store.set((1, 1, "other"), EvidenceSearchSession())
            assert await store.get(active_key) is active

    run(scenario())


def test_terminal_session_without_reserved_candidates_is_removed():
    async def scenario():
        store = EvidenceSearchSessionStore()
        key = (1, 1, "complete")
        async with store.search_guard(key) as session:
            session.status = SearchSessionStatus.COMPLETED
        assert await store.get(key) is None
        assert key not in store._locks

    run(scenario())


def test_delete_removes_idle_auxiliary_structures():
    async def scenario():
        store = EvidenceSearchSessionStore()
        key = (1, 1, "delete")
        async with store.search_guard(key):
            pass
        assert key not in store._locks
        await store.delete(key)
        assert key not in store._sessions
        assert key not in store._locks

    run(scenario())


def test_contract_modules_do_not_import_sqlalchemy():
    import app.agents.schemas as agent_schemas
    import app.tools.schemas as tool_schemas

    assert "sqlalchemy" not in inspect.getsource(agent_schemas).casefold()
    assert "sqlalchemy" not in inspect.getsource(tool_schemas).casefold()


def test_prompts_exist_and_are_utf8_role_instructions():
    prompt_root = Path(__file__).resolve().parents[2] / "prompts"
    names = {
        "search_agent_system.txt",
        "search_refinement_system.txt",
        "evidence_evaluator_system.txt",
    }
    for name in names:
        content = (prompt_root / name).read_text(encoding="utf-8")
        assert content.strip()
        assert "API_KEY" not in content
        assert "http://" not in content and "https://" not in content


def test_settings_repr_and_logs_do_not_expose_api_keys(caplog):
    marker = "super-secret-test-key"
    configured = Settings()
    configured.OLLAMA_API_KEY = marker
    configured.OPENROUTER_API_KEY = marker
    with caplog.at_level(logging.INFO):
        logging.getLogger("test.ai.config").info("settings=%r", configured)
    assert marker not in repr(configured)
    assert marker not in caplog.text

