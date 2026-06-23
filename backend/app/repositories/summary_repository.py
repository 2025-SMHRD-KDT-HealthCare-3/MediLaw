from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.summary import Summary
from app.schemas.summary_schema import SummaryCreate, SummaryUpdate


def create(db: Session, room_id: int, admin_id: int, data: SummaryCreate) -> Summary:
    summary = Summary(**data.model_dump(), room_id=room_id, admin_id=admin_id)
    db.add(summary)
    db.flush()
    db.refresh(summary)
    return summary


def get_by_id(db: Session, summary_id: int) -> Summary | None:
    return db.get(Summary, summary_id)


def get_list(db: Session, room_id: int | None = None, skip: int = 0, limit: int = 100) -> list[Summary]:
    # TODO: add admin and confirmation status filters.
    stmt = select(Summary).order_by(Summary.created_at.desc())
    if room_id is not None:
        stmt = stmt.where(Summary.room_id == room_id)
    return list(db.scalars(stmt.offset(skip).limit(limit)).all())


def get_unconfirmed_for_room(db: Session, room_id: int) -> Summary | None:
    stmt = (
        select(Summary)
        .where(Summary.room_id == room_id, Summary.is_confirmed.is_(False))
        .order_by(Summary.created_at.desc(), Summary.summary_id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def update(db: Session, summary: Summary, data: SummaryUpdate) -> Summary:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(summary, key, value)
    db.flush()
    db.refresh(summary)
    return summary
