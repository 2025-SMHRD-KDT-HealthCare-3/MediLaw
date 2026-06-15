from sqlalchemy.orm import Session

from app.ai.summary_generator import generate_summary_stub
from app.core.exceptions import NotFoundError
from app.models.user import User
from app.repositories import chat_repository, summary_repository
from app.schemas.summary_schema import SummaryCreate, SummaryUpdate
from app.services.room_service import ensure_room_access


def create_summary(db: Session, room_id: int, current_user: User, data: SummaryCreate):
    """Generate and store a room summary using chat history."""
    ensure_room_access(db, room_id, current_user)
    chats = [
        {
            "speaker_type": chat.speaker_type,
            "chat_text": chat.chat_text,
            "chatted_at": chat.chatted_at.isoformat(),
        }
        for chat in chat_repository.get_list(db, room_id=room_id)
    ]
    generated = generate_summary_stub(chats)
    payload = data.model_copy(
        update={
            "summary": data.summary or generated["summary"],
            "checklist_item": data.checklist_item or generated["checklist_item"],
        }
    )
    try:
        summary = summary_repository.create(db, room_id, current_user.user_id, payload)
        db.commit()
        db.refresh(summary)
        return summary
    except Exception:
        db.rollback()
        raise


def list_room_summaries(
    db: Session,
    room_id: int,
    current_user: User,
    skip: int = 0,
    limit: int = 100,
):
    ensure_room_access(db, room_id, current_user)
    return summary_repository.get_list(db, room_id=room_id, skip=skip, limit=limit)


def confirm_summary(db: Session, summary_id: int):
    summary = summary_repository.get_by_id(db, summary_id)
    if summary is None:
        raise NotFoundError("summary not found")
    try:
        confirmed = summary_repository.update(db, summary, SummaryUpdate(is_confirmed=True))
        db.commit()
        db.refresh(confirmed)
        return confirmed
    except Exception:
        db.rollback()
        raise


def list_summaries(db: Session, skip: int = 0, limit: int = 100):
    return summary_repository.get_list(db, skip=skip, limit=limit)
