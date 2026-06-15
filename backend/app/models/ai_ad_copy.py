from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.datetime import utc_now


class AiAdCopy(Base):
    __tablename__ = "tb_ai_ad_copy"

    ai_copy_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tb_user.user_id"), nullable=False)
    input_language: Mapped[str | None] = mapped_column(String(10))
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    english_text: Mapped[str | None] = mapped_column(Text)
    translated_text: Mapped[str | None] = mapped_column(Text)
    risky_expression: Mapped[str | None] = mapped_column(Text)
    # 법령명, 조문번호, 근거 요약을 문자열 또는 JSON 문자열 형태로 저장한다.
    legal_basis: Mapped[str | None] = mapped_column(Text)
    revision_recomm: Mapped[str | None] = mapped_column(Text)
    alternative_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    user = relationship("User", back_populates="ai_ad_copies")
