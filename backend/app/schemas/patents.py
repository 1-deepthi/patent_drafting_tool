from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PatentCreate(BaseModel):
    team_id: int
    invention_title: str = Field(min_length=1, max_length=500)


class PatentUpdate(BaseModel):
    invention_title: str = Field(min_length=1, max_length=500)


class PatentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_id: int
    invention_title: str
    application_status: str
    assigned_patent_agent_id: int | None
    ai_status: str | None
    questionnaire_status: str | None
    document_status: str | None
    filing_status: str | None
    official_application_number: str | None
    filing_date: datetime | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class AssignAgentRequest(BaseModel):
    # Explicit agent choice. Omit entirely (or POST to the /auto-assign
    # endpoint) to let the platform pick by workload instead.
    patent_agent_id: int


class RejectAssignmentRequest(BaseModel):
    reason: str | None = None


class AvailableAgentOut(BaseModel):
    id: int
    full_name: str
    email: str
    active_assignment_count: int
