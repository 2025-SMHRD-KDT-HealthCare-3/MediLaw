from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import Chat
from app.schemas.chat_schema import ChatCreate, ChatUpdate


def create(db: Session, room_id: int, data: ChatCreate) -> Chat:
    chat = Chat(**data.model_dump(), room_id=room_id)
    db.add(chat)
    db.flush()
    db.refresh(chat)
    return chat


def get_by_id(db: Session, chat_id: int) -> Chat | None:
    return db.get(Chat, chat_id)


def get_list(db: Session, room_id: int | None = None, skip: int = 0, limit: int = 100) -> list[Chat]:
    # TODO: add cursor pagination for chat history.
    stmt = select(Chat).order_by(Chat.chatted_at.asc())
    if room_id is not None:
        stmt = stmt.where(Chat.room_id == room_id)
    return list(db.scalars(stmt.offset(skip).limit(limit)).all())


def get_recent_for_room(db: Session, room_id: int, limit: int = 10) -> list[Chat]:
    stmt = (
        select(Chat)
        .where(Chat.room_id == room_id)
        .order_by(Chat.chatted_at.desc(), Chat.chat_id.desc())
        .limit(limit)
    )
    return list(reversed(list(db.scalars(stmt).all())))


def update(db: Session, chat: Chat, data: ChatUpdate) -> Chat:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(chat, key, value)
    db.flush()
    db.refresh(chat)
    return chat
