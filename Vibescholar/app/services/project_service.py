from fastapi import Depends, HTTPException
from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_settings_repository import ProjectSettingsRepository
from app.models.user import Project
from app.models.project_settings import ProjectSettings
from app.schemas.request import ProjectCreate, ProjectUpdate, ProjectSettingsUpdate
from app.exceptions.document import ProjectNotFoundException

class ProjectService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    def _verify_project_ownership(self, project_id: int, user_id: int) -> Project:
        project = ProjectRepository.get_by_id(self.db, project_id)
        if not project or project.user_id != user_id:
            raise ProjectNotFoundException(project_id)
        return project

    def list_projects(self, user_id: int) -> List[Project]:
        return ProjectRepository.list_by_user(self.db, user_id)

    def create_project(self, user_id: int, project_in: ProjectCreate) -> Project:
        project_name = project_in.name.strip()
        existing_project = ProjectRepository.get_active_by_user_and_name(self.db, user_id, project_name)
        if existing_project:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe um projeto com esse nome."
            )

        normalized_project = ProjectCreate(name=project_name, description=project_in.description)
        try:
            project = ProjectRepository.create(self.db, user_id, normalized_project)
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe um projeto com esse nome."
            )

        try:
            ProjectSettingsRepository.create_default(self.db, project.id)
        except IntegrityError:
            self.db.rollback()
            raise
        return project

    def get_project(self, project_id: int, user_id: int) -> Project:
        return self._verify_project_ownership(project_id, user_id)

    def update_project(self, project_id: int, user_id: int, project_in: ProjectUpdate) -> Project:
        project = self._verify_project_ownership(project_id, user_id)
        return ProjectRepository.update(self.db, project, project_in)

    def delete_project(self, project_id: int, user_id: int) -> Project:
        project = self._verify_project_ownership(project_id, user_id)
        return ProjectRepository.soft_delete(self.db, project)

    def get_settings(self, project_id: int, user_id: int) -> ProjectSettings:
        self._verify_project_ownership(project_id, user_id)
        settings = ProjectSettingsRepository.get_by_project_id(self.db, project_id)
        if not settings:
            settings = ProjectSettingsRepository.create_default(self.db, project_id)
        return settings

    def update_settings(self, project_id: int, user_id: int, settings_in: ProjectSettingsUpdate) -> ProjectSettings:
        self._verify_project_ownership(project_id, user_id)
        db_settings = ProjectSettingsRepository.get_by_project_id(self.db, project_id)
        if not db_settings:
            db_settings = ProjectSettingsRepository.create_default(self.db, project_id)
        return ProjectSettingsRepository.update(self.db, db_settings, settings_in)
