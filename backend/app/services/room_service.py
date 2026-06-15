from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.repositories import room_repository
from app.schemas.room_schema import RoomCreate, RoomUpdate


def create_room(db: Session, user_id: int, data: RoomCreate):
    return room_repository.create(db, user_id, data)


def get_room(db: Session, room_id: int):
    room = room_repository.get_by_id(db, room_id)
    if not room:
        raise NotFoundError("room not found")
    return room


def list_rooms(db: Session, user_id: int | None = None):
    return room_repository.get_list(db, user_id=user_id)


def update_room(db: Session, room_id: int, data: RoomUpdate):
    room = get_room(db, room_id)
    return room_repository.update(db, room, data)
