from datetime import datetime

from pydantic import BaseModel, Field


class EvidenceCreate(BaseModel):
    ans_id: int
    law_name: str | None = Field(default=None, max_length=255)
    article_no: str | None = Field(default=None, max_length=100)
    core_basis: str | None = None
    source_url: str | None = Field(default=None, max_length=2048)


class EvidenceUpdate(BaseModel):
    law_name: str | None = Field(default=None, max_length=255)
    article_no: str | None = Field(default=None, max_length=100)
    core_basis: str | None = None
    source_url: str | None = Field(default=None, max_length=2048)


class EvidenceResponse(EvidenceCreate):
    evidence_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
