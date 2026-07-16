from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from datetime import datetime
from app.models.reference import ProjectReference, EvidenceSuggestion
from app.schemas.request import ReferenceCreate
from app.core.logging import logger
from app.tools.schemas import ReferenceCandidate

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
        return db.query(ProjectReference).filter(
            ProjectReference.project_id.is_(None),
            ProjectReference.deleted_at.is_(None)
        ).all()

    @staticmethod
    def find_citation_matches(
        db: Session,
        project_id: int,
        doi: Optional[str] = None,
        author: Optional[str] = None,
        year: Optional[int] = None,
    ) -> List[ProjectReference]:
        base_query = db.query(ProjectReference).filter(
            or_(ProjectReference.project_id == project_id, ProjectReference.project_id.is_(None)),
            ProjectReference.deleted_at.is_(None),
        )
        if doi:
            doi_matches = base_query.filter(
                func.lower(ProjectReference.doi) == doi.strip().lower()
            ).all()
            if doi_matches:
                return doi_matches
        if author and year is not None:
            return base_query.filter(
                func.lower(ProjectReference.authors).contains(author.strip().lower()),
                ProjectReference.year == year,
            ).all()
        return []

    @staticmethod
    def find_active_by_doi_or_title_year(
        db: Session,
        doi: Optional[str],
        title: str,
        year: Optional[int],
    ) -> Optional[ProjectReference]:
        query = db.query(ProjectReference).filter(
            ProjectReference.project_id.is_(None),
            ProjectReference.deleted_at.is_(None),
        )
        if doi:
            found = query.filter(func.lower(ProjectReference.doi) == doi.strip().lower()).first()
            if found:
                return found
        return query.filter(
            func.lower(ProjectReference.title) == title.strip().lower(),
            ProjectReference.year == year,
        ).first()

    @staticmethod
    def find_project_candidate(
        db: Session,
        project_id: int,
        doi: Optional[str],
        title: str,
        year: Optional[int],
    ) -> Optional[ProjectReference]:
        """Find one active project reference by DOI, then exact title and year."""
        query = db.query(ProjectReference).filter(
            ProjectReference.project_id == project_id,
            ProjectReference.deleted_at.is_(None),
        )
        normalized_doi = doi.strip().lower() if doi else None
        if normalized_doi:
            found = query.filter(func.lower(ProjectReference.doi) == normalized_doi).first()
            if found:
                return found
        return query.filter(
            func.lower(ProjectReference.title) == title.strip().lower(),
            ProjectReference.year == year,
        ).first()

    @staticmethod
    def get_or_create_candidate(
        db: Session,
        project_id: int,
        candidate: ReferenceCandidate,
    ) -> tuple[ProjectReference, bool]:
        """Stage one deduplicated real candidate without committing the transaction."""
        reference = ReferenceRepository.find_project_candidate(
            db,
            project_id,
            candidate.doi,
            candidate.title,
            candidate.year,
        )
        if reference is not None:
            return reference, False
        reference = ProjectReference(
            project_id=project_id,
            title=candidate.title,
            authors="; ".join(candidate.authors),
            journal=candidate.journal,
            year=candidate.year,
            doi=candidate.doi,
            qualis_score=None,
            abstract=candidate.abstract,
            availability="ABERTO" if candidate.is_open_access is True else "FECHADO",
        )
        db.add(reference)
        db.flush()
        return reference, True

    @staticmethod
    def ensure_global_references(
        db: Session,
        payloads: list[dict],
    ) -> tuple[List[ProjectReference], list[int], list[int]]:
        references: List[ProjectReference] = []
        found_ids: list[int] = []
        created: List[ProjectReference] = []
        try:
            for payload in payloads:
                reference = ReferenceRepository.find_active_by_doi_or_title_year(
                    db,
                    payload.get("doi"),
                    payload["title"],
                    payload.get("year"),
                )
                if reference:
                    found_ids.append(reference.id)
                else:
                    reference = ProjectReference(project_id=None, **payload)
                    db.add(reference)
                    db.flush()
                    created.append(reference)
                references.append(reference)
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.exception("reference.mock.ensure rollback count=%s", len(payloads))
            raise
        return references, found_ids, [reference.id for reference in created]

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
        return db.query(EvidenceSuggestion).options(joinedload(EvidenceSuggestion.reference)).filter(
            EvidenceSuggestion.document_version_id == version_id
        ).all()

    @staticmethod
    def get_suggestions_by_version_and_sentence(
        db: Session, version_id: int, sentence_uuid: str
    ) -> List[EvidenceSuggestion]:
        return db.query(EvidenceSuggestion).options(joinedload(EvidenceSuggestion.reference)).filter(
            EvidenceSuggestion.document_version_id == version_id,
            EvidenceSuggestion.sentence_uuid == sentence_uuid,
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
    def get_or_stage_pending_suggestion(
        db: Session,
        version_id: int,
        sentence_uuid: str,
        reference_id: int,
    ) -> tuple[EvidenceSuggestion, bool]:
        """Reuse an existing suggestion or stage one pending suggestion without commit."""
        existing = ReferenceRepository.get_suggestion_by_version_and_sentence_and_ref(
            db,
            version_id,
            sentence_uuid,
            reference_id,
        )
        if existing is not None:
            return existing, False
        suggestion = EvidenceSuggestion(
            document_version_id=version_id,
            sentence_uuid=sentence_uuid,
            reference_id=reference_id,
            status="PENDING",
        )
        db.add(suggestion)
        db.flush()
        return suggestion, True

    @staticmethod
    def create_suggestion(db: Session, suggestion: EvidenceSuggestion) -> EvidenceSuggestion:
        try:
            db.add(suggestion)
            db.commit()
            db.refresh(suggestion)
            return suggestion
        except IntegrityError:
            db.rollback()
            logger.exception(
                "evidence.suggestion.create rollback version_id=%s sentence_uuid=%s reference_id=%s",
                suggestion.document_version_id,
                suggestion.sentence_uuid,
                suggestion.reference_id,
            )
            raise

    @staticmethod
    def bulk_create_suggestions(db: Session, suggestions: List[EvidenceSuggestion]):
        try:
            db.add_all(suggestions)
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.exception("evidence.suggestion.bulk_create rollback count=%s", len(suggestions))
            raise

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
