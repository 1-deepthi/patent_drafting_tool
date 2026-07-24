from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class TeamCreate(BaseModel):
    team_name: str = Field(min_length=1, max_length=255)


class TeamUpdate(BaseModel):
    team_name: str | None = Field(default=None, min_length=1, max_length=255)
    team_status: str | None = None  # ACTIVE / ARCHIVED


class TeamMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    email: str
    full_name: str
    membership_status: str | None
    added_by: int | None


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_name: str
    team_status: str
    created_by: int | None
    created_at: datetime
    member_count: int
    patent_count: int


class TeamDetailOut(TeamOut):
    members: list[TeamMemberOut]


class AddTeamMemberRequest(BaseModel):
    email: EmailStr
