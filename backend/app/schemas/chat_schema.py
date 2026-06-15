from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SpeakerType = Literal["USER", "AI", "ADMIN"]


class ChatCreate(BaseModel):
    chatter_id: int | None = None
    speaker_type: SpeakerType = "USER"
    chat_text: str | None = None
    chat_emoticon: str | None = Field(default=None, max_length=255)
    chat_file: str | None = Field(default=None, max_length=255)


class ChatUpdate(BaseModel):
    chat_text: str | None = None
    chat_emoticon: str | None = Field(default=None, max_length=255)
    chat_file: str | None = Field(default=None, max_length=255)


class ChatResponse(BaseModel):
    chat_id: int
    room_id: int
    chatter_id: int | None
    speaker_type: SpeakerType
    chat_text: str | None
    chat_emoticon: str | None
    chat_file: str | None
    chatted_at: datetime

    model_config = {"from_attributes": True}
