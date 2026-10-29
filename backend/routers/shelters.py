from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.shelter_schema import ShelterCreate, ShelterResponse
from backend.services.shelter_service import (create_shelter,get_shelter,search_shelters)
from backend.utils.permissions import get_current_user, require_roles
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/shelters", tags=["Shelters"])
@router.get("", response_model=list[ShelterResponse])
def list_shelters(
    q: str = Query(default="", max_length=160),
    district: str | None = Query(default=None, max_length=100),
    available_only: bool = True,
    limit: int = Query(default=10, ge=1, le=25),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user)
):
    return search_shelters(db,query=q,district=district,available_only=available_only,limit=limit)
@router.get("/{shelter_id}", response_model=ShelterResponse)
def shelter_detail(shelter_id: int,db: Session = Depends(get_db),_user: User = Depends(get_current_user)):
    shelter = get_shelter(db, shelter_id)
    if shelter is None:
        raise HTTPException(status_code=404, detail="Shelter not found.")
    return shelter
@router.post("",response_model=ShelterResponse,status_code=201,)
def add_shelter(
    data: ShelterCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(Role.ADMIN)),
):
    try:
        return create_shelter(db, data.model_dump())
    except IntegrityError as exc:
        db.rollback()
        logger.exception("Shelter database integrity error")
        raise HTTPException(status_code=409,detail="Shelter data violates a database constraint.") from exc