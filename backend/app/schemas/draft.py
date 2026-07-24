from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AIOutputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    questionnaire_version_id: int
    section_type: str
    version_number: int
    ai_provider: str | None
    ai_model: str | None
    ai_response: str | None
    processing_status: str | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


class DraftSectionSlot(BaseModel):
    """One row per known section type — `latest` is null if that section
    has never been generated for the current questionnaire version."""

    section_type: str
    latest: AIOutputOut | None


class GenerateDraftRequest(BaseModel):
    # Omit or pass null to (re)generate every known section; pass a subset
    # to regenerate just those (e.g. ["CLAIMS"]).
    section_types: list[str] | None = None


class GenerateDraftResponse(BaseModel):
    questionnaire_version_id: int
    questionnaire_version_number: int
    outputs: list[AIOutputOut]
