from fastapi import APIRouter, Depends
from backend.database.connection import get_db
from backend.models import Role
from backend.utils.permissions import require_roles
from backend.services.shelter_facilities_service import FacilitiesInput, update

router = APIRouter(prefix='/api/shelters', tags=['Shelter facilities'])

@router.patch('/{shelter_id}/facilities')
def confirm(shelter_id: int, data: FacilitiesInput, db=Depends(get_db), user=Depends(require_roles(Role.ADMIN, Role.RESPONSE_TEAM))):
    return update(db, shelter_id, user, data)
