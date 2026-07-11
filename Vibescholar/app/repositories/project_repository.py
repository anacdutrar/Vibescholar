from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.models.user import Project
from app.schemas.request import ProjectCreate, ProjectUpdate

class ProjectRepository:
    @staticmethod
    def get_by_id(db: Session, project_id: int) -> Optional[Project]:
        return db.query(Project).filter(
            Project.id == project_id,
            Project.deleted_at.is_(None)
        ).first()

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> List[Project]:
        return db.query(Project).filter(
            Project.user_id == user_id,
            Project.deleted_at.is_(None)
        ).order_by(Project.created_at.desc()).all()

    @staticmethod
    def get_active_by_user_and_name(db: Session, user_id: int, name: str) -> Optional[Project]:
        return db.query(Project).filter(
            Project.user_id == user_id,
            Project.name == name,
            Project.deleted_at.is_(None)
        ).first()

    @staticmethod
    def get_deleted_by_user_and_name(db: Session, user_id: int, name: str) -> Optional[Project]:
        return db.query(Project).filter(
            Project.user_id == user_id,
            Project.name == name,
            Project.deleted_at.is_not(None)
        ).first()

    @staticmethod
    def restore(db: Session, project: Project, description: Optional[str]) -> Project:
        project.deleted_at = None
        project.description = description
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(project)
        return project

    @staticmethod
    def create(db: Session, user_id: int, project_in: ProjectCreate) -> Project:
        db_project = Project(
            user_id=user_id,
            name=project_in.name.strip(),
            description=project_in.description
        )
        db.add(db_project)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(db_project)
        return db_project

    @staticmethod
    def update(db: Session, project: Project, project_in: ProjectUpdate) -> Project:
        project.name = project_in.name
        project.description = project_in.description
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def soft_delete(db: Session, project: Project) -> Project:
        project.deleted_at = datetime.utcnow()
        db.commit()
        db.refresh(project)
        return project
