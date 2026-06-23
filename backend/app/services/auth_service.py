import logging

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.security import create_access_token, get_password_hash, verify_password
from app.repositories import user_repository
from app.schemas.auth_schema import LoginRequest, SignupRequest, TokenResponse
from app.schemas.user_schema import UserCreate

logger = logging.getLogger(__name__)


def signup(db: Session, data: SignupRequest):
    """Create a user with hashed password after duplicate checks."""
    if user_repository.get_by_login_id(db, data.login_id):
        raise BadRequestError("login_id already exists")
    if data.email and user_repository.get_by_email(db, data.email):
        raise BadRequestError("email already exists")
    user_data = UserCreate(**data.model_dump())
    try:
        user = user_repository.create(db, user_data, get_password_hash(data.password))
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        logger.exception("signup failed login_id=%s", data.login_id)
        db.rollback()
        raise


def login(db: Session, data: LoginRequest) -> TokenResponse:
    """Validate credentials and issue an access token."""
    user = user_repository.get_by_login_id(db, data.login_id)
    if not user or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("invalid login_id or password")
    token = create_access_token(str(user.user_id))
    return TokenResponse(access_token=token)
