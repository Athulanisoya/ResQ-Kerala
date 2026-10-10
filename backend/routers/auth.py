from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..database.connection import get_db
from ..schemas.auth import AuthResponse, LoginRequest, RegisterRequest
from ..services import auth_service
from ..utils.permissions import Principal, get_principal


router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """Create a citizen account. Privileged roles cannot be self-registered."""
    return auth_service.register(db, data)


@router.post("/login", response_model=AuthResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    return auth_service.login(db, data)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Revoke the current bearer session immediately."""
    auth_service.logout(db, principal.session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
