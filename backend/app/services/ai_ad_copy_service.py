import json
import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.user import User
from app.repositories import ai_ad_copy_repository, chat_repository
from app.schemas.ai_ad_copy_schema import AiAdCopyCreate
from app.schemas.chat_schema import ChatCreate
from app.services import hms_client
from app.services.ai_answer_service import (
    hms_verification_output,
    persist_hms_sources,
    persist_hms_verifications,
)
from app.services.room_service import ensure_room_open

logger = logging.getLogger(__name__)


def analyze_and_create(db: Session, current_user: User, data: AiAdCopyCreate):
    """Review text ad copy with HMS and persist the user's history."""
    result = review_document_and_create(
        db,
        current_user,
        input_language=data.input_language,
        text=data.input_text,
        file_name=None,
        file_content=None,
        content_type=None,
        room_id=data.room_id,
    )
    return result["ai_copy"]


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _call_hms_document_review(
    *,
    text: str | None,
    file_name: str | None,
    file_content: bytes | None,
    content_type: str | None,
) -> dict:
    data = {"text": text} if text else None
    files = None
    if file_content is not None and file_name:
        files = {
            "file": (
                file_name,
                file_content,
                content_type or "application/octet-stream",
            )
        }

    return hms_client.post_multipart(
        "/documents/review",
        data=data,
        files=files,
        timeout=hms_client.DOCUMENT_TIMEOUT,
    )


def _collect_review_sources(hms_response: dict) -> list[dict]:
    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add_source(item: Any) -> None:
        if not isinstance(item, dict):
            return
        label = item.get("label") or item.get("matched_label") or item.get("raw")
        source_url = item.get("source_url") or item.get("matched_source_url") or ""
        key = (str(label or ""), str(source_url or ""))
        if not key[0] or key in seen:
            return
        seen.add(key)
        sources.append(
            {
                "label": label,
                "snippet": item.get("snippet") or item.get("segment_text") or item.get("reason"),
                "source_url": source_url,
            }
        )

    for item in hms_response.get("sources") or []:
        add_source(item)
    for finding in hms_response.get("findings") or hms_response.get("issues") or []:
        if isinstance(finding, dict):
            for citation in finding.get("citations") or []:
                add_source(citation)
    citation_check = hms_response.get("citation_check")
    if isinstance(citation_check, dict):
        for item in citation_check.get("output") or []:
            add_source(item)
    return sources


def review_document_and_create(
    db: Session,
    current_user: User,
    *,
    input_language: str,
    text: str | None,
    file_name: str | None,
    file_content: bytes | None,
    content_type: str | None,
    room_id: int | None = None,
):
    """Relay ad review to HMS and persist the review history."""
    if not text and not file_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text or file is required",
        )

    if room_id is not None:
        ensure_room_open(db, room_id, current_user)

    hms_response = _call_hms_document_review(
        text=text,
        file_name=file_name,
        file_content=file_content,
        content_type=content_type,
    )
    original_text = hms_response.get("original_text") or text or file_name or ""
    revised_text = hms_response.get("revised_text") or hms_response.get("corrected_copy")
    findings = hms_response.get("findings") or hms_response.get("issues")
    checklist = hms_response.get("checklist")

    payload = {
        "input_language": input_language,
        "input_text": str(original_text),
        "english_text": None,
        "translated_text": None,
        "risky_expression": _json_text(findings),
        "legal_basis": _json_text(
            {
                "findings": findings,
                "checklist": checklist,
                "checklist_summary": hms_response.get("checklist_summary"),
                "citation_check": hms_response.get("citation_check"),
            }
        ),
        "revision_recomm": revised_text,
        "alternative_text": revised_text,
    }

    try:
        ai_copy = ai_ad_copy_repository.create_from_hms_review(
            db,
            current_user.user_id,
            payload,
        )
        verifications = []
        if room_id is not None:
            user_chat = chat_repository.create(
                db,
                room_id,
                ChatCreate(
                    chatter_id=current_user.user_id,
                    speaker_type="USER",
                    chat_text=text or "PDF 광고 검토",
                    chat_file=file_name,
                ),
            )
            ai_chat = chat_repository.create(
                db,
                room_id,
                ChatCreate(
                    chatter_id=None,
                    speaker_type="AI",
                    chat_text=revised_text or "광고 검토 결과가 저장되었습니다.",
                ),
            )
            verifications = persist_hms_verifications(
                db,
                ai_chat.chat_id,
                current_user.user_id,
                hms_verification_output(hms_response.get("citation_check")),
            )
            evidences = persist_hms_sources(
                db,
                ai_chat.chat_id,
                _collect_review_sources(hms_response),
            )
        else:
            user_chat = None
            ai_chat = None
            evidences = []

        db.commit()
        db.refresh(ai_copy)
        for item in [*evidences, *(verifications or [])]:
            db.refresh(item)
        return {
            "ai_copy": ai_copy,
            "question_chat": user_chat,
            "answer_chat": ai_chat,
            "evidences": evidences,
            "verifications": verifications,
            "room_linked": room_id is not None,
            "hms": hms_response,
        }
    except Exception:
        logger.exception(
            "ad copy review persist failed user_id=%s room_id=%s",
            current_user.user_id,
            room_id,
        )
        db.rollback()
        raise


def list_ai_ad_copies(db: Session, current_user: User, skip: int = 0, limit: int = 100):
    # TODO: admins may use a dedicated endpoint/filter to review all ad-copy analyses.
    user_id = None if current_user.role == "ADMIN" else current_user.user_id
    return ai_ad_copy_repository.get_list(db, user_id=user_id, skip=skip, limit=limit)


def get_ai_ad_copy(db: Session, ai_copy_id: int, current_user: User):
    ai_copy = ai_ad_copy_repository.get_by_id(db, ai_copy_id)
    if ai_copy is None:
        raise NotFoundError("ai ad copy not found")
    if current_user.role != "ADMIN" and ai_copy.user_id != current_user.user_id:
        raise ForbiddenError("ai ad copy access denied")
    return ai_copy


def delete_ai_ad_copy(db: Session, ai_copy_id: int, current_user: User) -> dict:
    ai_copy = get_ai_ad_copy(db, ai_copy_id, current_user)
    try:
        ai_ad_copy_repository.delete(db, ai_copy)
        db.commit()
        return {"ai_copy_id": ai_copy_id, "deleted": True}
    except Exception:
        logger.exception(
            "ai ad copy delete failed ai_copy_id=%s user_id=%s",
            ai_copy_id,
            current_user.user_id,
        )
        db.rollback()
        raise
