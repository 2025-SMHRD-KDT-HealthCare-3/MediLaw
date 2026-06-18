from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models.user import User
from app.schemas.verification_schema import VerificationResponse
from app.services import verification_service

router = APIRouter(prefix="/answers/{ans_id}", tags=["verifications"])


@router.get("/verifications")
def list_answer_verifications(
    ans_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    verifications = verification_service.list_answer_verifications(db, ans_id, current_user)
    return success_response(
        jsonable_encoder([VerificationResponse.model_validate(item) for item in verifications])
    )


@router.post("/verify")
def verify_answer(
    ans_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    verifications = verification_service.verify_answer(db, ans_id, current_user)
    return success_response(
        jsonable_encoder([VerificationResponse.model_validate(item) for item in verifications])
    )
