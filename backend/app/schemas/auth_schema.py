from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    login_id: str = Field(max_length=50)
    password: str = Field(min_length=8)
    name: str | None = Field(default=None, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    login_id: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LogoutResponse(BaseModel):
    message: str = "logged out"
