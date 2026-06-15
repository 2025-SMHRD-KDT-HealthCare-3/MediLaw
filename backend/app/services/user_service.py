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
    return user_repository.update(db, user, data)


def list_users(db: Session):
    return user_repository.get_list(db)
