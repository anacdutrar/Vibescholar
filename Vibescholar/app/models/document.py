from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    current_version_id = Column(
        Integer, 
        ForeignKey("document_versions.id", use_alter=True, name="fk_document_current_version"), 
        nullable=True
    )
    grounding_score = Column(Float, default=0.0)
    deleted_at = Column(DateTime, nullable=True)
    last_analyzed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="documents")
    versions = relationship(
        "DocumentVersion", 
        foreign_keys="[DocumentVersion.document_id]", 
        back_populates="document", 
        cascade="all, delete-orphan"
    )
    active_version = relationship(
        "DocumentVersion", 
        foreign_keys=[current_version_id], 
        post_update=True
    )
    grounding_reports = relationship("GroundingReport", back_populates="document", cascade="all, delete-orphan")
    quality_issues = relationship("QualityIssue", back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    content_snapshot = Column(Text, nullable=False)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Constraints & Indexes
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
        Index("idx_doc_versions_doc_id", "document_id"),
    )

    # Relationships
    document = relationship(
        "Document", 
        foreign_keys=[document_id], 
        back_populates="versions"
    )
    sentences = relationship("Sentence", back_populates="version", cascade="all, delete-orphan")
    evidence_suggestions = relationship("EvidenceSuggestion", back_populates="version", cascade="all, delete-orphan")
    quality_issues = relationship("QualityIssue", back_populates="version", cascade="all, delete-orphan")


class Sentence(Base):
    __tablename__ = "sentences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=False)
    sentence_uuid = Column(String(255), nullable=False)
    paragraph_number = Column(Integer, nullable=False)
    sentence_number = Column(Integer, nullable=False)
    position = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String(20), default="UNVERIFIED")

    # Constraints & Indexes
    __table_args__ = (
        UniqueConstraint("document_version_id", "paragraph_number", "sentence_number", name="uq_sentence_position"),
        Index("idx_sentences_version_id", "document_version_id"),
        Index("idx_sentences_uuid", "sentence_uuid"),
    )

    # Relationships
    version = relationship("DocumentVersion", back_populates="sentences")


class GroundingReport(Base):
    __tablename__ = "grounding_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)
    supported_count = Column(Integer, default=0)
    unsupported_count = Column(Integer, default=0)
    partial_count = Column(Integer, default=0)
    outdated_count = Column(Integer, default=0)
    contradictions_count = Column(Integer, default=0)

    # Constraints & Indexes
    __table_args__ = (
        UniqueConstraint("document_id", "generated_at", name="uq_document_report_time"),
    )

    # Relationships
    document = relationship("Document", back_populates="grounding_reports")


class QualityIssue(Base):
    __tablename__ = "quality_issues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    document_version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=False)
    sentence_uuid = Column(String(255), nullable=True)
    issue_type = Column(String(50), nullable=False)  # e.g., LACK_OF_EVIDENCE, CONTRADICTION, OUTDATED
    description = Column(Text, nullable=False)
    severity = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index("idx_quality_issues_version_id", "document_version_id"),
    )

    # Relationships
    document = relationship("Document", back_populates="quality_issues")
    version = relationship("DocumentVersion", back_populates="quality_issues")
