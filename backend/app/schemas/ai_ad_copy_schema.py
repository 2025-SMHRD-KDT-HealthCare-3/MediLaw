from datetime import datetime

from pydantic import BaseModel, Field


class AiAdCopyCreate(BaseModel):
    user_id: int
    input_language: str | None = Field(default=None, max_length=10)
    input_text: str


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
