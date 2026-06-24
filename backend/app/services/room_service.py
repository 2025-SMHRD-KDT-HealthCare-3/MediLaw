import logging

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.models.user import User
from app.repositories import room_repository
from app.schemas.room_schema import RoomCreate, RoomUpdate

logger = logging.getLogger(__name__)


def create_room(db: Session, user_id: int, data: RoomCreate):
    """Create a room owned by the current user."""
    payload = data.model_copy(update={"room_status": "ACTIVE"})
    try:
        room = room_repository.create(db, user_id, payload)
        db.commit()
        db.refresh(room)
        return room
    except Exception:
        logger.exception("room create failed user_id=%s", user_id)
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


def leave_room(db: Session, room_id: int, current_user: User):
    """Validate access for a UI leave action without changing persisted room state."""
    return ensure_room_access(db, room_id, current_user)


def close_room(db: Session, room_id: int, current_user: User):
    """Close a room so existing history remains readable but new chat is blocked."""
    room = ensure_room_access(db, room_id, current_user)
    if room.room_status == "CLOSED":
        return room
    try:
        updated = room_repository.update(db, room, RoomUpdate(room_status="CLOSED"))
        db.commit()
        db.refresh(updated)
        return updated
    except Exception:
        logger.exception("room close failed room_id=%s user_id=%s", room_id, current_user.user_id)
        db.rollback()
        raise


def delete_room(db: Session, room_id: int, current_user: User) -> dict:
    """Delete a room and its stored conversation history."""
    room = ensure_room_access(db, room_id, current_user)
    try:
        room_repository.delete_with_children(db, room)
        db.commit()
        return {"room_id": room_id, "deleted": True}
    except Exception:
        logger.exception("room delete failed room_id=%s user_id=%s", room_id, current_user.user_id)
        db.rollback()
        raise


def update_room(db: Session, room_id: int, data: RoomUpdate, current_user: User):
    room = ensure_room_access(db, room_id, current_user)
    try:
        updated = room_repository.update(db, room, data)
        db.commit()
        db.refresh(updated)
        return updated
    except Exception:
        logger.exception("room update failed room_id=%s user_id=%s", room_id, current_user.user_id)
        db.rollback()
        raise
