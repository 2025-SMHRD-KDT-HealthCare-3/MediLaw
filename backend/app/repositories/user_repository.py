from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user_schema import UserCreate, UserUpdate


def create(db: Session, data: UserCreate, password_hash: str) -> User:
    payload = data.model_dump(exclude={"password"})
    user = User(**payload, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_by_login_id(db: Session, login_id: str) -> User | None:
    return db.scalar(select(User).where(User.login_id == login_id))


def get_list(db: Session, skip: int = 0, limit: int = 100) -> list[User]:
    # TODO: add filtering and pagination policy.
    return list(db.scalars(select(User).offset(skip).limit(limit)).all())


def update(db: Session, user: User, data: UserUpdate) -> User:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user
