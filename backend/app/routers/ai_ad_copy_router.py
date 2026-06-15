from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models.user import User
from app.schemas.ai_ad_copy_schema import AiAdCopyCreate, AiAdCopyResponse
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
