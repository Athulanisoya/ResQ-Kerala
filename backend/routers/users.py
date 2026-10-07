from fastapi import APIRouter, Depends

from ..models import User
from ..schemas.auth import UserResponse
from ..utils.permissions import get_current_user


router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user
