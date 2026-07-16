"""Controlled public and UI behavior for concurrent evidence searches."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from app.app import fastapi_app
from app.routers import grounding as grounding_router
from app.services.evidence_search_state import EvidenceSearchSessionStore
from app.services.grounding_service import GroundingService
from app.ui import api_client
from app.ui.pages.workspace import _run_evidence_action_once


class ConcurrentGroundingService:
    """Hold one real guard so a concurrent request reaches the public mapping."""

    def __init__(self) -> None:
        self.store = EvidenceSearchSessionStore()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.executions = 0

    async def search_sentence_evidence(self, sentence_id: int, user_id: int):
        key = (user_id, 31, f"sentence-{sentence_id}")
        async with self.store.search_guard(key):
            self.executions += 1
            self.started.set()
            await self.release.wait()
            return []


class FakeButton:
    """Record the minimal NiceGUI button lifecycle used by the helper."""

    def __init__(self, text: str = "Buscar evidências") -> None:
        self.text = text
        self.disabled = False
        self.events: list[str] = []

    def disable(self) -> None:
        self.disabled = True
        self.events.append("disable")

    def enable(self) -> None:
        self.disabled = False
        self.events.append("enable")

    def set_text(self, text: str) -> None:
        self.text = text
        self.events.append(text)


def test_second_simultaneous_request_returns_409_and_first_continues():
    async def scenario():
        service = ConcurrentGroundingService()
        fastapi_app.dependency_overrides[grounding_router.get_current_user] = (
            lambda: SimpleNamespace(id=17)
        )
        fastapi_app.dependency_overrides[GroundingService] = lambda: service
        transport = httpx.ASGITransport(app=fastapi_app)
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                first_task = asyncio.create_task(
                    client.post(
                        "/api/sentences/search/evidence",
                        json={"sentence_id": 23},
                    )
                )
                await service.started.wait()

                second = await client.post(
                    "/api/sentences/search/evidence",
                    json={"sentence_id": 23},
                )
                assert second.status_code == 409
                assert second.json() == {
                    "detail": "Já existe uma busca de evidências em andamento para esta sentença."
                }
                assert not first_task.done()
                assert service.executions == 1

                service.release.set()
                first = await first_task
                assert first.status_code == 200
                assert first.json() == []

                after_release = await client.post(
                    "/api/sentences/search/evidence",
                    json={"sentence_id": 23},
                )
                assert after_release.status_code == 200
                assert service.executions == 2
        finally:
            fastapi_app.dependency_overrides.clear()

    asyncio.run(scenario())


def test_ui_disables_button_prevents_duplicate_and_restores_after_success():
    async def scenario():
        button = FakeButton()
        active: set[int] = set()
        started = asyncio.Event()
        release = asyncio.Event()
        request = AsyncMock()

        async def action():
            await request()
            started.set()
            await release.wait()

        first = asyncio.create_task(
            _run_evidence_action_once(23, active, button, action)
        )
        await started.wait()
        assert button.disabled is True
        assert button.text == "Buscando evidências..."

        duplicate_started = await _run_evidence_action_once(23, active, button, action)
        assert duplicate_started is False
        request.assert_awaited_once_with()

        release.set()
        assert await first is True
        assert button.disabled is False
        assert button.text == "Buscar evidências"
        assert active == set()

    asyncio.run(scenario())


def test_ui_restores_button_and_allows_retry_after_error():
    async def scenario():
        button = FakeButton()
        active: set[int] = set()

        async def failure():
            raise ValueError("controlled failure")

        try:
            await _run_evidence_action_once(23, active, button, failure)
        except ValueError:
            pass
        else:
            raise AssertionError("the action error must propagate")

        assert button.disabled is False
        assert button.text == "Buscar evidências"
        assert active == set()

        success = AsyncMock()
        assert await _run_evidence_action_once(23, active, button, success) is True
        success.assert_awaited_once_with()

    asyncio.run(scenario())


def test_store_guard_is_released_after_operation_error():
    async def scenario():
        store = EvidenceSearchSessionStore()
        key = (17, 31, "sentence-error")

        try:
            async with store.search_guard(key):
                raise ValueError("controlled operation failure")
        except ValueError:
            pass
        else:
            raise AssertionError("the controlled operation error must propagate")

        async with store.search_guard(key) as session:
            assert session.search_in_progress is True

        stored = await store.get(key)
        assert stored is not None
        assert stored.search_in_progress is False

    asyncio.run(scenario())


def test_ui_client_preserves_conflict_instead_of_returning_empty_search(monkeypatch):
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409,
                request=request,
                json={
                    "detail": "Já existe uma busca de evidências em andamento para esta sentença."
                },
            )

        monkeypatch.setattr(
            api_client,
            "_async_client",
            lambda cookies=None: httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://testserver",
            ),
        )

        try:
            await api_client.api_search_evidence_async({}, 23)
        except api_client.EvidenceSearchConflictError as exc:
            assert str(exc) == (
                "Já existe uma busca de evidências em andamento para esta sentença."
            )
        else:
            raise AssertionError("HTTP 409 must not be converted into an empty result")

    asyncio.run(scenario())
