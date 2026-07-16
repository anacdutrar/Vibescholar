"""UI-only tests for the long-running evidence-search waiting indicator."""

import asyncio
import inspect

from app.ui.pages.workspace import (
    EVIDENCE_LOADING_MESSAGES,
    _EvidenceLoadingIndicator,
    _evidence_panel,
    _format_elapsed_time,
    _run_evidence_action_once,
    _synchronize_evidence_suggestions,
)


class FakeButton:
    """Minimal button compatible with the evidence-action guard."""

    def __init__(self) -> None:
        self.text = "Buscar evidências"
        self.disabled = False

    def disable(self) -> None:
        self.disabled = True

    def enable(self) -> None:
        self.disabled = False

    def set_text(self, text: str) -> None:
        self.text = text


class AdvancingClock:
    """Advance by one message interval whenever the indicator samples time."""

    def __init__(self, step: float = 12.0) -> None:
        self.value = -step
        self.step = step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


def test_elapsed_time_uses_minutes_and_seconds() -> None:
    assert _format_elapsed_time(0) == "00:00"
    assert _format_elapsed_time(65) == "01:05"
    assert _format_elapsed_time(-3) == "00:00"


def test_timer_starts_only_while_loading_and_rotates_messages() -> None:
    async def scenario() -> None:
        state = {"status": "idle"}
        refreshed = asyncio.Event()
        indicator = _EvidenceLoadingIndicator(
            state,
            refreshed.set,
            tick_seconds=0,
            message_interval_seconds=12,
            clock=AdvancingClock(),
        )

        indicator.start()
        assert indicator.running is False

        state["status"] = "loading"
        indicator.start()
        assert indicator.running is True
        assert state["loading_message"] == EVIDENCE_LOADING_MESSAGES[0]

        await asyncio.wait_for(refreshed.wait(), timeout=1)
        assert state["elapsed_seconds"] == 12
        assert state["loading_message"] == EVIDENCE_LOADING_MESSAGES[1]
        await indicator.stop()
        assert indicator.running is False

    asyncio.run(scenario())


def test_timer_stops_before_success_refresh_and_never_updates_afterward() -> None:
    async def scenario() -> None:
        state = {"status": "idle", "items": [], "error": None}
        refreshes: list[str] = []
        release = asyncio.Event()

        async def request():
            await release.wait()
            return [{"id": 1}]

        indicator = _EvidenceLoadingIndicator(
            state,
            lambda: refreshes.append(state["status"]),
            tick_seconds=0,
            clock=AdvancingClock(1),
        )
        task = asyncio.create_task(
            _synchronize_evidence_suggestions(
                state,
                request,
                lambda: refreshes.append(state["status"]),
                indicator,
            )
        )
        await asyncio.sleep(0)
        assert state["status"] == "loading"
        assert indicator.running is True

        release.set()
        await task
        completed_refreshes = len(refreshes)
        assert state["status"] == "success"
        assert indicator.running is False

        await asyncio.sleep(0.01)
        assert len(refreshes) == completed_refreshes

    asyncio.run(scenario())


def test_timer_stops_on_error_without_additional_updates() -> None:
    async def scenario() -> None:
        state = {"status": "idle", "items": [], "error": None}
        refreshes: list[str] = []

        async def request():
            await asyncio.sleep(0)
            raise ValueError("controlled failure")

        indicator = _EvidenceLoadingIndicator(
            state,
            lambda: refreshes.append(state["status"]),
            tick_seconds=0,
            clock=AdvancingClock(1),
        )
        await _synchronize_evidence_suggestions(
            state,
            request,
            lambda: refreshes.append(state["status"]),
            indicator,
        )
        completed_refreshes = len(refreshes)

        assert state["status"] == "error"
        assert state["error"] == "controlled failure"
        assert indicator.running is False
        await asyncio.sleep(0.01)
        assert len(refreshes) == completed_refreshes

    asyncio.run(scenario())


def test_closing_dialog_cancels_timer_and_prevents_future_updates() -> None:
    async def scenario() -> None:
        state = {"status": "loading"}
        refreshes = 0

        def refresh() -> None:
            nonlocal refreshes
            refreshes += 1

        indicator = _EvidenceLoadingIndicator(
            state,
            refresh,
            tick_seconds=0,
            clock=AdvancingClock(1),
        )
        indicator.start()
        await asyncio.sleep(0)
        indicator.close()
        closed_refreshes = refreshes

        await asyncio.sleep(0.01)
        assert indicator.running is False
        assert refreshes == closed_refreshes

    asyncio.run(scenario())


def test_completed_request_does_not_refresh_after_dialog_was_closed() -> None:
    async def scenario() -> None:
        state = {"status": "idle", "items": [], "error": None}
        refreshes = 0
        request_started = asyncio.Event()
        release = asyncio.Event()

        def refresh() -> None:
            nonlocal refreshes
            refreshes += 1

        async def request():
            request_started.set()
            await release.wait()
            return []

        indicator = _EvidenceLoadingIndicator(
            state,
            refresh,
            tick_seconds=60,
        )
        task = asyncio.create_task(
            _synchronize_evidence_suggestions(
                state,
                request,
                refresh,
                indicator,
            )
        )
        await request_started.wait()
        indicator.close()
        refreshes_at_close = refreshes

        release.set()
        await task

        assert state["status"] == "success"
        assert refreshes == refreshes_at_close

    asyncio.run(scenario())


def test_waiting_indicator_does_not_add_requests_and_button_stays_disabled() -> None:
    async def scenario() -> None:
        state = {"status": "idle", "items": [], "error": None}
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()
        button = FakeButton()

        async def request():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return []

        indicator = _EvidenceLoadingIndicator(
            state,
            lambda: None,
            tick_seconds=0,
            clock=AdvancingClock(1),
        )

        async def action() -> None:
            await _synchronize_evidence_suggestions(
                state,
                request,
                lambda: None,
                indicator,
            )

        task = asyncio.create_task(
            _run_evidence_action_once(23, set(), button, action)
        )
        await started.wait()
        await asyncio.sleep(0)

        assert calls == 1
        assert button.disabled is True
        assert button.text == "Buscando evidências..."

        release.set()
        assert await task is True
        assert calls == 1
        assert button.disabled is False

    asyncio.run(scenario())


def test_evidence_panel_uses_indeterminate_waiting_copy_without_polling() -> None:
    source = inspect.getsource(_evidence_panel)

    for message in EVIDENCE_LOADING_MESSAGES:
        assert message not in source  # messages remain centralized, not duplicated
    assert "loading_message" in source
    assert "Tempo decorrido:" in source
    assert "pode levar alguns minutos" in source
    assert "ui.spinner" in source
    assert "ui.linear_progress" not in source
    assert "poll" not in source.casefold()
    assert source.count("api_search_evidence_async") == 2
