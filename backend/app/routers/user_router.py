from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models.user import User
from app.schemas.user_schema import UserResponse, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def get_me(
    current_user: User = Depends(get_current_user),
):
    return success_response(jsonable_encoder(UserResponse.model_validate(current_user)))


@router.patch("/me")
def update_me(
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = user_service.update_me(db, current_user.user_id, data)
    return success_response(jsonable_encoder(UserResponse.model_validate(user)))
