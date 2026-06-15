from datetime import datetime

from pydantic import BaseModel, Field


class RoomCreate(BaseModel):
    room_title: str = Field(max_length=255)
    room_desc: str | None = None
    room_limit: int | None = None
    room_status: str = Field(default="OPEN", max_length=10)


class RoomUpdate(BaseModel):
    room_title: str | None = Field(default=None, max_length=255)
    room_desc: str | None = None
    room_limit: int | None = None
    room_status: str | None = Field(default=None, max_length=10)


class RoomResponse(BaseModel):
    room_id: int
    user_id: int
    room_title: str
    room_desc: str | None
    room_limit: int | None
    room_status: str
    created_at: datetime

    model_config = {"from_attributes": True}
