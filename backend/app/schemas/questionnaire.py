from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# Drives frontend branching for the Technical Details section — see
# app/models/questionnaire.py docstring.
INVENTION_TYPES = ("Software", "Mechanical", "Electronics", "Biotech", "Chemistry")
QUESTIONNAIRE_STATUSES = ("Not Started", "In Progress", "Completed")


class QuestionnaireUpdate(BaseModel):
    """Partial update — every field optional so the frontend can autosave
    section-by-section as the Innovator works through the guided flow."""

    invention_type: str | None = Field(
        default=None, pattern="^(" + "|".join(INVENTION_TYPES) + ")$"
    )
    problem_statement: str | None = None
    proposed_solution: str | None = None
    novelty_description: str | None = None
    technical_description: str | None = None
    advantages: str | None = None
    prior_art: str | None = None
    keywords: str | None = None
    has_existing_drawings: bool | None = None


class QuestionnaireOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    questionnaire_status: str | None
    completion_percentage: Decimal | None
    invention_type: str | None
    problem_statement: str | None
    proposed_solution: str | None
    novelty_description: str | None
    technical_description: str | None
    advantages: str | None
    prior_art: str | None
    keywords: str | None
    has_existing_drawings: bool | None
    created_at: datetime
    updated_at: datetime


class QuestionnaireVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    questionnaire_id: int
    patent_application_id: int
    version_number: int
    version_status: str | None
    invention_type: str | None
    problem_statement: str | None
    proposed_solution: str | None
    novelty_description: str | None
    technical_description: str | None
    advantages: str | None
    prior_art: str | None
    keywords: str | None
    change_reason: str | None
    created_by: int | None
