from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from backend.models.shelter import Shelter
def search_shelters(db: Session,query: str = "",district: str | None = None,available_only: bool = True,limit: int = 10):
    statement = select(Shelter)
    query = (query or "").strip()
    district = (district or "").strip()
    if query:
        pattern = f"%{query}%"
        statement = statement.where(or_(
                Shelter.name.ilike(pattern),
                Shelter.district.ilike(pattern),
                Shelter.locality.ilike(pattern),
                Shelter.address.ilike(pattern),
            )
        )

    if district:
        statement = statement.where(
            Shelter.district.ilike(f"%{district}%")
        )
    if available_only:
        statement = statement.where(
            Shelter.status == "OPEN",
            Shelter.occupied < Shelter.capacity
        )

    statement = statement.order_by(Shelter.district,Shelter.locality,Shelter.name).limit(max(1, min(limit, 25)))

    return list(db.scalars(statement).all())
def get_shelter(db: Session, shelter_id: int):
    return db.get(Shelter, shelter_id)
def create_shelter(db: Session, values: dict):
    shelter = Shelter(**values)
    db.add(shelter)
    db.commit()
    db.refresh(shelter)
    return shelter