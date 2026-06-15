from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.user import User
from app.repositories import chat_repository
from app.repositories import evidence_repository
from app.schemas.evidence_schema import EvidenceCreate
from app.services.room_service import ensure_room_access


def create_evidence(db: Session, data: EvidenceCreate):
    try:
        evidence = evidence_repository.create(db, data)
        db.commit()
        db.refresh(evidence)
        return evidence
    except Exception:
        db.rollback()
        raise


def list_answer_evidences(db: Session, ans_id: int, current_user: User):
    answer_chat = chat_repository.get_by_id(db, ans_id)
    if answer_chat is None:
        raise NotFoundError("answer chat not found")
    if answer_chat.speaker_type != "AI":
        raise BadRequestError("ans_id must reference an AI chat")
    ensure_room_access(db, answer_chat.room_id, current_user)
    return evidence_repository.get_list(db, ans_id=ans_id)
