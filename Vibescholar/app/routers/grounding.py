from fastapi import APIRouter, Depends, HTTPException
import time
from typing import List
from pydantic import BaseModel

from app.routers.auth import get_current_user
from app.schemas.request import EvidenceStatusUpdate
from app.schemas.response import EvidenceSuggestionOut
from app.services.grounding_service import GroundingService
from app.core.logging import logger
from app.llm.exceptions import (
    LLMConnectionError,
    LLMResponseValidationError,
    LLMTimeoutError,
    LLMUnavailableError,
    UnknownToolError,
)
from app.services.evidence_search_state import SearchAlreadyInProgressError

router = APIRouter(tags=["Grounding"])

# --- SCHEMAS ---
class EvidenceSearchRequest(BaseModel):
    sentence_id: int

# --- ENDPOINTS ---


def _public_llm_error(exc: Exception) -> HTTPException:
    """Map controlled LLM failures without exposing internal error details."""
    if isinstance(exc, LLMTimeoutError):
        return HTTPException(
            status_code=504,
            detail="O modelo local demorou mais que o limite configurado.",
        )
    if isinstance(exc, LLMConnectionError):
        return HTTPException(
            status_code=503,
            detail="Não foi possível conectar ao modelo local.",
        )
    if isinstance(exc, LLMUnavailableError):
        return HTTPException(
            status_code=503,
            detail="O modelo local configurado não está disponível.",
        )
    return HTTPException(
        status_code=502,
        detail="O modelo retornou uma resposta inválida.",
    )

@router.get("/api/documents/{document_id}/sentences")
def list_document_sentences(
    document_id: int,
    current_user = Depends(get_current_user),
    grounding_service: GroundingService = Depends()
):
    """
    Retrieves all sentences associated with the document's active version.
    """
    return grounding_service.list_document_sentences(document_id, current_user.id)

@router.post("/api/sentences/search/evidence", response_model=List[EvidenceSuggestionOut])
async def search_sentence_evidence(
    req: EvidenceSearchRequest,
    current_user = Depends(get_current_user),
    grounding_service: GroundingService = Depends()
):
    """
    Triggers MockEvidenceService to search and filter suggestions for a sentence,
    saving them as PENDING suggestions.
    """
    started_at = time.perf_counter()
    logger.info(
        "ai.pipeline.router.started operation=search_evidence sentence_id=%s",
        req.sentence_id,
    )
    try:
        suggestions = await grounding_service.search_sentence_evidence(
            req.sentence_id, current_user.id
        )
        logger.info(
            "ai.pipeline.router.completed operation=search_evidence status=success "
            "suggestions=%s duration=%.4f termination=%s",
            len(suggestions),
            time.perf_counter() - started_at,
            "suggestions_returned" if suggestions else "no_suggestions",
        )
        return suggestions
    except (
        LLMTimeoutError,
        LLMConnectionError,
        LLMUnavailableError,
        LLMResponseValidationError,
        UnknownToolError,
    ) as exc:
        logger.warning(
            "ai.pipeline.router.failed operation=search_evidence status=llm_failure "
            "error_type=%s duration=%.4f",
            type(exc).__name__,
            time.perf_counter() - started_at,
        )
        raise _public_llm_error(exc) from None
    except SearchAlreadyInProgressError:
        logger.info(
            "ai.pipeline.router.failed operation=search_evidence sentence_id=%s "
            "status=conflict reason=already_in_progress duration=%.4f",
            req.sentence_id,
            time.perf_counter() - started_at,
        )
        raise HTTPException(
            status_code=409,
            detail="Já existe uma busca de evidências em andamento para esta sentença.",
        ) from None

@router.put("/api/evidence-suggestions/{suggestion_id}", response_model=EvidenceSuggestionOut)
def update_suggestion_status(
    suggestion_id: int,
    status_in: EvidenceStatusUpdate,
    current_user = Depends(get_current_user),
    grounding_service: GroundingService = Depends()
):
    """
    Approves or Rejects a mock evidence suggestion, re-running the quality analyzer to update score cache.
    """
    return grounding_service.update_suggestion_status(suggestion_id, status_in.status, current_user.id)

@router.get("/api/documents/{document_id}/grounding")
def get_grounding_summary(
    document_id: int,
    current_user = Depends(get_current_user),
    grounding_service: GroundingService = Depends()
):
    """
    Retrieves the latest generated grounding report and score.
    """
    return grounding_service.get_grounding_summary(document_id, current_user.id)
