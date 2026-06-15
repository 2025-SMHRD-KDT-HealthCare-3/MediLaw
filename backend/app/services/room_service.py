from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.models.user import User
from app.repositories import room_repository
from app.schemas.room_schema import RoomCreate, RoomUpdate


def create_room(db: Session, user_id: int, data: RoomCreate):
    """Create a room owned by the current user."""
    payload = data.model_copy(update={"room_status": "ACTIVE"})
    try:
        room = room_repository.create(db, user_id, payload)
        db.commit()
        db.refresh(room)
        return room
    except Exception:
        db.rollback()
        raise


def get_room(db: Session, room_id: int):
    room = room_repository.get_by_id(db, room_id)
    if not room:
        raise NotFoundError("room not found")
    return room


def ensure_room_access(db: Session, room_id: int, current_user: User):
    room = get_room(db, room_id)
    if current_user.role != "ADMIN" and room.user_id != current_user.user_id:
        raise ForbiddenError("room access denied")
    return room


def ensure_room_open(db: Session, room_id: int, current_user: User):
    room = ensure_room_access(db, room_id, current_user)
    if room.room_status != "ACTIVE":
        raise BadRequestError("room is not active")
    return room


def list_rooms(db: Session, current_user: User, skip: int = 0, limit: int = 100):
    # TODO: admins may use richer filters for all rooms in a dashboard.
    user_id = None if current_user.role == "ADMIN" else current_user.user_id
    return room_repository.get_list(db, user_id=user_id, skip=skip, limit=limit)


def update_room(db: Session, room_id: int, data: RoomUpdate, current_user: User):
    room = ensure_room_access(db, room_id, current_user)
    try:
        updated = room_repository.update(db, room, data)
        db.commit()
        db.refresh(updated)
        return updated
    except Exception:
        db.rollback()
        raise
