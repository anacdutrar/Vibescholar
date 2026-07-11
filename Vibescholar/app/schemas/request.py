from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    email: Optional[EmailStr] = None

class UserLogin(BaseModel):
    username: str
    password: str

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None

class ProjectSettingsUpdate(BaseModel):
    preferred_language: Optional[str] = "pt"
    minimum_qualis: Optional[str] = "B1"
    publication_year_min: Optional[int] = None
    publication_year_max: Optional[int] = None
    preferred_sources: Optional[str] = None
    only_open_access: Optional[bool] = False
    prefer_doi: Optional[bool] = False
    max_suggestions: Optional[int] = 5

class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    content: Optional[str] = ""

class DocumentUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None

class DocumentContentUpdate(BaseModel):
    content: str

class DocumentVersionCreate(BaseModel):
    created_by: str

class ReferenceCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    authors: str
    journal: Optional[str] = None
    year: Optional[int] = None
    doi: Optional[str] = None
    qualis_score: Optional[str] = None
    abstract: Optional[str] = None
    availability: Optional[str] = "FECHADO"

class EvidenceStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(PENDING|APPROVED|REJECTED)$")
