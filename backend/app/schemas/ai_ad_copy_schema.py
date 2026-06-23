from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AiAdCopyCreate(BaseModel):
    input_language: Literal["ko", "en"] = "ko"
    input_text: str = Field(min_length=1, max_length=5000)
    room_id: int | None = Field(default=None, ge=1)

    @field_validator("input_text", mode="before")
    @classmethod
    def strip_input_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class AiAdCopyUpdate(BaseModel):
    risky_expression: str | None = None
    legal_basis: str | None = None
    revision_recomm: str | None = None
    alternative_text: str | None = None


class AiAdCopyResponse(BaseModel):
    ai_copy_id: int
    user_id: int
    input_language: str | None
    input_text: str
    english_text: str | None
    translated_text: str | None
    risky_expression: str | None
    legal_basis: str | None
    revision_recomm: str | None
    alternative_text: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
