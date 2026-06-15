from pydantic import BaseModel, Field, field_validator

from app.utils.validators import validate_email_format, validate_phone_number


class SignupRequest(BaseModel):
    login_id: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=72)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)

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


class LoginRequest(BaseModel):
    login_id: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("login_id", mode="before")
    @classmethod
    def strip_login_id(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LogoutResponse(BaseModel):
    message: str = "logged out"
