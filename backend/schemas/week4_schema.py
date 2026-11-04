from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
class Week4WorkflowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "incomplete", "failed","error", "not_run"]
    incident_id: int
    revision: int | None = None
    original_text: str
    reported_facts: dict[str, Any] = Field(default_factory=dict)
    original_text_sha256: str | None = None
    model: str | None = None
    results: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    tool_events: list[dict[str, Any]] = Field(default_factory=list)
    agent_response: str | None = None
    warning: str | None = None
    human_review_required: bool = True
    orchestration_mode: str | None = None
    llm_used: bool | None = None
    translation: str | None = None
    generative_summary: str | None = None
    language_draft_status: str | None = None


class Week4ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    suggestion_key: str = Field(min_length=1, max_length=50)
    decision: Literal["accepted", "edited", "rejected"]
    value: str | None = Field(default=None, max_length=5000)
    note: str | None = Field(default=None, max_length=1000)
    expected_review_id: int = Field(default=0, ge=0)
