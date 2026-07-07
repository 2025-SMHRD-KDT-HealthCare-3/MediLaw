import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.chat import Chat
from app.models.user import User
from app.repositories import chat_repository, evidence_repository, verification_repository
from app.schemas.chat_schema import ChatCreate
from app.schemas.evidence_schema import EvidenceCreate
from app.schemas.verification_schema import VerificationCreate
from app.services import hms_client
from app.services.hms_mapping import (
    clamp_score,
    clean_text,
    hms_bool,
    map_verification_status,
    parse_law_label,
    verification_reason,
)
from app.services.room_service import ensure_room_open

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10
AI_FAILURE_MESSAGE = "\ud604\uc7ac AI \ub2f5\ubcc0 \uc0dd\uc131\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4. \uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574 \uc8fc\uc138\uc694."


def _chat_to_hms_turn(chat: Chat) -> dict | None:
    if not chat.chat_text:
        return None
    if chat.speaker_type == "USER":
        role = "user"
    elif chat.speaker_type in {"AI", "ADMIN"}:
        role = "assistant"
    else:
        return None
    return {"role": role, "content": chat.chat_text}


def build_hms_history(db: Session, room_id: int, *, exclude_chat_id: int | None = None) -> list[dict]:
    history = []
    for chat in chat_repository.get_recent_for_room(db, room_id, limit=HISTORY_LIMIT + 1):
        if exclude_chat_id is not None and chat.chat_id == exclude_chat_id:
            continue
        turn = _chat_to_hms_turn(chat)
        if turn:
            history.append(turn)
    return history[-HISTORY_LIMIT:]


def _call_hms_chat(question: str, history: list[dict], lang: str = "ko") -> dict:
    # 영어 입력이면 HMS 영어 전용 챗봇 엔드포인트로(영문 답변 + 공식 영문조문).
    is_en = (lang or "").lower() == "en"
    path = "/chat/en" if is_en else "/chat"
    data = hms_client.post_json(
        path,
        {"question": question, "history": history, "top_k": 8, "lang": "en" if is_en else "ko"},
        timeout=hms_client.DEFAULT_TIMEOUT,
    )
    if not isinstance(data, dict) or not data.get("answer"):
        raise HTTPException(
            status_code=502,
            detail="HMS chat response did not include answer",
        )
    return data


def persist_hms_sources(db: Session, ans_id: int, sources: list[dict]) -> list:
    evidences = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        law_name, article_no = parse_law_label(source.get("label"))
        evidences.append(
            evidence_repository.create(
                db,
                EvidenceCreate(
                    ans_id=ans_id,
                    law_name=law_name,
                    article_no=article_no,
                    core_basis=clean_text(source.get("snippet")),
                    source_url=clean_text(source.get("source_url")),
                ),
            )
        )
    return evidences


def persist_hms_verifications(
    db: Session,
    ans_id: int,
    user_id: int,
    output_items: list[dict],
) -> list:
    verifications = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        law_name, article_no = parse_law_label(item.get("matched_label") or item.get("raw"))
        verifications.append(
            verification_repository.create(
                db,
                VerificationCreate(
                    ans_id=ans_id,
                    user_id=user_id,
                    law_name=law_name,
                    article_no=article_no,
                    article_exists=hms_bool(item.get("exists")),
                    content_matches=hms_bool(item.get("clause_accurate")),
                    effective_date_valid=hms_bool(item.get("valid_as_of")),
                    verification_status=map_verification_status(item),
                    confidence_score=clamp_score(item.get("trust_score")),
                    verification_reason=verification_reason(item),
                ),
            )
        )
    return verifications

def hms_verification_output(citation_check: dict | None) -> list[dict]:
    if not isinstance(citation_check, dict):
        return []
    output = citation_check.get("output", [])
    if isinstance(output, list) and output:
        return output

    summary = citation_check.get("summary")
    if not isinstance(summary, dict):
        return []

    score = summary.get("avg_score")
    if score is None:
        score = summary.get("min_score")
    if score is None:
        return []

    total = int(summary.get("total") or 0)
    failed = int(summary.get("failed") or 0)
    verified = int(summary.get("verified") or 0)
    if failed > 0:
        status = "ERROR"
    elif total > 0 and verified == total:
        status = "CONFIRMED"
    else:
        status = "WARNING"

    return [
        {
            "raw": "citation_check.summary",
            "exists": total > 0,
            "clause_accurate": None,
            "valid_as_of": None,
            "verified": status == "CONFIRMED",
            "trust_score": score,
            "status": status,
            "note": "Citation summary score from HMS",
        }
    ]


def create_ai_answer(
    db: Session, room_id: int, current_user: User, question: str, lang: str = "ko"
) -> dict:
    """Persist the user question first, then call HMS and persist the answer.

    lang: 'ko'(기본)면 한국어 챗봇(/chat), 'en'이면 영어 전용 챗봇(/chat/en) 호출.
    """
    ensure_room_open(db, room_id, current_user)
    try:
        user_chat = chat_repository.create(
            db,
            room_id,
            ChatCreate(chatter_id=current_user.user_id, speaker_type="USER", chat_text=question),
        )
        db.commit()
        db.refresh(user_chat)
    except Exception:
        logger.exception("AI question persist failed room_id=%s user_id=%s", room_id, current_user.user_id)
        db.rollback()
        raise

    history = build_hms_history(db, room_id, exclude_chat_id=user_chat.chat_id)
    try:
        hms_response = _call_hms_chat(question, history, lang)
    except HTTPException:
        try:
            failure_chat = chat_repository.create(
                db,
                room_id,
                ChatCreate(chatter_id=None, speaker_type="AI", chat_text=AI_FAILURE_MESSAGE),
            )
            db.commit()
            db.refresh(failure_chat)
        except Exception:
            logger.exception("AI failure message persist failed room_id=%s", room_id)
            db.rollback()
        raise

    try:
        sources = hms_response.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        answer_text = hms_response["answer"]
        ai_chat = chat_repository.create(
            db,
            room_id,
            ChatCreate(chatter_id=None, speaker_type="AI", chat_text=answer_text),
        )

        evidences = persist_hms_sources(db, ai_chat.chat_id, sources)
        verifications = persist_hms_verifications(
            db,
            ai_chat.chat_id,
            current_user.user_id,
            hms_verification_output(hms_response.get("citation_check")),
        )

        db.commit()
        for item in [user_chat, ai_chat, *evidences, *verifications]:
            db.refresh(item)
        return {
            "question_chat": user_chat,
            "answer_chat": ai_chat,
            "evidences": evidences,
            "verifications": verifications,
            "hms": hms_response,
        }
    except Exception:
        logger.exception("AI answer persist failed room_id=%s user_id=%s", room_id, current_user.user_id)
        db.rollback()
        raise
