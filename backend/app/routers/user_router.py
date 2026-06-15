from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user_id
from app.core.response import success_response
from app.schemas.user_schema import UserResponse, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def get_me(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user = user_service.get_me(db, current_user_id)
    return success_response(jsonable_encoder(UserResponse.model_validate(user)))


@router.patch("/me")
def update_me(
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user = user_service.update_me(db, current_user_id, data)
    return success_response(jsonable_encoder(UserResponse.model_validate(user)))
