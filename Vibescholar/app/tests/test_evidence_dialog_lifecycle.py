"""Evidence-dialog lifecycle and reuse tests without a browser or network."""

import asyncio
import inspect
from unittest.mock import AsyncMock, Mock

from app.ui.pages import workspace as workspace_module
from app.ui.pages.workspace import (
    _evidence_panel,
    _element_is_active,
    _load_pending_or_search_evidence_suggestions,
    _render_suggestions,
    _run_evidence_action_once,
)


class LifecycleButton:
    """Track attempts to update a button after its containing card was removed."""

    def __init__(self) -> None:
        self.text = "Buscar evidências"
        self.disabled = False
        self.is_deleted = False
        self.events: list[str] = []

    def disable(self) -> None:
        if self.is_deleted:
            raise AssertionError("deleted button was disabled")
        self.disabled = True
        self.events.append("disable")

    def enable(self) -> None:
        if self.is_deleted:
            raise AssertionError("deleted button was enabled")
        self.disabled = False
        self.events.append("enable")

    def set_text(self, text: str) -> None:
        if self.is_deleted:
            raise AssertionError("deleted button text was changed")
        self.text = text
        self.events.append(f"text:{text}")


def _suggestion(index: int, *, status: str = "PENDING", source: str | None = None) -> dict:
    item = {
        "id": index,
        "status": status,
        "reference": {
            "id": index,
            "title": f"Reference {index}",
            "authors": "Author",
        },
    }
    if source is not None:
        item["source"] = source
    return item


def test_five_persisted_pending_suggestions_open_without_search_post() -> None:
    async def scenario() -> None:
        suggestions = [_suggestion(index) for index in range(1, 6)]
        state = {"status": "checking", "items": [], "error": None}
        pending_request = AsyncMock(return_value=suggestions)
        search_request = AsyncMock()
        refresh = Mock()

        searched = await _load_pending_or_search_evidence_suggestions(
            state,
            pending_request,
            search_request,
            refresh,
        )

        assert searched is False
        assert state["status"] == "success"
        assert state["items"] == suggestions
        assert len(state["items"]) == 5
        assert all(item["status"] == "PENDING" for item in state["items"])
        pending_request.assert_awaited_once_with()
        search_request.assert_not_awaited()
        assert refresh.call_count == 2

    asyncio.run(scenario())


def test_empty_pending_lookup_runs_search_once_for_possible_reserve() -> None:
    async def scenario() -> None:
        reserve = _suggestion(2)
        state = {"status": "checking", "items": [], "error": None}
        pending_request = AsyncMock(return_value=[])
        search_request = AsyncMock(return_value=[reserve])

        searched = await _load_pending_or_search_evidence_suggestions(
            state,
            pending_request,
            search_request,
            lambda: None,
        )

        assert searched is True
        assert state["status"] == "success"
        assert state["items"] == [reserve]
        pending_request.assert_awaited_once_with()
        search_request.assert_awaited_once_with()

    asyncio.run(scenario())


def test_pending_lookup_failure_does_not_start_search() -> None:
    async def scenario() -> None:
        state = {"status": "checking", "items": [], "error": None}
        pending_request = AsyncMock(side_effect=ValueError("pending lookup failed"))
        search_request = AsyncMock()

        searched = await _load_pending_or_search_evidence_suggestions(
            state,
            pending_request,
            search_request,
            lambda: None,
        )

        assert searched is False
        assert state["status"] == "error"
        assert state["error"] == "pending lookup failed"
        search_request.assert_not_awaited()

    asyncio.run(scenario())


def test_deleted_action_button_is_not_updated_by_finally() -> None:
    async def scenario() -> None:
        button = LifecycleButton()
        active: set[int] = set()

        async def action() -> None:
            button.is_deleted = True

        assert await _run_evidence_action_once(17, active, button, action) is True
        assert active == set()
        assert button.events == ["disable", "text:Buscando evidências..."]
        assert _element_is_active(button) is False

    asyncio.run(scenario())


def test_dialog_lifecycle_does_not_auto_close_or_refresh_card_after_search() -> None:
    panel_source = inspect.getsource(_evidence_panel)
    workspace_source = inspect.getsource(workspace_module)
    search_callback = workspace_source.split(
        "async def search_ev()", 1
    )[1].split("async def review_citation()", 1)[0]

    assert "dlg.close()" not in panel_source
    assert "on_click=dlg.close" in panel_source
    assert "_render_suggestions(pending" in panel_source
    assert '"Aprovar"' in inspect.getsource(_render_suggestions)
    assert "await refresh_card_and_grounding()" not in search_callback
    assert "await _evidence_panel(" in search_callback
