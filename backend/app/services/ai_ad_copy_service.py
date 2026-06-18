import json
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.ai.ad_copy_analyzer import analyze_ad_copy_stub
from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.user import User
from app.repositories import ai_ad_copy_repository, chat_repository
from app.schemas.ai_ad_copy_schema import AiAdCopyCreate
from app.schemas.chat_schema import ChatCreate
from app.services.ai_answer_service import persist_hms_verifications
from app.services.room_service import ensure_room_open


def analyze_and_create(db: Session, current_user: User, data: AiAdCopyCreate):
    """Analyze an ad copy with stub logic and persist the user's history."""
    analysis = analyze_ad_copy_stub(data.input_text, data.input_language)
    try:
        ai_copy = ai_ad_copy_repository.create(db, current_user.user_id, data, analysis)
        db.commit()
        db.refresh(ai_copy)
        return ai_copy
    except Exception:
        db.rollback()
        raise


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

    try:
        response = httpx.post(
            f"{settings.HMS_URL.rstrip('/')}/documents/review",
            data=data,
            files=files,
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"HMS document review request failed: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="HMS document review response was not valid JSON",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="HMS document review response was not an object",
        )
    return payload


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
            ensure_room_open(db, room_id, current_user)
            user_chat = chat_repository.create(
                db,
                room_id,
                ChatCreate(
                    chatter_id=current_user.user_id,
                    speaker_type="USER",
                    chat_text=text or "PDF 광고검토",
                    chat_file=file_name,
                ),
            )
            ai_chat = chat_repository.create(
                db,
                room_id,
                ChatCreate(
                    chatter_id=None,
                    speaker_type="AI",
                    chat_text=revised_text or "광고검토 결과가 저장되었습니다.",
                ),
            )
            verifications = persist_hms_verifications(
                db,
                ai_chat.chat_id,
                current_user.user_id,
                hms_response.get("citation_check"),
            )
        else:
            user_chat = None
            ai_chat = None

        db.commit()
        db.refresh(ai_copy)
        for item in [*(verifications or [])]:
            db.refresh(item)
        return {
            "ai_copy": ai_copy,
            "question_chat": user_chat,
            "answer_chat": ai_chat,
            "verifications": verifications,
            "hms": hms_response,
        }
    except Exception:
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
