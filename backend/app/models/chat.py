from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Chat(Base):
    __tablename__ = "tb_chat"
    __table_args__ = (
        CheckConstraint("speaker_type in ('USER', 'AI', 'ADMIN')", name="ck_chat_speaker_type"),
    )

    chat_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("tb_room.room_id"), nullable=False)
    # AI 답변은 chatter_id를 NULL로 두거나 시스템 사용자 ID를 사용할 수 있다.
    chatter_id: Mapped[int | None] = mapped_column(ForeignKey("tb_user.user_id"), nullable=True)
    # speaker_type은 USER, AI, ADMIN 발화자 구분에 사용한다.
    speaker_type: Mapped[str] = mapped_column(String(20), nullable=False)
    chat_text: Mapped[str | None] = mapped_column(Text)
    chat_emoticon: Mapped[str | None] = mapped_column(String(255))
    # chat_file은 파일 원본이 아니라 파일명 또는 파일 참조 경로만 저장한다.
    chat_file: Mapped[str | None] = mapped_column(String(255))
    chatted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    room = relationship("Room", back_populates="chats")
    chatter = relationship("User", back_populates="chats")
    evidences = relationship("Evidence", back_populates="answer_chat")
    verifications = relationship("Verification", back_populates="answer_chat")
