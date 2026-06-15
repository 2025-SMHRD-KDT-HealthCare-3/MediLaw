from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.security import create_access_token, get_password_hash, verify_password
from app.repositories import user_repository
from app.schemas.auth_schema import LoginRequest, SignupRequest, TokenResponse
from app.schemas.user_schema import UserCreate


def signup(db: Session, data: SignupRequest):
    if user_repository.get_by_login_id(db, data.login_id):
        raise BadRequestError("login_id already exists")
    user_data = UserCreate(**data.model_dump())
    return user_repository.create(db, user_data, get_password_hash(data.password))


def login(db: Session, data: LoginRequest) -> TokenResponse:
    user = user_repository.get_by_login_id(db, data.login_id)
    if not user or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("invalid login_id or password")
    token = create_access_token(str(user.user_id))
    return TokenResponse(access_token=token)
