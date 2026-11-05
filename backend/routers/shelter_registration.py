from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import User
from backend.schemas.shelter_registration_schema import ShelterRegistrationCreate, ShelterRegistrationStatus
from backend.services import shelter_registration_service as service
from backend.utils.permissions import get_current_user


router = APIRouter(tags=["Shelter registrations"])


@router.get("/api/shelter-registrations")
def own_registrations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_registrations(db, user)


@router.get("/api/shelters/{shelter_id}/registrations")
def registrations(shelter_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_registrations(db, user, shelter_id)


@router.post("/api/shelters/{shelter_id}/registrations", status_code=201)
def reserve(shelter_id: int, data: ShelterRegistrationCreate, response: Response,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result, created = service.reserve(db, user, shelter_id, data)
    response.status_code = 201 if created else 200
    return result


@router.patch("/api/shelter-registrations/{registration_id}/status")
def status(registration_id: int, data: ShelterRegistrationStatus,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.change_status(db, user, registration_id, data)
