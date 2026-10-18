from datetime import datetime
from typing import Literal
from pydantic import (BaseModel,ConfigDict,Field,field_validator)
Severity=Literal["LOW","MEDIUM","HIGH","UNKNOWN"]
AlertMatch=Literal["MATCH","NO_MATCH","UNCERTAIN","NOT_CHECKED"]
class AnalysisUpsert(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    severity: Severity = "UNKNOWN"
    extracted_location: str | None = Field(default=None, max_length=255)
    alert_match:AlertMatch="NOT_CHECKED"
    summary: str | None = Field(default=None)
    requires_investigation: bool = Field(default=True)
    source:Literal["MANUAL_DEMO","AI_MODULE"]="MANUAL_DEMO"



    @field_validator("extracted_location","summary")
    @classmethod
    def blank_to_none(cls,value):
        return value or None
class AnalysisResponse(BaseModel):
        model_config=ConfigDict(from_attributes=True)
        id:int
        incident_id:int
        severity:str
        extracted_location:str|None
        alert_match:str
        summary:str|None
        requires_investigation:bool
        source:str
        reviewed_by_user_id:int|None
        created_at:datetime
        updated_at:datetime
class InvestigationStart(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    assigned_to_name:str=Field(min_length=2,max_length=120)
class InvestigationUpdate(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    status: Literal["IN_PROGRESS","COMPLETED",]
    findings: str = Field(min_length=5,max_length=5000,)
    action_taken: str | None = Field(default=None,max_length=2000,)
    @field_validator("action_taken")
    @classmethod
    def blank_to_none(cls, value):
        return value or None
class InvestigationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    incident_id: int
    assigned_to_name: str
    status: str
    findings: str | None
    action_taken: str | None
    created_by_user_id: int
    updated_by_user_id: int
    created_at: datetime
    updated_at: datetime
