from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, DECIMAL, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.datetime import utc_now


class Verification(Base):
    __tablename__ = "tb_verification"
    __table_args__ = (
        CheckConstraint(
            "verification_status in ('CONFIRMED', 'WARNING', 'ERROR')",
            name="ck_verification_status",
        ),
        CheckConstraint(
            "confidence_score >= 0 and confidence_score <= 100",
            name="ck_verification_confidence_score",
        ),
    )

    verification_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # ans_id는 별도 AI 응답 테이블이 아니라 AI 답변이 저장된 tb_chat.chat_id를 참조한다.
    ans_id: Mapped[int] = mapped_column(ForeignKey("tb_chat.chat_id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("tb_user.user_id"), nullable=False)
    law_name: Mapped[str | None] = mapped_column(String(255))
    article_no: Mapped[str | None] = mapped_column(String(100))
    article_exists: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content_matches: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    effective_date_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_score: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2))
    verification_reason: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    answer_chat = relationship("Chat", back_populates="verifications")
    user = relationship("User", back_populates="verifications")
