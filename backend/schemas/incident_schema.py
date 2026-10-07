from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class IncidentCreate(BaseModel):
    message: str
    location: str
    disaster_type: str = "Flood"
    people_affected: Optional[int] = None
    help_required: Optional[str] = None

class IncidentResponse(BaseModel): 
    id: int
    message: str
    location: str
    disaster_type: str
    people_affected: Optional[int] = None
    help_required: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class IncidentStatusUpdate(BaseModel):
    status: str
