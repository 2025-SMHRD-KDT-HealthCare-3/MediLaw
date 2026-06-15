from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.response import success_response
from app.schemas.ai_ad_copy_schema import AiAdCopyCreate, AiAdCopyResponse
from app.services import ai_ad_copy_service

router = APIRouter(prefix="/ai-ad-copies", tags=["ai-ad-copies"])


@router.post("")
def create_ai_ad_copy(data: AiAdCopyCreate, db: Session = Depends(get_db)):
    ai_copy = ai_ad_copy_service.analyze_and_create(db, data)
    return success_response(jsonable_encoder(AiAdCopyResponse.model_validate(ai_copy)))


@router.get("")
def list_ai_ad_copies(db: Session = Depends(get_db)):
    ai_copies = ai_ad_copy_service.list_ai_ad_copies(db)
    return success_response(
        jsonable_encoder([AiAdCopyResponse.model_validate(item) for item in ai_copies])
    )


@router.get("/{ai_copy_id}")
def get_ai_ad_copy(ai_copy_id: int, db: Session = Depends(get_db)):
    ai_copy = ai_ad_copy_service.get_ai_ad_copy(db, ai_copy_id)
    if ai_copy is None:
        raise NotFoundError("ai ad copy not found")
    return success_response(jsonable_encoder(AiAdCopyResponse.model_validate(ai_copy)))
