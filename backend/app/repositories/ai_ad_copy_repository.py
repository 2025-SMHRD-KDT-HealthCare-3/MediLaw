from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_ad_copy import AiAdCopy
from app.schemas.ai_ad_copy_schema import AiAdCopyCreate, AiAdCopyUpdate


def create(db: Session, data: AiAdCopyCreate, analysis: dict[str, str | None]) -> AiAdCopy:
    ai_copy = AiAdCopy(**data.model_dump(), **analysis)
    db.add(ai_copy)
    db.commit()
    db.refresh(ai_copy)
    return ai_copy


def get_by_id(db: Session, ai_copy_id: int) -> AiAdCopy | None:
    return db.get(AiAdCopy, ai_copy_id)


def get_list(db: Session, user_id: int | None = None, skip: int = 0, limit: int = 100) -> list[AiAdCopy]:
    # TODO: add date range and risky expression filters.
    stmt = select(AiAdCopy).order_by(AiAdCopy.created_at.desc())
    if user_id is not None:
        stmt = stmt.where(AiAdCopy.user_id == user_id)
    return list(db.scalars(stmt.offset(skip).limit(limit)).all())


def update(db: Session, ai_copy: AiAdCopy, data: AiAdCopyUpdate) -> AiAdCopy:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(ai_copy, key, value)
    db.commit()
    db.refresh(ai_copy)
    return ai_copy
