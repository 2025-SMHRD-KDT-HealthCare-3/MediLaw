from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.validators import validate_file_reference


SpeakerType = Literal["USER", "AI", "ADMIN"]


class ChatCreate(BaseModel):
    chatter_id: int | None = None
    speaker_type: SpeakerType = "USER"
    chat_text: str | None = Field(default=None, min_length=1, max_length=10000)
    chat_emoticon: str | None = Field(default=None, max_length=255)
    chat_file: str | None = Field(default=None, max_length=255)

    @field_validator("chat_text", "chat_emoticon", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("chat_file")
    @classmethod
    def validate_chat_file(cls, value: str | None) -> str | None:
        return validate_file_reference(value) if value else value

    @model_validator(mode="after")
    def require_message_content(self) -> "ChatCreate":
        if not self.chat_text and not self.chat_emoticon and not self.chat_file:
            raise ValueError("chat_text, chat_emoticon, or chat_file is required")
        return self


class ChatUpdate(BaseModel):
    chat_text: str | None = Field(default=None, min_length=1, max_length=10000)
    chat_emoticon: str | None = Field(default=None, max_length=255)
    chat_file: str | None = Field(default=None, max_length=255)

    @field_validator("chat_text", "chat_emoticon", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("chat_file")
    @classmethod
    def validate_chat_file(cls, value: str | None) -> str | None:
        return validate_file_reference(value) if value else value


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
