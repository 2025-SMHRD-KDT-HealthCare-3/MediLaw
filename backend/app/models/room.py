from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.datetime import utc_now


class Room(Base):
    __tablename__ = "tb_room"
    __table_args__ = (
        CheckConstraint("room_status in ('ACTIVE', 'CLOSED')", name="ck_room_status"),
    )

    room_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tb_user.user_id"), nullable=False)
    room_title: Mapped[str] = mapped_column(String(255), nullable=False)
    room_desc: Mapped[str | None] = mapped_column(Text)
    # ERD 명칭을 유지한다. 방 인원수 또는 제한 인원 수로 사용되는 값이다.
    room_limit: Mapped[int | None] = mapped_column()
    room_status: Mapped[str] = mapped_column(String(10), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    user = relationship("User", back_populates="rooms")
    chats = relationship("Chat", back_populates="room")
    summaries = relationship("Summary", back_populates="room")
