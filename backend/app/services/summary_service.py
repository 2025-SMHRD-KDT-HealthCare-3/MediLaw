import json

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.user import User
from app.repositories import chat_repository, summary_repository
from app.schemas.summary_schema import SummaryCreate, SummaryUpdate
from app.services import hms_client
from app.services.room_service import ensure_room_access


def _room_history_for_hms(db: Session, room_id: int) -> list[dict]:
    history = []
    for chat in chat_repository.get_list(db, room_id=room_id, limit=100):
        if not chat.chat_text:
            continue
        if chat.speaker_type == "USER":
            role = "user"
        elif chat.speaker_type in {"AI", "ADMIN"}:
            role = "assistant"
        else:
            continue
        history.append({"role": role, "content": chat.chat_text})
    return history


def _generate_checklist(db: Session, room_id: int) -> dict:
    history = _room_history_for_hms(db, room_id)
    if not history:
        raise BadRequestError("room has no chat history")
    return hms_client.post_json(
        "/chat/checklist",
        {"history": history, "top_k": 6, "max_topics": 5, "lang": "auto"},
        timeout=180,
    )


def create_summary(db: Session, room_id: int, current_user: User, data: SummaryCreate):
    """Generate and store a room checklist using HMS chat history."""
    ensure_room_access(db, room_id, current_user)
    generated = _generate_checklist(db, room_id)
    payload = data.model_copy(
        update={
            "summary": data.summary
            or json.dumps(
                {
                    "checklist_summary": generated.get("checklist_summary"),
                    "search_queries": generated.get("search_queries"),
                    "citation_check": generated.get("citation_check"),
                },
                ensure_ascii=False,
            ),
            "checklist_item": data.checklist_item
            or json.dumps(generated.get("checklist", []), ensure_ascii=False),
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
