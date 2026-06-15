from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models.user import User
from app.schemas.chat_schema import ChatCreate, ChatResponse
from app.services import chat_service

router = APIRouter(prefix="/rooms/{room_id}/chats", tags=["chats"])


@router.get("")
def list_chats(
    room_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chats = chat_service.list_chats(db, room_id, current_user, skip=skip, limit=limit)
    return success_response(jsonable_encoder([ChatResponse.model_validate(chat) for chat in chats]))


@router.post("")
def create_chat(
    room_id: int,
    data: ChatCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chat = chat_service.create_chat(db, room_id, current_user, data)
    return success_response(jsonable_encoder(ChatResponse.model_validate(chat)))
