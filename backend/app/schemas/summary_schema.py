from datetime import datetime

from pydantic import BaseModel, Field


class SummaryCreate(BaseModel):
    admin_id: int
    summary: str | None = None
    checklist_item: str | None = None
    summary_file: str | None = Field(default=None, max_length=255)


class SummaryUpdate(BaseModel):
    summary: str | None = None
    checklist_item: str | None = None
    summary_file: str | None = Field(default=None, max_length=255)
    is_confirmed: bool | None = None


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
