from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin
from app.core.response import success_response
from app.models.user import User
from app.schemas.summary_schema import SummaryResponse
from app.schemas.user_schema import UserResponse
from app.schemas.verification_schema import VerificationResponse
from app.services import summary_service, user_service, verification_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    users = user_service.list_users(db, skip=skip, limit=limit)
    return success_response(jsonable_encoder([UserResponse.model_validate(user) for user in users]))


@router.get("/verifications")
def list_verifications(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    verifications = verification_service.list_verifications(db, skip=skip, limit=limit)
    return success_response(
        jsonable_encoder([VerificationResponse.model_validate(item) for item in verifications])
    )


@router.get("/summaries")
def list_summaries(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    summaries = summary_service.list_summaries(db, skip=skip, limit=limit)
    return success_response(
        jsonable_encoder([SummaryResponse.model_validate(item) for item in summaries])
    )
