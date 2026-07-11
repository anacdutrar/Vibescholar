from fastapi import APIRouter, Depends, status
from typing import List

from app.core.logging import logger
from app.routers.auth import get_current_user
from app.schemas.request import ProjectCreate, ProjectUpdate, ProjectSettingsUpdate
from app.schemas.response import ProjectOut, ProjectSettingsOut
from app.services.project_service import ProjectService

router = APIRouter(tags=["Projects"])

@router.get("/api/projects", response_model=List[ProjectOut])
def list_projects(
    current_user = Depends(get_current_user),
    project_service: ProjectService = Depends()
):
    """
    Lists all active projects owned by the currently authenticated user.
    """
    return project_service.list_projects(current_user.id)

@router.post("/api/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    project_in: ProjectCreate,
    current_user = Depends(get_current_user),
    project_service: ProjectService = Depends()
):
    """
    Creates a new research project and initializes its default settings.
    """
    logger.info(
        "projects.create router reached user_id=%s payload=%s",
        current_user.id,
        {"name": project_in.name, "description": project_in.description}
    )
    return project_service.create_project(current_user.id, project_in)

@router.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    current_user = Depends(get_current_user),
    project_service: ProjectService = Depends()
):
    """
    Retrieves project details.
    """
    return project_service.get_project(project_id, current_user.id)

@router.put("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    current_user = Depends(get_current_user),
    project_service: ProjectService = Depends()
):
    """
    Updates an existing project name or description.
    """
    return project_service.update_project(project_id, current_user.id, project_in)

@router.delete("/api/projects/{project_id}", response_model=ProjectOut)
def delete_project(
    project_id: int,
    current_user = Depends(get_current_user),
    project_service: ProjectService = Depends()
):
    """
    Soft-deletes a project.
    """
    return project_service.delete_project(project_id, current_user.id)

# --- SETTINGS ---

@router.get("/api/projects/{project_id}/settings", response_model=ProjectSettingsOut)
def get_project_settings(
    project_id: int,
    current_user = Depends(get_current_user),
    project_service: ProjectService = Depends()
):
    """
    Retrieves settings for a specific project.
    """
    return project_service.get_settings(project_id, current_user.id)

@router.put("/api/projects/{project_id}/settings", response_model=ProjectSettingsOut)
def update_project_settings(
    project_id: int,
    settings_in: ProjectSettingsUpdate,
    current_user = Depends(get_current_user),
    project_service: ProjectService = Depends()
):
    """
    Updates project settings.
    """
    return project_service.update_settings(project_id, current_user.id, settings_in)
