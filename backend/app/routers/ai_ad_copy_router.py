from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
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

router = APIRouter(prefix="/ai-ad-copies", tags=["ai-ad-copies"])


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
    file_content = await file.read() if file is not None else None
    result = ai_ad_copy_service.review_document_and_create(
        db,
        current_user,
        input_language=input_language,
        text=text.strip() if isinstance(text, str) and text.strip() else None,
        file_name=file.filename if file is not None else None,
        file_content=file_content,
        content_type=file.content_type if file is not None else None,
        room_id=room_id,
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
