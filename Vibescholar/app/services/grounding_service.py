from fastapi import Depends, HTTPException
import re
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

    def search_sentence_evidence(self, sentence_id: int, user_id: int) -> List[EvidenceSuggestion]:
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
        existing_by_reference = {item.reference_id: item for item in existing}
        terminal_reference_ids = {
            item.reference_id for item in existing if item.status in {"APPROVED", "REJECTED"}
        }
        citation_hints = extract_citation_hints(sentence.text)
        citation_matches = []
        if citation_hints:
            citation_matches = ReferenceRepository.find_citation_matches(
                self.db,
                doc.project_id,
                doi=citation_hints.get("doi"),
                author=citation_hints.get("author"),
                year=citation_hints.get("year"),
            )
        citation_reference_ids = {reference.id for reference in citation_matches}
        logger.info(
            "evidence.search.citation sentence_id=%s pattern=%s reference_ids=%s",
            sentence.id,
            citation_hints.get("raw") if citation_hints else None,
            sorted(citation_reference_ids),
        )

        # Call EvidenceService search
        evidence_service = EvidenceService()
        try:
            matching_refs = evidence_service.search(
                self.db,
                sentence.text,
                doc.project_id,
                excluded_reference_ids=terminal_reference_ids,
            )
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

        provider_match_count = len(matching_refs)
        matching_refs = list({
            reference.id: reference
            for reference in list(citation_matches) + matching_refs
        }.values())
        if provider_match_count:
            matching_refs = matching_refs[:provider_match_count]

        suggestions = [item for item in existing if item.status == "APPROVED"]
        returned_ids = {item.id for item in suggestions}
        discarded_ids = []
        for ref in matching_refs:
            if ref.id is None or ref.id <= 0 or ReferenceRepository.get_by_id(self.db, ref.id) is None:
                discarded_ids.append(ref.id)
                continue
            # Check if suggestion already exists
            sug = existing_by_reference.get(ref.id)
            if not sug:
                sug = EvidenceSuggestion(
                    document_version_id=version.id,
                    sentence_uuid=sentence.sentence_uuid,
                    reference_id=ref.id,
                    status="PENDING"
                )
                try:
                    ReferenceRepository.create_suggestion(self.db, sug)
                except IntegrityError:
                    sug = ReferenceRepository.get_suggestion_by_version_and_sentence_and_ref(
                        self.db, version.id, sentence.sentence_uuid, ref.id
                    )
                    if not sug:
                        logger.warning(
                            "evidence.search controlled_integrity_error sentence_id=%s reference_id=%s",
                            sentence.id,
                            ref.id,
                        )
                        raise HTTPException(
                            status_code=409,
                            detail="Não foi possível registrar a sugestão de evidência.",
                        )
                existing_by_reference[ref.id] = sug

            sug.reference = ref
            if (
                sug.status != "REJECTED" or ref.id in citation_reference_ids
            ) and sug.id not in returned_ids:
                suggestions.append(sug)
                returned_ids.add(sug.id)

        logger.info(
            "evidence.search.completed sentence_id=%s discarded_ids=%s final_count=%s reference_ids=%s",
            sentence.id,
            discarded_ids,
            len(suggestions),
            [suggestion.reference_id for suggestion in suggestions],
        )

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
