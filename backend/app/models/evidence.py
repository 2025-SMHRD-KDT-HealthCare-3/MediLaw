from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Evidence(Base):
    __tablename__ = "tb_evidence"

    evidence_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # ans_id는 별도 AI 응답 테이블이 아니라 AI 답변이 저장된 tb_chat.chat_id를 참조한다.
    ans_id: Mapped[int] = mapped_column(ForeignKey("tb_chat.chat_id"), nullable=False)
    law_name: Mapped[str | None] = mapped_column(String(255))
    article_no: Mapped[str | None] = mapped_column(String(100))
    # 법령 원문 전체를 저장하지 않고 핵심 근거 요약만 저장한다.
    core_basis: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    answer_chat = relationship("Chat", back_populates="evidences")
