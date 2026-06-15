from sqlalchemy.orm import Session

from app.ai.summary_generator import generate_summary_stub
from app.repositories import chat_repository, summary_repository
from app.schemas.summary_schema import SummaryCreate, SummaryUpdate


def create_summary(db: Session, room_id: int, data: SummaryCreate):
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
    return summary_repository.create(db, room_id, payload)


def list_room_summaries(db: Session, room_id: int):
    return summary_repository.get_list(db, room_id=room_id)


def confirm_summary(db: Session, summary_id: int):
    summary = summary_repository.get_by_id(db, summary_id)
    if summary is None:
        return None
    return summary_repository.update(db, summary, SummaryUpdate(is_confirmed=True))


def list_summaries(db: Session):
    return summary_repository.get_list(db)
