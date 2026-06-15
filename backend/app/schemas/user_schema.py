from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.validators import validate_email_format, validate_phone_number


class UserBase(BaseModel):
    login_id: str | None = Field(default=None, min_length=3, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    role: Literal["USER", "ADMIN"] | None = "USER"

    @field_validator("login_id", "name", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return validate_email_format(value) if value else value

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return validate_phone_number(value) if value else value


class UserCreate(UserBase):
    login_id: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=72)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return validate_email_format(value) if value else value

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return validate_phone_number(value) if value else value


class UserResponse(UserBase):
    user_id: int
    login_id: str
    role: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
