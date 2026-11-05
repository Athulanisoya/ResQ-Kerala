"""Authenticated geography and current coverage for each role's Overview."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import User
from backend.services.overview_map_service import district_boundaries, map_payload
from backend.utils.permissions import get_current_user


router = APIRouter(prefix="/api/overview", tags=["Overview map"])


@router.get("/map")
def current_map(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return map_payload(db, user)


@router.get("/district-boundaries")
def boundaries(_user: User = Depends(get_current_user)):
    return district_boundaries()
