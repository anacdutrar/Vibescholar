from sqlalchemy.orm import Session
from typing import Optional
from app.models.project_settings import ProjectSettings
from app.schemas.request import ProjectSettingsUpdate

class ProjectSettingsRepository:
    @staticmethod
    def get_by_project_id(db: Session, project_id: int) -> Optional[ProjectSettings]:
        return db.query(ProjectSettings).filter(ProjectSettings.project_id == project_id).first()

    @staticmethod
    def create_default(db: Session, project_id: int) -> ProjectSettings:
        db_settings = ProjectSettings(
            project_id=project_id,
            preferred_language="pt",
            minimum_qualis="B1",
            publication_year_min=None,
            publication_year_max=None,
            preferred_sources=None,
            only_open_access=False,
            prefer_doi=False,
            max_suggestions=5
        )
        db.add(db_settings)
        db.commit()
        db.refresh(db_settings)
        return db_settings

    @staticmethod
    def update(db: Session, db_settings: ProjectSettings, settings_in: ProjectSettingsUpdate) -> ProjectSettings:
        for field, value in settings_in.model_dump(exclude_unset=True).items():
            setattr(db_settings, field, value)
        db.commit()
        db.refresh(db_settings)
        return db_settings
