from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.models.user import User
from app.schemas.auth_schema import LoginRequest, SignupRequest
from app.schemas.user_schema import UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup")
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    user = auth_service.signup(db, data)
    return success_response(jsonable_encoder(UserResponse.model_validate(user)))


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    token = auth_service.login(db, data)
    return success_response(jsonable_encoder(token))


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    # TODO: add token blacklist or refresh-token invalidation if adopted.
    return success_response({"message": "logged out"})
