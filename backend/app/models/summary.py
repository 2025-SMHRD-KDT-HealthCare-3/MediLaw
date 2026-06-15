from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Summary(Base):
    __tablename__ = "tb_summary"

    summary_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("tb_room.room_id"), nullable=False)
    admin_id: Mapped[int] = mapped_column(ForeignKey("tb_user.user_id"), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    # checklist_item은 여러 체크리스트 항목을 JSON 문자열 형태로 저장할 수 있다.
    checklist_item: Mapped[str | None] = mapped_column(Text)
    # summary_file은 파일 원본이 아니라 파일명 또는 파일 참조 경로만 저장한다.
    summary_file: Mapped[str | None] = mapped_column(String(255))
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    room = relationship("Room", back_populates="summaries")
    admin = relationship("User", back_populates="summaries")
