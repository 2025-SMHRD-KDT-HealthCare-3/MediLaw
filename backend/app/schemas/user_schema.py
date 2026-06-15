from datetime import datetime

from pydantic import BaseModel, Field


class UserBase(BaseModel):
    login_id: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default="USER", max_length=20)


class UserCreate(UserBase):
    login_id: str = Field(max_length=50)
    password: str = Field(min_length=8)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)


class UserResponse(UserBase):
    user_id: int
    login_id: str
    role: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
