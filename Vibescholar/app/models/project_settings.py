from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class ProjectSettings(Base):
    __tablename__ = "project_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)
    
    preferred_language = Column(String(50), default="pt")
    minimum_qualis = Column(String(10), default="B1")
    publication_year_min = Column(Integer, nullable=True)
    publication_year_max = Column(Integer, nullable=True)
    preferred_sources = Column(Text, nullable=True)  # JSON-encoded array or comma-separated list
    only_open_access = Column(Boolean, default=False)
    prefer_doi = Column(Boolean, default=False)
    max_suggestions = Column(Integer, default=5)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="settings")
