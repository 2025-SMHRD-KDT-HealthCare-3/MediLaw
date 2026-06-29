from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models.user import User
from app.schemas.chat_schema import ChatResponse
from app.schemas.evidence_schema import EvidenceResponse
from app.schemas.verification_schema import VerificationResponse
from app.services import ai_answer_service

router = APIRouter(prefix="/rooms/{room_id}", tags=["ai-answer"])


class AiAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    lang: str = Field(default="ko", pattern="^(ko|en)$")  # 'en'이면 영어 전용 챗봇(/chat/en)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


@router.post("/ai-answer")
def create_ai_answer(
    room_id: int,
    data: AiAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ai_answer_service.create_ai_answer(db, room_id, current_user, data.question, data.lang)
    payload = {
        "question_chat": ChatResponse.model_validate(result["question_chat"]),
        "answer_chat": ChatResponse.model_validate(result["answer_chat"]),
        "evidences": [EvidenceResponse.model_validate(item) for item in result["evidences"]],
        "verifications": [
            VerificationResponse.model_validate(item) for item in result["verifications"]
        ],
    }
    return success_response(jsonable_encoder(payload))
