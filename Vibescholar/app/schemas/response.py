from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class ProjectSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    preferred_language: str
    minimum_qualis: str
    publication_year_min: Optional[int] = None
    publication_year_max: Optional[int] = None
    preferred_sources: Optional[str] = None
    only_open_access: bool
    prefer_doi: bool
    max_suggestions: int
    created_at: datetime
    updated_at: datetime

class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    description: Optional[str] = None
    created_at: datetime

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: Optional[str] = None
    content: Optional[str] = None
    current_version_id: Optional[int] = None
    grounding_score: float
    last_analyzed_at: datetime
    created_at: datetime
    updated_at: datetime

class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    content_snapshot: str
    created_by: str
    created_at: datetime

class SentenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_version_id: int
    sentence_uuid: str
    paragraph_number: int
    sentence_number: int
    position: float
    text: str
    status: str

class GroundingReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    generated_at: datetime
    supported_count: int
    unsupported_count: int
    partial_count: int
    outdated_count: int
    contradictions_count: int

class QualityIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    document_version_id: int
    sentence_uuid: Optional[str] = None
    issue_type: str
    description: str
    severity: float
    created_at: datetime

class ReferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: Optional[int] = None
    title: str
    authors: str
    journal: Optional[str] = None
    year: Optional[int] = None
    doi: Optional[str] = None
    qualis_score: Optional[str] = None
    abstract: Optional[str] = None
    availability: Optional[str] = None

class EvidenceSuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_version_id: int
    sentence_uuid: str
    reference_id: int
    status: str
    created_at: datetime
    reference: Optional[ReferenceOut] = None
