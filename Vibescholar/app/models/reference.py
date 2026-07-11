from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class ProjectReference(Base):
    __tablename__ = "project_references"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)  # NULL = Global reference
    title = Column(String(255), nullable=False)
    authors = Column(Text, nullable=False)  # Raw names or JSON list of authors
    journal = Column(String(255), nullable=True)
    year = Column(Integer, nullable=True)
    doi = Column(String(100), nullable=True)
    qualis_score = Column(String(10), nullable=True)  # Qualis values (e.g. A1, A2, B1, etc.)
    abstract = Column(Text, nullable=True)
    availability = Column(String(20), default="FECHADO")  # ABERTO or FECHADO (Open Access status)
    deleted_at = Column(DateTime, nullable=True)

    # Indexes
    __table_args__ = (
        Index("idx_project_references_project_id", "project_id"),
    )

    # Relationships
    project = relationship("Project", back_populates="references")
    evidence_suggestions = relationship("EvidenceSuggestion", back_populates="reference", cascade="all, delete-orphan")


class EvidenceSuggestion(Base):
    __tablename__ = "evidence_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=False)
    sentence_uuid = Column(String(255), nullable=False)
    reference_id = Column(Integer, ForeignKey("project_references.id"), nullable=False)
    status = Column(String(20), default="PENDING")  # PENDING, APPROVED, REJECTED
    created_at = Column(DateTime, default=datetime.utcnow)

    # Constraints & Indexes
    __table_args__ = (
        UniqueConstraint("document_version_id", "sentence_uuid", "reference_id", name="uq_version_sentence_ref"),
        Index("idx_evidence_version_id", "document_version_id"),
        Index("idx_evidence_uuid", "sentence_uuid"),
    )

    # Relationships
    version = relationship("DocumentVersion", back_populates="evidence_suggestions")
    reference = relationship("ProjectReference", back_populates="evidence_suggestions")
