from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user_id
from app.core.response import success_response
from app.schemas.chat_schema import ChatResponse
from app.schemas.evidence_schema import EvidenceResponse
from app.schemas.verification_schema import VerificationResponse
from app.services import ai_answer_service

router = APIRouter(prefix="/rooms/{room_id}", tags=["ai-answer"])


class AiAnswerRequest(BaseModel):
    question: str


@router.post("/ai-answer")
def create_ai_answer(
    room_id: int,
    data: AiAnswerRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    result = ai_answer_service.create_ai_answer(db, room_id, current_user_id, data.question)
    payload = {
        "question_chat": ChatResponse.model_validate(result["question_chat"]),
        "answer_chat": ChatResponse.model_validate(result["answer_chat"]),
        "evidences": [EvidenceResponse.model_validate(item) for item in result["evidences"]],
        "verifications": [
            VerificationResponse.model_validate(item) for item in result["verifications"]
        ],
    }
    return success_response(jsonable_encoder(payload))
