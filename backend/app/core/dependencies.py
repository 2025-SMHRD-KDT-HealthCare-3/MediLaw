from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories import user_repository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    payload = decode_access_token(token)
    subject = payload.get("sub") if payload else None
    if subject is None:
        raise UnauthorizedError("invalid or expired token")
    try:
        return int(subject)
    except ValueError as exc:
        raise UnauthorizedError("invalid token subject") from exc


def get_current_user(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
) -> User:
    user = user_repository.get_by_id(db, current_user_id)
    if user is None:
        raise UnauthorizedError("user not found")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "ADMIN":
        raise UnauthorizedError("admin permission required")
    return current_user
