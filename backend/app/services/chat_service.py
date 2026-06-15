from sqlalchemy.orm import Session

from app.repositories import chat_repository
from app.schemas.chat_schema import ChatCreate


def create_chat(db: Session, room_id: int, data: ChatCreate):
    return chat_repository.create(db, room_id, data)


def list_chats(db: Session, room_id: int):
    return chat_repository.get_list(db, room_id=room_id)
