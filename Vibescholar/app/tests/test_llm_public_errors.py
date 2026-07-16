"""Public HTTP mapping for controlled real-pipeline LLM failures."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.app import fastapi_app
from app.llm.exceptions import (
    LLMConnectionError,
    LLMResponseValidationError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.routers import grounding as grounding_router
from app.services.grounding_service import GroundingService


class GroundingServiceStub:
    def __init__(self, result=None, error=None):
        self.result = [] if result is None else result
        self.error = error
        self.calls = []

    async def search_sentence_evidence(self, sentence_id, user_id):
        self.calls.append((sentence_id, user_id))
        if self.error is not None:
            raise self.error
        return self.result


def post_evidence_search(service: GroundingServiceStub):
    user = SimpleNamespace(id=17)
    fastapi_app.dependency_overrides[grounding_router.get_current_user] = lambda: user
    fastapi_app.dependency_overrides[GroundingService] = lambda: service
    client = TestClient(fastapi_app, raise_server_exceptions=True)
    try:
        return client.post("/api/sentences/search/evidence", json={"sentence_id": 23})
    finally:
        client.close()
        fastapi_app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (
            LLMTimeoutError("internal timeout details"),
            504,
            "O modelo local demorou mais que o limite configurado.",
        ),
        (
            LLMConnectionError("internal connection details"),
            503,
            "Não foi possível conectar ao modelo local.",
        ),
        (
            LLMUnavailableError("internal model details"),
            503,
            "O modelo local configurado não está disponível.",
        ),
        (
            LLMResponseValidationError("internal response details"),
            502,
            "O modelo retornou uma resposta inválida.",
        ),
    ],
)
def test_typed_llm_failures_have_safe_distinguishable_public_responses(
    error, status_code, message
):
    service = GroundingServiceStub(error=error)

    response = post_evidence_search(service)

    assert response.status_code == status_code
    assert response.json() == {"detail": message}
    assert response.json() != []
    assert service.calls == [(23, 17)]
    assert str(error) not in response.text


def test_successful_search_without_suggestions_remains_an_empty_list():
    service = GroundingServiceStub(result=[])

    response = post_evidence_search(service)

    assert response.status_code == 200
    assert response.json() == []
    assert service.calls == [(23, 17)]
