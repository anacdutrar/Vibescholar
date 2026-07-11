from fastapi import Depends, Response, Cookie
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.repositories.user_repository import UserRepository
from app.schemas.request import UserCreate, UserLogin
from app.core.security import verify_password
from app.exceptions.auth import CredentialsException, UserAlreadyExistsException
from app.models.user import User

class AuthService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    def register(self, user_in: UserCreate) -> User:
        existing_user = UserRepository.get_by_username(self.db, user_in.username)
        if existing_user:
            raise UserAlreadyExistsException()
        return UserRepository.create(self.db, user_in)

    def login(self, user_in: UserLogin, response: Response) -> User:
        user = UserRepository.get_by_username(self.db, user_in.username)
        if not user or not verify_password(user_in.password, user.password_hash):
            raise CredentialsException("Usuário ou senha incorretos.")
        
        response.set_cookie(
            key="session_username",
            value=user.username,
            httponly=True,
            max_age=3600 * 24,
            samesite="lax",
            secure=False
        )
        return user

    def logout(self, response: Response):
        response.delete_cookie(key="session_username")
        return {"message": "Logout efetuado com sucesso."}

    def get_current_user(self, session_username: Optional[str] = Cookie(None)) -> User:
        if not session_username:
            raise CredentialsException("Não autenticado. Sessão expirada ou inexistente.")
        user = UserRepository.get_by_username(self.db, session_username)
        if not user:
            raise CredentialsException("Usuário não encontrado.")
        return user

def get_current_user_dep(
    session_username: Optional[str] = Cookie(None),
    auth_service: AuthService = Depends()
) -> User:
    return auth_service.get_current_user(session_username)
