from datetime import datetime
from sqlalchemy import (Column,Integer,String,Text,DateTime,ForeignKey)
from backend.database.connection import Base
class Incident(Base):
    __tablename__="incident_reports"
    id=Column(Integer,primary_key=True,index=True)
    report_refernce=Column(String(50),unique=True,nullable=False,index=True)
    user_id=Column(Integer,nullable=False,index=True)
    message=Column(Text,nullable=False)
    location=Column(String(255),nullable=False)
    people_affected=Column(Integer,nullable=True)
    help_required=Column(String(255),nullable=True)
    status=Column(String(50),nullable=False,default="SUBMITTED")
    created_at=Column(DateTime,default=datetime.utcnow,nullable=False)
    updated_at=Column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow,nullable=False)
class IncidentStatusHistory(Base):
    __tablename__="status_history"
    id=Column(Integer,primary_key=True,index=True)
    incident_id=Column(Integer,ForeignKey("incident_reports.id"),nullable=False,index=True)
    status=Column(String(50),nullable=False)
    note=Column(Text,nullable=True)
    created_at=Column(DateTime,default=datetime.utcnow,nullable=False)
    