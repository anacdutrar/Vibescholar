from fastapi import APIRouter, Depends, Response, Cookie, status
from typing import Optional
from app.core.logging import logger
from app.schemas.request import UserCreate, UserLogin
from app.schemas.response import UserOut
from app.services.auth_service import AuthService, get_current_user_dep

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, auth_service: AuthService = Depends()):
    """
    Registers a new user and hashes their password.
    """
    logger.info(
        "auth.register router reached payload=%s",
        {"username": user_in.username, "email": user_in.email, "password": "<omitted>"}
    )
    return auth_service.register(user_in)

@router.post("/login", response_model=UserOut)
def login(user_in: UserLogin, response: Response, auth_service: AuthService = Depends()):
    """
    Logs in a user, setting an HttpOnly session cookie.
    """
    return auth_service.login(user_in, response)

@router.post("/logout")
def logout(response: Response, auth_service: AuthService = Depends()):
    """
    Logs out the user by clearing the session cookie.
    """
    return auth_service.logout(response)

# Expose get_current_user dependency for other routers
get_current_user = get_current_user_dep
