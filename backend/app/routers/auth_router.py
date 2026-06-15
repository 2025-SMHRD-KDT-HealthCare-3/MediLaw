from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import success_response
from app.schemas.auth_schema import LoginRequest, SignupRequest
from app.schemas.user_schema import UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup")
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    user = auth_service.signup(db, data)
    return success_response(jsonable_encoder(UserResponse.model_validate(user)))


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    token = auth_service.login(db, data)
    return success_response(jsonable_encoder(token))


@router.post("/logout")
def logout():
    # TODO: add token blacklist or refresh-token invalidation if adopted.
    return success_response({"message": "logged out"})
