from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.chat import Chat
from app.models.evidence import Evidence
from app.models.room import Room
from app.models.summary import Summary
from app.models.verification import Verification
from app.schemas.room_schema import RoomCreate, RoomUpdate


def create(db: Session, user_id: int, data: RoomCreate) -> Room:
    room = Room(**data.model_dump(), user_id=user_id)
    db.add(room)
    db.flush()
    db.refresh(room)
    return room


def get_by_id(db: Session, room_id: int) -> Room | None:
    return db.get(Room, room_id)


def get_list(db: Session, user_id: int | None = None, skip: int = 0, limit: int = 100) -> list[Room]:
    # TODO: add room_status filtering and access control conditions.
    stmt = select(Room).order_by(Room.created_at.desc(), Room.room_id.desc())
    if user_id is not None:
        stmt = stmt.where(Room.user_id == user_id)
    return list(db.scalars(stmt.offset(skip).limit(limit)).all())


def update(db: Session, room: Room, data: RoomUpdate) -> Room:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(room, key, value)
    db.flush()
    db.refresh(room)
    return room


def delete_with_children(db: Session, room: Room) -> None:
    chat_ids = select(Chat.chat_id).where(Chat.room_id == room.room_id)
    db.execute(
        delete(Evidence)
        .where(Evidence.ans_id.in_(chat_ids))
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(Verification)
        .where(Verification.ans_id.in_(chat_ids))
        .execution_options(synchronize_session=False)
    )
    db.execute(delete(Summary).where(Summary.room_id == room.room_id))
    db.execute(delete(Chat).where(Chat.room_id == room.room_id))
    db.delete(room)
    db.flush()
