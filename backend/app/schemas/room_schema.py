from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

RoomStatus = Literal["ACTIVE", "CLOSED"]


class RoomCreate(BaseModel):
    room_title: str = Field(min_length=1, max_length=255)
    room_desc: str | None = Field(default=None, max_length=2000)
    room_limit: int | None = Field(default=None, ge=1, le=100)
    room_status: RoomStatus = "ACTIVE"

    @field_validator("room_title", mode="before")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class RoomUpdate(BaseModel):
    room_title: str | None = Field(default=None, min_length=1, max_length=255)
    room_desc: str | None = Field(default=None, max_length=2000)
    room_limit: int | None = Field(default=None, ge=1, le=100)
    room_status: RoomStatus | None = None

    @field_validator("room_title", mode="before")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class RoomResponse(BaseModel):
    room_id: int
    user_id: int
    room_title: str
    room_desc: str | None
    room_limit: int | None
    room_status: str
    created_at: datetime

    model_config = {"from_attributes": True}
