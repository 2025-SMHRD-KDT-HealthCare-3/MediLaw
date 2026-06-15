from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user_id
from app.core.response import success_response
from app.schemas.verification_schema import VerificationResponse
from app.services import verification_service

router = APIRouter(prefix="/answers/{ans_id}", tags=["verifications"])


class VerifyAnswerRequest(BaseModel):
    user_id: int | None = None


@router.get("/verifications")
def list_answer_verifications(ans_id: int, db: Session = Depends(get_db)):
    verifications = verification_service.list_answer_verifications(db, ans_id)
    return success_response(
        jsonable_encoder([VerificationResponse.model_validate(item) for item in verifications])
    )


@router.post("/verify")
def verify_answer(
    ans_id: int,
    data: VerifyAnswerRequest | None = None,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user_id = data.user_id if data and data.user_id else current_user_id
    verification = verification_service.verify_answer_stub(db, ans_id, user_id)
    return success_response(jsonable_encoder(VerificationResponse.model_validate(verification)))
