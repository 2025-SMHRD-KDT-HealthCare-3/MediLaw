from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import success_response
from app.schemas.chat_schema import ChatCreate, ChatResponse
from app.services import chat_service

router = APIRouter(prefix="/rooms/{room_id}/chats", tags=["chats"])


@router.get("")
def list_chats(room_id: int, db: Session = Depends(get_db)):
    chats = chat_service.list_chats(db, room_id)
    return success_response(jsonable_encoder([ChatResponse.model_validate(chat) for chat in chats]))


@router.post("")
def create_chat(room_id: int, data: ChatCreate, db: Session = Depends(get_db)):
    chat = chat_service.create_chat(db, room_id, data)
    return success_response(jsonable_encoder(ChatResponse.model_validate(chat)))
