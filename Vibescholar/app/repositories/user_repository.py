from sqlalchemy.orm import Session
from typing import Optional
from app.models.user import User
from app.schemas.request import UserCreate
from app.core.security import hash_password

class UserRepository:
    @staticmethod
    def get_by_id(db: Session, user_id: int) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_by_username(db: Session, username: str) -> Optional[User]:
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def create(db: Session, user_in: UserCreate) -> User:
        db_user = User(
            username=user_in.username,
            password_hash=hash_password(user_in.password),
            email=user_in.email
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
