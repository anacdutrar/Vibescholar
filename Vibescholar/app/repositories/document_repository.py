from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime
from app.models.document import Document, DocumentVersion, Sentence, GroundingReport, QualityIssue
from app.schemas.request import DocumentCreate

class DocumentRepository:
    # --- DOCUMENT CRUD ---
    @staticmethod
    def get_by_id(db: Session, doc_id: int) -> Optional[Document]:
        return db.query(Document).filter(
            Document.id == doc_id,
            Document.deleted_at.is_(None)
        ).first()

    @staticmethod
    def list_by_project(db: Session, project_id: int) -> List[Document]:
        return db.query(Document).filter(
            Document.project_id == project_id,
            Document.deleted_at.is_(None)
        ).order_by(Document.created_at.desc()).all()

    @staticmethod
    def create(db: Session, project_id: int, doc_in: DocumentCreate) -> Document:
        db_doc = Document(
            project_id=project_id,
            title=doc_in.title,
            description=doc_in.description,
            content=doc_in.content,
            grounding_score=0.0
        )
        db.add(db_doc)
        db.commit()
        db.refresh(db_doc)
        return db_doc

    @staticmethod
    def update_content(db: Session, doc_id: int, content: str) -> Document:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.content = content
            doc.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(doc)
        return doc

    @staticmethod
    def update_version_id(db: Session, doc_id: int, version_id: int) -> Document:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.current_version_id = version_id
            db.commit()
            db.refresh(doc)
        return doc

    @staticmethod
    def update_grounding_score(db: Session, doc_id: int, score: float) -> Document:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.grounding_score = score
            doc.last_analyzed_at = datetime.utcnow()
            db.commit()
            db.refresh(doc)
        return doc

    @staticmethod
    def soft_delete(db: Session, doc: Document) -> Document:
        doc.deleted_at = datetime.utcnow()
        db.commit()
        db.refresh(doc)
        return doc

    # --- DOCUMENT VERSIONS ---
    @staticmethod
    def create_version(db: Session, doc_id: int, content_snapshot: str, created_by: str, version_number: int) -> DocumentVersion:
        version = DocumentVersion(
            document_id=doc_id,
            version_number=version_number,
            content_snapshot=content_snapshot,
            created_by=created_by
        )
        db.add(version)
        db.commit()
        db.refresh(version)
        return version

    @staticmethod
    def get_version_by_id(db: Session, version_id: int) -> Optional[DocumentVersion]:
        return db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()

    @staticmethod
    def get_latest_version(db: Session, doc_id: int) -> Optional[DocumentVersion]:
        return db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id
        ).order_by(desc(DocumentVersion.version_number)).first()

    @staticmethod
    def list_versions(db: Session, doc_id: int) -> List[DocumentVersion]:
        return db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id
        ).order_by(desc(DocumentVersion.version_number)).all()

    @staticmethod
    def count_versions(db: Session, doc_id: int) -> int:
        return db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id
        ).count()

    # --- SENTENCES ---
    @staticmethod
    def get_sentences_by_version(db: Session, version_id: int) -> List[Sentence]:
        return db.query(Sentence).filter(
            Sentence.document_version_id == version_id
        ).order_by(Sentence.paragraph_number, Sentence.sentence_number).all()

    @staticmethod
    def get_sentence_by_uuid_and_version(db: Session, version_id: int, sentence_uuid: str) -> Optional[Sentence]:
        return db.query(Sentence).filter(
            Sentence.document_version_id == version_id,
            Sentence.sentence_uuid == sentence_uuid
        ).first()

    @staticmethod
    def bulk_create_sentences(db: Session, sentences: List[Sentence]):
        db.add_all(sentences)
        db.commit()

    @staticmethod
    def delete_sentences_by_version(db: Session, version_id: int):
        db.query(Sentence).filter(Sentence.document_version_id == version_id).delete()
        db.commit()

    @staticmethod
    def update_sentence_status(db: Session, sentence_id: int, status: str):
        sentence = db.query(Sentence).filter(Sentence.id == sentence_id).first()
        if sentence:
            sentence.status = status
            db.commit()

    # --- GROUNDING REPORTS ---
    @staticmethod
    def create_report(db: Session, report: GroundingReport) -> GroundingReport:
        db.add(report)
        db.commit()
        db.refresh(report)
        return report

    @staticmethod
    def get_latest_report(db: Session, doc_id: int) -> Optional[GroundingReport]:
        return db.query(GroundingReport).filter(
            GroundingReport.document_id == doc_id
        ).order_by(desc(GroundingReport.generated_at)).first()

    # --- QUALITY ISSUES ---
    @staticmethod
    def get_issues_by_version(db: Session, version_id: int) -> List[QualityIssue]:
        return db.query(QualityIssue).filter(QualityIssue.document_version_id == version_id).all()

    @staticmethod
    def bulk_create_issues(db: Session, issues: List[QualityIssue]):
        db.add_all(issues)
        db.commit()

    @staticmethod
    def delete_issues_by_version(db: Session, version_id: int):
        db.query(QualityIssue).filter(QualityIssue.document_version_id == version_id).delete()
        db.commit()
