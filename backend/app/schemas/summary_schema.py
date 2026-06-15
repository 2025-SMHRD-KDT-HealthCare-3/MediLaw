from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.utils.validators import validate_file_reference


class SummaryCreate(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=10000)
    checklist_item: str | None = Field(default=None, min_length=1, max_length=10000)
    summary_file: str | None = Field(default=None, max_length=255)

    @field_validator("summary", "checklist_item", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("summary_file")
    @classmethod
    def validate_summary_file(cls, value: str | None) -> str | None:
        return validate_file_reference(value) if value else value


class SummaryUpdate(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=10000)
    checklist_item: str | None = Field(default=None, min_length=1, max_length=10000)
    summary_file: str | None = Field(default=None, max_length=255)
    is_confirmed: bool | None = None

    @field_validator("summary", "checklist_item", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("summary_file")
    @classmethod
    def validate_summary_file(cls, value: str | None) -> str | None:
        return validate_file_reference(value) if value else value


class SummaryResponse(BaseModel):
    summary_id: int
    room_id: int
    admin_id: int
    summary: str | None
    checklist_item: str | None
    summary_file: str | None
    is_confirmed: bool
    created_at: datetime

    model_config = {"from_attributes": True}
