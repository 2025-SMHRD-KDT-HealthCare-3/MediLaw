from sqlalchemy.orm import Session

from app.ai.citation_verifier import verify_citation_stub
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.user import User
from app.repositories import chat_repository, verification_repository
from app.schemas.verification_schema import VerificationCreate
from app.services.room_service import ensure_room_access


def create_verification(db: Session, data: VerificationCreate):
    try:
        verification = verification_repository.create(db, data)
        db.commit()
        db.refresh(verification)
        return verification
    except Exception:
        db.rollback()
        raise


def _get_ai_answer_or_raise(db: Session, ans_id: int):
    answer_chat = chat_repository.get_by_id(db, ans_id)
    if answer_chat is None:
        raise NotFoundError("answer chat not found")
    if answer_chat.speaker_type != "AI":
        raise BadRequestError("ans_id must reference an AI chat")
    return answer_chat


def list_answer_verifications(db: Session, ans_id: int, current_user: User):
    answer_chat = _get_ai_answer_or_raise(db, ans_id)
    ensure_room_access(db, answer_chat.room_id, current_user)
    return verification_repository.get_list(db, ans_id=ans_id)


def verify_answer_stub(db: Session, ans_id: int, current_user: User):
    answer_chat = _get_ai_answer_or_raise(db, ans_id)
    ensure_room_access(db, answer_chat.room_id, current_user)
    result = verify_citation_stub(
        {"law_name": "의료법", "article_no": "제56조", "answer_text": answer_chat.chat_text}
    )
    data = VerificationCreate(ans_id=ans_id, user_id=current_user.user_id, **result)
    try:
        verification = verification_repository.create(db, data)
        db.commit()
        db.refresh(verification)
        return verification
    except Exception:
        db.rollback()
        raise


def list_verifications(db: Session, skip: int = 0, limit: int = 100):
    return verification_repository.get_list(db, skip=skip, limit=limit)
