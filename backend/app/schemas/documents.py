from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    change_summary: str | None
    generated_by: int | None
    generated_at: datetime | None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    template_id: int | None
    document_type: str | None
    output_format: str
    watermark_status: str | None
    generated_by: int | None
    generated_at: datetime | None


class DocumentGenerationJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    status: str
    triggered_by: int
    retried_from_job_id: int | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class GenerateDocumentRequest(BaseModel):
    # PDF is the default for every role; DOCX is selectable only by the
    # Patent Agent (enforced in the endpoint, not here).
    output_format: str = "PDF"
    document_type: str | None = None  # defaults to the sole V1 type if omitted
