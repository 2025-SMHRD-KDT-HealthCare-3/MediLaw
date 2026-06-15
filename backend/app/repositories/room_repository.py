from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.room import Room
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
    stmt = select(Room)
    if user_id is not None:
        stmt = stmt.where(Room.user_id == user_id)
    return list(db.scalars(stmt.offset(skip).limit(limit)).all())


def update(db: Session, room: Room, data: RoomUpdate) -> Room:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(room, key, value)
    db.flush()
    db.refresh(room)
    return room
