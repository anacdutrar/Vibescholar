import inspect
import asyncio
from unittest.mock import AsyncMock
#g
from app.ui.pages.workspace import (
    _apply_evidence_status_locally,
    _apply_autosave_content,
    _detect_apparent_citation,
    _grounding_score,
    _load_grounding_state,
    _matching_citation_suggestions,
    _refresh_evidence_components,
    _replace_grounding_state,
    _selectable_reference_suggestions,
    _sentence_evidence_action_label,
    _transition_citation_review_state,
)


def _sentence() -> dict:
    return {
        "id": 7,
        "text": '"A internet mudou o mundo" (SILVA, 2024, p. 15).',
        "status": "UNVERIFIED",
        "approved_evidence_count": 0,
        "approved_reference_titles": [],
    }


def _suggestion() -> dict:
    return {
        "id": 11,
        "status": "PENDING",
        "reference": {"id": 5, "title": "Internet e sociedade"},
    }


def test_citation_with_page_locator_uses_review_action() -> None:
    sentence = _sentence()

    assert _detect_apparent_citation(sentence["text"])["raw"] == "(SILVA, 2024, p. 15)"
    assert _sentence_evidence_action_label(sentence, set()) == "Revisar citação"


def test_sentence_without_citation_uses_evidence_search_action() -> None:
    sentence = _sentence()
    sentence["text"] = "A internet mudou o mundo."

    assert _sentence_evidence_action_label(sentence, set()) == "Buscar evidências"


def test_approval_updates_sentence_state_and_action_immediately() -> None:
    sentence = _sentence()
    suggestion = _suggestion()

    _apply_evidence_status_locally(sentence, suggestion, "APPROVED")

    assert sentence["approved_evidence_count"] == 1
    assert sentence["status"] == "SUPPORTED"
    assert sentence["approved_reference_titles"] == ["Internet e sociedade"]
    assert _sentence_evidence_action_label(sentence, set()) == "Ver evidências / Adicionar outra"


def test_removing_last_approval_returns_sentence_to_unverified() -> None:
    sentence = _sentence()
    suggestion = _suggestion()
    _apply_evidence_status_locally(sentence, suggestion, "APPROVED")

    _apply_evidence_status_locally(sentence, suggestion, "PENDING")

    assert sentence["approved_evidence_count"] == 0
    assert sentence["status"] == "UNVERIFIED"
    assert sentence["approved_reference_titles"] == []


def test_rejection_is_recorded_locally_without_navigation_or_reload() -> None:
    sentence = _sentence()
    suggestion = _suggestion()

    _apply_evidence_status_locally(sentence, suggestion, "REJECTED")

    assert sentence["_evidence_status_by_id"][suggestion["id"]] == "REJECTED"
    assert sentence["approved_evidence_count"] == 0
    assert sentence["status"] == "UNVERIFIED"
    source = inspect.getsource(_apply_evidence_status_locally)
    assert "navigate" not in source
    assert "reload" not in source


def test_rejected_citation_returns_to_search_and_is_not_offered_again() -> None:
    sentence = _sentence()
    suggestion = _suggestion()
    citation = _detect_apparent_citation(sentence["text"])
    ignored = {sentence["id"]}

    _apply_evidence_status_locally(sentence, suggestion, "REJECTED")
    _transition_citation_review_state(
        sentence,
        "REJECTED",
        "reject",
        suggestion["reference"]["id"],
    )

    assert _sentence_evidence_action_label(sentence, ignored) == "Buscar evidências"
    assert _matching_citation_suggestions([suggestion], citation) == []
    assert sentence["_citation_review_state"] == "REJECTED"


def test_manual_confirmation_remains_available_without_direct_match() -> None:
    suggestion = _suggestion()

    assert _selectable_reference_suggestions([suggestion]) == [suggestion]


def test_reference_without_real_id_is_not_available_for_confirmation() -> None:
    suggestion = _suggestion()
    suggestion["reference"].pop("id")
    suggestion["reference_id"] = None

    assert _selectable_reference_suggestions([suggestion]) == []


def test_evidence_action_refreshes_card_and_grounding_without_reload() -> None:
    refresh_card = AsyncMock()
    refresh_grounding = AsyncMock()

    asyncio.run(_refresh_evidence_components(7, refresh_card, refresh_grounding))

    refresh_card.assert_awaited_once_with()
    refresh_grounding.assert_awaited_once_with()
    source = inspect.getsource(_refresh_evidence_components)
    assert "reload" not in source
    assert "navigate" not in source


def test_header_and_grounding_tab_read_the_same_score() -> None:
    grounding_state = {"score": 0.625}

    header_score = _grounding_score(grounding_state)
    tab_score = _grounding_score(grounding_state)

    assert header_score == tab_score == 0.625


def test_switching_document_clears_previous_grounding_score() -> None:
    grounding_state = {}
    _replace_grounding_state(
        grounding_state,
        10,
        {"grounding_score": 0.8, "supported_count": 8},
    )

    _replace_grounding_state(grounding_state, 11, {})

    assert grounding_state["document_id"] == 11
    assert grounding_state["score"] == 0.0
    assert grounding_state["supported_count"] == 0


def test_autosave_content_does_not_recalculate_grounding() -> None:
    document = {"id": 10, "content": "Antes"}
    grounding_state = {"document_id": 10, "score": 0.75}

    _apply_autosave_content(document, "Depois")

    assert document["content"] == "Depois"
    assert grounding_state == {"document_id": 10, "score": 0.75}


def test_grounding_sync_replaces_shared_state(monkeypatch) -> None:
    async def fake_summary(cookies, document_id):
        return {
            "grounding_score": 0.5,
            "supported_count": 1,
            "unsupported_count": 1,
            "outdated_count": 0,
        }

    monkeypatch.setattr(
        "app.ui.pages.workspace.api.api_get_grounding_summary_async",
        fake_summary,
    )
    grounding_state = {"document_id": 10, "score": 0.0}

    asyncio.run(_load_grounding_state(grounding_state, {}, 10))

    assert grounding_state["score"] == 0.5
    assert grounding_state["supported_count"] == 1
