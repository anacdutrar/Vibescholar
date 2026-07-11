from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
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

    def list_document_sentences(self, document_id: int, user_id: int) -> List[Sentence]:
        doc = self._verify_document_ownership(document_id, user_id)
        if not doc.current_version_id:
            return []
        return self.doc_repo.get_sentences_by_version(self.db, doc.current_version_id)

    def search_sentence_evidence(self, sentence_id: int, user_id: int) -> List[EvidenceSuggestion]:
        # Fetch sentence
        sentence = self.db.query(Sentence).filter(Sentence.id == sentence_id).first()
        if not sentence:
            raise HTTPException(status_code=404, detail="Sentença não encontrada.")

        # Fetch version and document context to verify permission
        version = self.doc_repo.get_version_by_id(self.db, sentence.document_version_id)
        doc = self._verify_document_ownership(version.document_id, user_id)

        # Call EvidenceService search
        evidence_service = EvidenceService()
        matching_refs = evidence_service.search(self.db, sentence.text, doc.project_id)

        suggestions = []
        for ref in matching_refs:
            # Check if suggestion already exists
            sug = ReferenceRepository.get_suggestion_by_version_and_sentence_and_ref(
                self.db, version.id, sentence.sentence_uuid, ref.id
            )
            if not sug:
                sug = EvidenceSuggestion(
                    document_version_id=version.id,
                    sentence_uuid=sentence.sentence_uuid,
                    reference_id=ref.id,
                    status="PENDING"
                )
                ReferenceRepository.create_suggestion(self.db, sug)
            
            sug.reference = ref
            suggestions.append(sug)

        return suggestions

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
