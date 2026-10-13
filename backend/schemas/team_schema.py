from pydantic import BaseModel


class AssignTeamRequest(BaseModel):
    incident_id: int
    team_id: int
    assignment_note: str | None = None