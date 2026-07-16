from fastapi import Depends, HTTPException
import re
import time
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Dict, Any
from app.core.database import get_db
from app.models.document import Sentence, Document
from app.models.reference import EvidenceSuggestion
from app.repositories.document_repository import DocumentRepository
from app.repositories.reference_repository import ReferenceRepository
from app.repositories.project_repository import ProjectRepository
from app.services.evidence_service import EvidenceService
from app.services.quality_analyzer import QualityAnalyzer
from app.exceptions.document import DocumentNotFoundException
from app.exceptions.reference import SuggestionNotFoundException
from app.core.logging import logger
from app.agents.schemas import CitationHint
from app.schemas.response import EvidenceSuggestionOut


def extract_citation_hints(text: str) -> Dict[str, Any] | None:
    doi_match = re.search(r"\b10\.\d{4,9}/[^\s\]\)},;]+", text, re.IGNORECASE)
    author_year_match = re.search(
        r"\(([A-ZÀ-ÖØ-Ý][\wÀ-ÿ'’-]+)(?:\s+et\s+al\.)?,\s*((?:19|20)\d{2})\)",
        text,
        re.IGNORECASE,
    )
    if doi_match:
        doi = doi_match.group(0).rstrip(".,;:")
        return {"raw": doi, "doi": doi, "author": None, "year": None}
    if author_year_match:
        return {
            "raw": author_year_match.group(0),
            "doi": None,
            "author": author_year_match.group(1),
            "year": int(author_year_match.group(2)),
        }
    return None

class GroundingService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db
        self.doc_repo = DocumentRepository()

    def _verify_document_ownership(self, doc_id: int, user_id: int) -> Document:
        doc = self.doc_repo.get_by_id(self.db, doc_id)
        if not doc:
            raise DocumentNotFoundException(doc_id)
        project = ProjectRepository.get_by_id(self.db, doc.project_id)
        if not project or project.user_id != user_id:
            raise HTTPException(status_code=403, detail="Acesso não autorizado.")
        return doc

    def list_document_sentences(self, document_id: int, user_id: int) -> List[Dict[str, Any]]:
        doc = self._verify_document_ownership(document_id, user_id)
        if not doc.current_version_id:
            return []
        sentences = self.doc_repo.get_sentences_by_version(self.db, doc.current_version_id)
        suggestions = ReferenceRepository.get_suggestions_by_version(self.db, doc.current_version_id)
        approved_by_sentence: Dict[str, list[EvidenceSuggestion]] = {}
        for suggestion in suggestions:
            if suggestion.status == "APPROVED" and suggestion.reference is not None:
                approved_by_sentence.setdefault(suggestion.sentence_uuid, []).append(suggestion)

        return [
            {
                "id": sentence.id,
                "document_version_id": sentence.document_version_id,
                "sentence_uuid": sentence.sentence_uuid,
                "paragraph_number": sentence.paragraph_number,
                "sentence_number": sentence.sentence_number,
                "position": sentence.position,
                "text": sentence.text,
                "status": sentence.status,
                "approved_evidence_count": len(approved_by_sentence.get(sentence.sentence_uuid, [])),
                "approved_reference_titles": [
                    suggestion.reference.title
                    for suggestion in approved_by_sentence.get(sentence.sentence_uuid, [])
                ],
            }
            for sentence in sentences
        ]

    async def search_sentence_evidence(
        self,
        sentence_id: int,
        user_id: int,
    ) -> List[EvidenceSuggestionOut]:
        started_at = time.perf_counter()
        # Fetch sentence
        sentence = self.db.query(Sentence).filter(Sentence.id == sentence_id).first()
        if not sentence:
            raise HTTPException(status_code=404, detail="Sentença não encontrada.")

        # Fetch version and document context to verify permission
        version = self.doc_repo.get_version_by_id(self.db, sentence.document_version_id)
        doc = self._verify_document_ownership(version.document_id, user_id)
        logger.info(
            "evidence.search.context sentence_id=%s sentence_uuid=%s document_version_id=%s project_id=%s",
            sentence.id,
            sentence.sentence_uuid,
            version.id,
            doc.project_id,
        )

        existing = ReferenceRepository.get_suggestions_by_version_and_sentence(
            self.db, version.id, sentence.sentence_uuid
        )
        logger.info(
            "evidence.search.existing sentence_id=%s suggestions=%s",
            sentence.id,
            [{"id": item.id, "reference_id": item.reference_id, "status": item.status} for item in existing],
        )
        terminal_reference_ids = {
            item.reference_id for item in existing if item.status in {"APPROVED", "REJECTED"}
        }
        citation_hints = extract_citation_hints(sentence.text)
        logger.info(
            "evidence.search.citation sentence_id=%s detected=%s",
            sentence.id,
            citation_hints is not None,
        )

        # Call EvidenceService search
        evidence_service = EvidenceService()
        try:
            suggestions = await evidence_service.search(
                self.db,
                sentence.text,
                doc.project_id,
                user_id=user_id,
                document_version_id=version.id,
                sentence_uuid=sentence.sentence_uuid,
                citation_hints=(
                    [CitationHint.model_validate(citation_hints)] if citation_hints else None
                ),
                excluded_reference_ids=terminal_reference_ids,
            )
            logger.info(
                "ai.pipeline.grounding_service.completed sentence_id=%s suggestions=%s "
                "duration=%.4f termination=%s",
                sentence.id,
                len(suggestions),
                time.perf_counter() - started_at,
                "suggestions_returned" if suggestions else "no_suggestions",
            )
            return suggestions
        except IntegrityError:
            self.db.rollback()
            logger.warning(
                "evidence.search.reference_integrity_rollback sentence_id=%s project_id=%s",
                sentence.id,
                doc.project_id,
            )
            raise HTTPException(
                status_code=409,
                detail="Não foi possível preparar as referências de evidência.",
            )

    def update_suggestion_status(self, suggestion_id: int, status: str, user_id: int) -> EvidenceSuggestion:
        sug = ReferenceRepository.get_suggestion_by_id(self.db, suggestion_id)
        if not sug:
            raise SuggestionNotFoundException(suggestion_id)

        # Verify authorization
        version = self.doc_repo.get_version_by_id(self.db, sug.document_version_id)
        self._verify_document_ownership(version.document_id, user_id)

        # Update suggestion status
        ReferenceRepository.update_suggestion_status(self.db, sug, status)

        # Re-run quality analyzer to update scores, sentence status, and report details
        QualityAnalyzer.analyze_version(self.db, sug.document_version_id)

        # Reload relationship for returning response
        ref = ReferenceRepository.get_by_id(self.db, sug.reference_id)
        sug.reference = ref

        return sug

    def get_grounding_summary(self, document_id: int, user_id: int) -> Dict[str, Any]:
        doc = self._verify_document_ownership(document_id, user_id)
        
        report = self.doc_repo.get_latest_report(self.db, document_id)
        if not report:
            raise HTTPException(status_code=404, detail="Nenhum relatório de fundamentação gerado para este documento.")

        return {
            "grounding_score": doc.grounding_score,
            "supported_count": report.supported_count,
            "unsupported_count": report.unsupported_count,
            "outdated_count": report.outdated_count,
            "generated_at": report.generated_at
        }
