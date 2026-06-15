from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


VerificationStatus = Literal["CONFIRMED", "WARNING", "ERROR"]


class VerificationCreate(BaseModel):
    ans_id: int
    user_id: int
    law_name: str | None = Field(default=None, max_length=255)
    article_no: str | None = Field(default=None, max_length=100)
    article_exists: bool = False
    content_matches: bool = False
    effective_date_valid: bool = False
    verification_status: VerificationStatus = "WARNING"
    confidence_score: Decimal | None = Field(default=None, ge=0, le=100)
    verification_reason: str | None = None


class VerificationUpdate(BaseModel):
    article_exists: bool | None = None
    content_matches: bool | None = None
    effective_date_valid: bool | None = None
    verification_status: VerificationStatus | None = None
    confidence_score: Decimal | None = Field(default=None, ge=0, le=100)
    verification_reason: str | None = None


class VerificationResponse(VerificationCreate):
    verification_id: int
    verified_at: datetime

    model_config = {"from_attributes": True}
