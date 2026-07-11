from fastapi import APIRouter, Depends
from typing import List
from pydantic import BaseModel

from app.routers.auth import get_current_user
from app.schemas.request import EvidenceStatusUpdate
from app.schemas.response import SentenceOut, EvidenceSuggestionOut
from app.services.grounding_service import GroundingService

router = APIRouter(tags=["Grounding"])

# --- SCHEMAS ---
class EvidenceSearchRequest(BaseModel):
    sentence_id: int

# --- ENDPOINTS ---

@router.get("/api/documents/{document_id}/sentences", response_model=List[SentenceOut])
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
def search_sentence_evidence(
    req: EvidenceSearchRequest,
    current_user = Depends(get_current_user),
    grounding_service: GroundingService = Depends()
):
    """
    Triggers MockEvidenceService to search and filter suggestions for a sentence,
    saving them as PENDING suggestions.
    """
    return grounding_service.search_sentence_evidence(req.sentence_id, current_user.id)

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
