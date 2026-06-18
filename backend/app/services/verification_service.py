import re

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.user import User
from app.repositories import chat_repository, evidence_repository, verification_repository
from app.schemas.verification_schema import VerificationCreate
from app.services import hms_client
from app.services.ai_answer_service import persist_hms_verifications
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


def _normalize_article_no(article_no: str | None) -> str | None:
    if not article_no:
        return None
    match = re.search(r"\d+(?:-\d+)?", article_no)
    return match.group(0) if match else article_no


def _build_hms_citations(db: Session, ans_id: int) -> list[dict]:
    citations = []
    for evidence in evidence_repository.get_list(db, ans_id=ans_id):
        if evidence.law_name and evidence.article_no:
            citations.append(
                {
                    "law_name": evidence.law_name,
                    "article_no": _normalize_article_no(evidence.article_no),
                }
            )
        elif evidence.law_name:
            citations.append({"raw": evidence.law_name})
    return citations


def _call_hms_verify(answer_text: str | None, citations: list[dict]) -> dict:
    payload = {"citations": citations} if citations else {"text": answer_text or ""}
    return hms_client.post_json("/v1/verify", payload, timeout=120)


def verify_answer(db: Session, ans_id: int, current_user: User):
    answer_chat = _get_ai_answer_or_raise(db, ans_id)
    ensure_room_access(db, answer_chat.room_id, current_user)
    hms_response = _call_hms_verify(
        answer_chat.chat_text,
        _build_hms_citations(db, ans_id),
    )
    try:
        verifications = persist_hms_verifications(
            db,
            ans_id,
            current_user.user_id,
            hms_response,
        )
        db.commit()
        for verification in verifications:
            db.refresh(verification)
        return verifications
    except Exception:
        db.rollback()
        raise


def list_verifications(db: Session, skip: int = 0, limit: int = 100):
    return verification_repository.get_list(db, skip=skip, limit=limit)
