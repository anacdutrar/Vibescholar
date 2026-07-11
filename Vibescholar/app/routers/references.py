from fastapi import APIRouter, Depends, UploadFile, File, status
from typing import List, Optional

from app.routers.auth import get_current_user
from app.schemas.request import ReferenceCreate
from app.schemas.response import ReferenceOut
from app.services.reference_service import ReferenceService

router = APIRouter(tags=["References"])

@router.get("/api/references", response_model=List[ReferenceOut])
def list_references(
    project_id: Optional[int] = None,
    current_user = Depends(get_current_user),
    ref_service: ReferenceService = Depends()
):
    """
    Lists global references or references associated with a specific project.
    """
    return ref_service.list_references(project_id, current_user.id)

@router.post("/api/projects/{project_id}/references", response_model=ReferenceOut, status_code=status.HTTP_201_CREATED)
def create_reference(
    project_id: int,
    ref_in: ReferenceCreate,
    current_user = Depends(get_current_user),
    ref_service: ReferenceService = Depends()
):
    """
    Manually adds a new reference to the project library.
    """
    return ref_service.create_reference(project_id, ref_in, current_user.id)

@router.put("/api/references/{reference_id}", response_model=ReferenceOut)
def update_reference(
    reference_id: int,
    ref_in: ReferenceCreate,
    current_user = Depends(get_current_user),
    ref_service: ReferenceService = Depends()
):
    """
    Updates an existing reference's metadata.
    """
    return ref_service.update_reference(reference_id, ref_in, current_user.id)

@router.delete("/api/references/{reference_id}", response_model=ReferenceOut)
def delete_reference(
    reference_id: int,
    current_user = Depends(get_current_user),
    ref_service: ReferenceService = Depends()
):
    """
    Soft-deletes a reference.
    """
    return ref_service.delete_reference(reference_id, current_user.id)

@router.post("/api/projects/{project_id}/references/import", response_model=List[ReferenceOut], status_code=status.HTTP_201_CREATED)
def import_references(
    project_id: int,
    file: UploadFile = File(...),
    current_user = Depends(get_current_user),
    ref_service: ReferenceService = Depends()
):
    """
    Imports bibliography references from BibTeX, CSV or JSON.
    """
    file_content = file.file.read()
    return ref_service.import_references(project_id, file.filename, file_content, current_user.id)
