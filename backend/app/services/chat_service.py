import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories import chat_repository
from app.schemas.chat_schema import ChatCreate
from app.services.room_service import ensure_room_access, ensure_room_open

logger = logging.getLogger(__name__)


def create_chat(db: Session, room_id: int, current_user: User, data: ChatCreate):
    """Store a user chat message after room access validation."""
    ensure_room_open(db, room_id, current_user)
    payload = data.model_copy(
        update={"chatter_id": current_user.user_id, "speaker_type": "USER"}
    )
    try:
        chat = chat_repository.create(db, room_id, payload)
        db.commit()
        db.refresh(chat)
        return chat
    except Exception:
        logger.exception("chat create failed room_id=%s user_id=%s", room_id, current_user.user_id)
        db.rollback()
        raise


def list_chats(db: Session, room_id: int, current_user: User, skip: int = 0, limit: int = 100):
    ensure_room_access(db, room_id, current_user)
    return chat_repository.get_list(db, room_id=room_id, skip=skip, limit=limit)
