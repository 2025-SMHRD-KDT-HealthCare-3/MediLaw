import functools
from typing import Literal

import anyio
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models.user import User
from app.schemas.ai_ad_copy_schema import AiAdCopyCreate, AiAdCopyResponse
from app.schemas.chat_schema import ChatResponse
from app.schemas.evidence_schema import EvidenceResponse
from app.schemas.verification_schema import VerificationResponse
from app.services import ai_ad_copy_service
from app.utils.validators import validate_file_reference

router = APIRouter(prefix="/ai-ad-copies", tags=["ai-ad-copies"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _upload_size(file: UploadFile) -> int | None:
    size = getattr(file, "size", None)
    if isinstance(size, int):
        return size
    if not file.file.seekable():
        return None
    current = file.file.tell()
    file.file.seek(0, 2)
    measured = file.file.tell()
    file.file.seek(current)
    return measured


@router.post("")
def create_ai_ad_copy(
    data: AiAdCopyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ai_copy = ai_ad_copy_service.analyze_and_create(db, current_user, data)
    return success_response(jsonable_encoder(AiAdCopyResponse.model_validate(ai_copy)))


@router.post("/ad-review")
async def review_ad_copy(
    input_language: Literal["ko", "en"] = Form("ko"),
    text: str | None = Form(None),
    room_id: int | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_content = None
    file_name = None
    if file is not None:
        try:
            file_name = validate_file_reference(file.filename or "upload")
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        size = _upload_size(file)
        if size is not None and size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="uploaded file is too large",
            )
        file_content = await file.read()
        if len(file_content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="uploaded file is too large",
            )

    result = await anyio.to_thread.run_sync(
        functools.partial(
            ai_ad_copy_service.review_document_and_create,
            db,
            current_user,
            input_language=input_language,
            text=text.strip() if isinstance(text, str) and text.strip() else None,
            file_name=file_name,
            file_content=file_content,
            content_type=file.content_type if file is not None else None,
            room_id=room_id,
        )
    )
    payload = {
        "ai_copy": AiAdCopyResponse.model_validate(result["ai_copy"]),
        "question_chat": (
            ChatResponse.model_validate(result["question_chat"])
            if result["question_chat"] is not None
            else None
        ),
        "answer_chat": (
            ChatResponse.model_validate(result["answer_chat"])
            if result["answer_chat"] is not None
            else None
        ),
        "evidences": [EvidenceResponse.model_validate(item) for item in result["evidences"]],
        "verifications": [
            VerificationResponse.model_validate(item) for item in result["verifications"]
        ],
        "room_linked": result["room_linked"],
    }
    return success_response(jsonable_encoder(payload))


@router.get("")
def list_ai_ad_copies(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ai_copies = ai_ad_copy_service.list_ai_ad_copies(
        db, current_user, skip=skip, limit=limit
    )
    return success_response(
        jsonable_encoder([AiAdCopyResponse.model_validate(item) for item in ai_copies])
    )


@router.get("/{ai_copy_id}")
def get_ai_ad_copy(
    ai_copy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ai_copy = ai_ad_copy_service.get_ai_ad_copy(db, ai_copy_id, current_user)
    return success_response(jsonable_encoder(AiAdCopyResponse.model_validate(ai_copy)))
