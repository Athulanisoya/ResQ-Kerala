from fastapi import APIRouter, Depends
from backend.database.connection import get_db
from backend.utils.permissions import get_current_user
from backend.services import preparedness_service as service

router = APIRouter(prefix='/api/preparedness', tags=['Private household preparedness'])
@router.get('/guidance')
def guidance(_user=Depends(get_current_user)): return service.guidance()
@router.get('/me')
def mine(db=Depends(get_db), user=Depends(get_current_user)): return service.read(db, user)
@router.put('/me')
def save(data: service.PlanInput, db=Depends(get_db), user=Depends(get_current_user)): return service.save(db, user, data)
