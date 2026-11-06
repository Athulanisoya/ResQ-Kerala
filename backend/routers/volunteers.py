"""Volunteer records are private to the applicant and administrators."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.volunteer_schema import (ApplicationReview, Attendance, ShiftCreate, ShiftSignup,
                                               ShiftUpdate, VersionNote, VolunteerInput)
from backend.services import volunteer_service as service
from backend.utils.permissions import require_roles

router = APIRouter(prefix='/api/volunteers', tags=['Volunteers'])
citizen = require_roles(Role.CITIZEN)
admin = require_roles(Role.ADMIN)
member = require_roles(Role.CITIZEN, Role.ADMIN)


@router.get('/catalog')
def catalog(_user: User = Depends(member)):
    return service.catalog()


@router.get('/me')
def mine(db: Session = Depends(get_db), user: User = Depends(citizen)):
    return service.my_application(db, user)


@router.put('/me')
def apply(data: VolunteerInput, db: Session = Depends(get_db), user: User = Depends(citizen)):
    return service.save_application(db, user, data)


@router.get('/admin/applications')
def applications(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
                 db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.list_applications(db, user, offset=offset, limit=limit)


@router.post('/admin/applications/{application_id}/review')
def review(application_id: int, data: ApplicationReview, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.review_application(db, user, application_id, data)


@router.get('/shifts')
def shifts(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
           db: Session = Depends(get_db), user: User = Depends(member)):
    return service.list_shifts(db, user, offset=offset, limit=limit)


@router.post('/shifts', status_code=201)
def create(data: ShiftCreate, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.create_shift(db, user, data)


@router.put('/shifts/{shift_id}')
def update(shift_id: int, data: ShiftUpdate, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.update_shift(db, user, shift_id, data)


@router.post('/shifts/{shift_id}/cancel')
def cancel(shift_id: int, data: VersionNote, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.cancel_shift(db, user, shift_id, data)


@router.post('/shifts/{shift_id}/signup')
def join(shift_id: int, data: ShiftSignup, db: Session = Depends(get_db), user: User = Depends(citizen)):
    return service.join_shift(db, user, shift_id, data)


@router.post('/signups/{signup_id}/cancel')
def leave(signup_id: int, data: VersionNote, db: Session = Depends(get_db), user: User = Depends(citizen)):
    return service.cancel_signup(db, user, signup_id, data)


@router.get('/admin/shifts/{shift_id}/roster')
def roster(shift_id: int, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.roster(db, user, shift_id)


@router.post('/admin/signups/{signup_id}/attendance')
def attendance(signup_id: int, data: Attendance, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.record_attendance(db, user, signup_id, data)
