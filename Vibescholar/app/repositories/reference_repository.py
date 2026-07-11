from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import datetime
from app.models.reference import ProjectReference, EvidenceSuggestion
from app.schemas.request import ReferenceCreate

class ReferenceRepository:
    # --- REFERENCE CRUD ---
    @staticmethod
    def get_by_id(db: Session, ref_id: int) -> Optional[ProjectReference]:
        return db.query(ProjectReference).filter(
            ProjectReference.id == ref_id,
            ProjectReference.deleted_at.is_(None)
        ).first()

    @staticmethod
    def list_by_project(db: Session, project_id: Optional[int] = None) -> List[ProjectReference]:
        # Excludes soft-deleted references.
        # Fetches global references (project_id IS NULL) + project-specific ones if project_id is provided.
        if project_id is not None:
            return db.query(ProjectReference).filter(
                or_(ProjectReference.project_id == project_id, ProjectReference.project_id.is_(None)),
                ProjectReference.deleted_at.is_(None)
            ).all()
        else:
            return db.query(ProjectReference).filter(
                ProjectReference.project_id.is_(None),
                ProjectReference.deleted_at.is_(None)
            ).all()

    @staticmethod
    def create(db: Session, ref_in: ReferenceCreate, project_id: Optional[int] = None) -> ProjectReference:
        db_ref = ProjectReference(
            project_id=project_id,
            title=ref_in.title,
            authors=ref_in.authors,
            journal=ref_in.journal,
            year=ref_in.year,
            doi=ref_in.doi,
            qualis_score=ref_in.qualis_score,
            abstract=ref_in.abstract,
            availability=ref_in.availability
        )
        db.add(db_ref)
        db.commit()
        db.refresh(db_ref)
        return db_ref

    @staticmethod
    def update(db: Session, ref: ProjectReference, ref_in: ReferenceCreate) -> ProjectReference:
        ref.title = ref_in.title
        ref.authors = ref_in.authors
        ref.journal = ref_in.journal
        ref.year = ref_in.year
        ref.doi = ref_in.doi
        ref.qualis_score = ref_in.qualis_score
        ref.abstract = ref_in.abstract
        ref.availability = ref_in.availability
        db.commit()
        db.refresh(ref)
        return ref

    @staticmethod
    def soft_delete(db: Session, ref: ProjectReference) -> ProjectReference:
        ref.deleted_at = datetime.utcnow()
        db.commit()
        db.refresh(ref)
        return ref

    # --- EVIDENCE SUGGESTIONS ---
    @staticmethod
    def get_suggestion_by_id(db: Session, suggestion_id: int) -> Optional[EvidenceSuggestion]:
        return db.query(EvidenceSuggestion).filter(EvidenceSuggestion.id == suggestion_id).first()

    @staticmethod
    def get_suggestions_by_version(db: Session, version_id: int) -> List[EvidenceSuggestion]:
        return db.query(EvidenceSuggestion).filter(
            EvidenceSuggestion.document_version_id == version_id
        ).all()

    @staticmethod
    def get_suggestion_by_version_and_sentence_and_ref(
        db: Session, version_id: int, sentence_uuid: str, ref_id: int
    ) -> Optional[EvidenceSuggestion]:
        return db.query(EvidenceSuggestion).filter(
            EvidenceSuggestion.document_version_id == version_id,
            EvidenceSuggestion.sentence_uuid == sentence_uuid,
            EvidenceSuggestion.reference_id == ref_id
        ).first()

    @staticmethod
    def create_suggestion(db: Session, suggestion: EvidenceSuggestion) -> EvidenceSuggestion:
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)
        return suggestion

    @staticmethod
    def bulk_create_suggestions(db: Session, suggestions: List[EvidenceSuggestion]):
        db.add_all(suggestions)
        db.commit()

    @staticmethod
    def update_suggestion_status(db: Session, suggestion: EvidenceSuggestion, status: str) -> EvidenceSuggestion:
        suggestion.status = status
        db.commit()
        db.refresh(suggestion)
        return suggestion

    @staticmethod
    def delete_suggestions_by_version(db: Session, version_id: int):
        db.query(EvidenceSuggestion).filter(EvidenceSuggestion.document_version_id == version_id).delete()
        db.commit()
