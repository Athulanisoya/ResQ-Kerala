from datetime import datetime
from sqlalchemy import(Boolean,Column,DateTime,ForeignKey,Integer,String,Text)
from backend.database.connection import Base
class IncidentAnalysis(Base):
    __tablename__="incident_analyses"
    id=Column(Integer,primary_key=True,index=True)
    incident_id=Column(Integer,ForeignKey("incident_reports.id"),nullable=False,unique=True,index=True)
    severity=Column(String(20),nullable=False,default="UNKNOWN")
    extracted_location=Column(String(255),nullable=True)
    alert_match=Column("altert_match",String(20),nullable=False,default="UNCERTAIN")
    summary=Column(Text,nullable=True)
    requires_investigation=Column(Boolean,nullable=False,default=True)
    source=Column(String(30),nullable=False,default="MANUAL_DEMO")
    reviewed_by_user_id=Column(Integer,ForeignKey("users.id"),nullable=True)
    created_at=Column(DateTime,default=datetime.utcnow,nullable=False)
    updated_at=Column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow,nullable=False)
class InvestigationReport(Base):
   __tablename__="investigation_reports"
   id=Column(Integer,primary_key=True,index=True)
   incident_id=Column(Integer,ForeignKey("incident_reports.id"),nullable=False,unique=True,index=True)
   assigned_to_name=Column(String(120),nullable=False)
   status=Column(String(20),nullable=False,default="OPEN")
   findings=Column(Text,nullable=True)
   action_taken=Column(Text,nullable=True)
   created_by_user_id=Column(Integer,ForeignKey("users.id"),nullable=False)
   updated_by_user_id=Column(Integer,ForeignKey("users.id"),nullable=False)
   created_at=Column(DateTime,default=datetime.utcnow,nullable=False)
   updated_at=Column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow,nullable=False)

class InvestigationTeamAssignment(Base):
    """An explicit team identity, independent of display-only investigator names."""
    __tablename__ = "investigation_team_assignments"
    id = Column(Integer, primary_key=True)
    investigation_id = Column(Integer, ForeignKey("investigation_reports.id"), nullable=False, unique=True, index=True)
    team_id = Column(Integer, ForeignKey("response_teams.id"), nullable=False, index=True)
    assigned_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
