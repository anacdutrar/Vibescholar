"""Frontend synchronization tests for long-running evidence searches."""

import asyncio
import inspect

from app.ui import api_client
from app.ui.pages.workspace import (
    _evidence_panel,
    _evidence_search_finished_empty,
    _load_pending_or_search_evidence_suggestions,
    _run_evidence_action_once,
    _synchronize_evidence_suggestions,
)


class FakeButton:
    """Minimal NiceGUI-compatible button state used by synchronization tests."""

    def __init__(self) -> None:
        self.text = "Buscar evidências"
        self.disabled = False

    def disable(self) -> None:
        self.disabled = True

    def enable(self) -> None:
        self.disabled = False

    def set_text(self, text: str) -> None:
        self.text = text


class RecordingAsyncClient:
    """Capture the evidence request arguments without network access."""

    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, path: str, **kwargs):
        self.calls.append((path, kwargs))
        return self.response


class ResponseStub:
    """Return one successful public API payload."""

    status_code = 200

    def __init__(self, payload) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


def test_successful_search_stays_loading_until_backend_finishes():
    async def scenario():
        state = {"status": "idle", "items": [], "error": None}
        button = FakeButton()
        active: set[int] = set()
        started = asyncio.Event()
        release = asyncio.Event()
        refresh_states: list[str] = []
        suggestion = {"id": 1, "status": "PENDING"}

        async def request():
            started.set()
            await release.wait()
            return [suggestion]

        async def action():
            await _synchronize_evidence_suggestions(
                state,
                request,
                lambda: refresh_states.append(state["status"]),
            )

        task = asyncio.create_task(
            _run_evidence_action_once(7, active, button, action)
        )
        await started.wait()

        assert state["status"] == "loading"
        assert state["items"] == []
        assert _evidence_search_finished_empty(state) is False
        assert button.disabled is True
        assert button.text == "Buscando evidências..."

        release.set()
        assert await task is True
        assert state["status"] == "success"
        assert state["items"] == [suggestion]
        assert _evidence_search_finished_empty(state) is False
        assert button.disabled is False
        assert refresh_states == ["loading", "success"]

    asyncio.run(scenario())


def test_empty_message_becomes_valid_only_after_successful_completion():
    async def scenario():
        state = {"status": "idle", "items": [], "error": None}
        started = asyncio.Event()
        release = asyncio.Event()

        async def request():
            started.set()
            await release.wait()
            return []

        task = asyncio.create_task(
            _synchronize_evidence_suggestions(state, request, lambda: None)
        )
        await started.wait()

        assert state["status"] == "loading"
        assert _evidence_search_finished_empty(state) is False

        release.set()
        await task
        assert state["status"] == "success"
        assert _evidence_search_finished_empty(state) is True

    asyncio.run(scenario())


def test_operational_failure_renders_error_state_and_restores_button():
    async def scenario():
        state = {"status": "idle", "items": [], "error": None}
        button = FakeButton()

        async def request():
            raise RuntimeError("controlled provider failure")

        async def action():
            await _synchronize_evidence_suggestions(state, request, lambda: None)

        assert await _run_evidence_action_once(7, set(), button, action) is True
        assert state["status"] == "error"
        assert state["error"] == "controlled provider failure"
        assert _evidence_search_finished_empty(state) is False
        assert button.disabled is False
        assert button.text == "Buscar evidências"

    asyncio.run(scenario())


def test_evidence_api_waits_without_generic_ui_timeout(monkeypatch):
    async def scenario():
        client = RecordingAsyncClient(ResponseStub([]))
        monkeypatch.setattr(api_client, "_async_client", lambda cookies=None: client)

        result = await api_client.api_search_evidence_async({}, 23)

        assert result == []
        assert client.calls == [
            (
                "/api/sentences/search/evidence",
                {"json": {"sentence_id": 23}, "timeout": None},
            )
        ]

    asyncio.run(scenario())


def test_dialog_opens_before_awaiting_pipeline_and_refreshes_afterward():
    source = inspect.getsource(_evidence_panel)

    assert source.index("dlg.open()") < source.rindex(
        "await _load_pending_or_search_evidence_suggestions"
    )
    assert '"Buscando evidências..."' in source
    assert "_evidence_search_finished_empty(suggestions_state)" in source
