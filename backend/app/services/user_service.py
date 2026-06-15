from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.repositories import user_repository
from app.schemas.user_schema import UserUpdate


def get_me(db: Session, user_id: int):
    user = user_repository.get_by_id(db, user_id)
    if not user:
        raise NotFoundError("user not found")
    return user


def update_me(db: Session, user_id: int, data: UserUpdate):
    user = get_me(db, user_id)
    if data.email and data.email != user.email:
        existing = user_repository.get_by_email(db, data.email)
        if existing and existing.user_id != user.user_id:
            from app.core.exceptions import BadRequestError

            raise BadRequestError("email already exists")
    try:
        updated = user_repository.update(db, user, data)
        db.commit()
        db.refresh(updated)
        return updated
    except Exception:
        db.rollback()
        raise


def list_users(db: Session, skip: int = 0, limit: int = 100):
    return user_repository.get_list(db, skip=skip, limit=limit)
