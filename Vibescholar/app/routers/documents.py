import io
from fastapi import APIRouter, Depends, UploadFile, File, Form, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List, Optional

from app.routers.auth import get_current_user
from app.schemas.request import DocumentCreate, DocumentContentUpdate, DocumentUpdate
from app.schemas.response import DocumentOut, DocumentVersionOut
from app.services.document_service import DocumentService

router = APIRouter(tags=["Documents"])

@router.post("/api/projects/{project_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(
    project_id: int,
    doc_in: DocumentCreate,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Creates a new document, initializes its first version and extracts initial sentences.
    """
    return doc_service.create_document(project_id, doc_in, current_user.id, current_user.username)

@router.get("/api/projects/{project_id}/documents", response_model=List[DocumentOut])
def list_documents(
    project_id: int,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Lists all active documents in a project.
    """
    return doc_service.list_documents(project_id, current_user.id)

@router.get("/api/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: int,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Retrieves document metadata and grounding details.
    """
    return doc_service.get_document(document_id, current_user.id)

@router.delete("/api/documents/{document_id}", response_model=DocumentOut)
def delete_document(
    document_id: int,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Soft-deletes a document.
    """
    return doc_service.delete_document(document_id, current_user.id)

@router.put("/api/documents/{document_id}/content", response_model=DocumentOut)
def autosave_document_content(
    document_id: int,
    content_in: DocumentContentUpdate,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Updates the content directly in the database (used by debounced editor autosave).
    Does NOT create a version.
    """
    return doc_service.autosave_content(document_id, content_in.content, current_user.id)

@router.post("/api/documents/{document_id}/version")
def save_document_version(
    document_id: int,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Manually creates a new version snapshot, splits sentences, and runs grounding analysis.
    """
    result = doc_service.save_version(document_id, current_user.id, current_user.username)
    if isinstance(result, dict):
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=jsonable_encoder(result))

@router.get("/api/documents/{document_id}/versions", response_model=List[DocumentVersionOut])
def list_document_versions(
    document_id: int,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Lists the version history of a document.
    """
    return doc_service.list_versions(document_id, current_user.id)

@router.post("/api/documents/{document_id}/restore/{version_id}")
def restore_document_version(
    document_id: int,
    version_id: int,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Loads an old version snapshot into the current draft without creating a new version.
    """
    return doc_service.restore_version(document_id, version_id, current_user.id)

# --- UPLOAD / IMPORT ---
@router.post("/api/documents/import", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def import_document_file(
    project_id: int = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Uploads a file (.docx, .md, .txt), converts it to Markdown, and creates a Document.
    """
    file_bytes = file.file.read()
    return doc_service.import_document(project_id, title, file.filename, file_bytes, current_user.id, current_user.username)

# --- EXPORT ---
@router.get("/api/documents/{document_id}/export/{export_format}")
def export_document_file(
    document_id: int,
    export_format: str,
    current_user = Depends(get_current_user),
    doc_service: DocumentService = Depends()
):
    """
    Exports the document active version in the requested format (markdown, docx, pdf, bibtex, apa, abnt).
    """
    content, media_type, filename = doc_service.export_document(document_id, export_format, current_user.id)
    if isinstance(content, bytes):
        return StreamingResponse(io.BytesIO(content), media_type=media_type, headers={
            "Content-Disposition": f"attachment; filename={filename}"
        })
    else:
        return Response(content=content, media_type=media_type, headers={
            "Content-Disposition": f"attachment; filename={filename}"
        })
