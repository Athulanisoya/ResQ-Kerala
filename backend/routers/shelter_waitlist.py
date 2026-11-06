from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import User
from backend.schemas.shelter_waitlist_schema import ShelterWaitlistAction, ShelterWaitlistCreate
from backend.services import shelter_waitlist_service as service
from backend.utils.permissions import get_current_user


router = APIRouter(tags=["Shelter waiting lists"])


@router.get("/api/shelter-waitlist")
def own_waitlist(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_waitlist(db, user)


@router.get("/api/shelters/{shelter_id}/waitlist")
def shelter_waitlist(shelter_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_waitlist(db, user, shelter_id)


@router.post("/api/shelters/{shelter_id}/waitlist", status_code=201)
def join(shelter_id: int, data: ShelterWaitlistCreate, response: Response,
         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result, created = service.join(db, user, shelter_id, data)
    response.status_code = 201 if created else 200
    return result


@router.post("/api/shelter-waitlist/{entry_id}/accept")
def accept(entry_id: int, data: ShelterWaitlistAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.accept(db, user, entry_id, data)


@router.post("/api/shelter-waitlist/{entry_id}/cancel")
def cancel(entry_id: int, data: ShelterWaitlistAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.cancel(db, user, entry_id, data)
