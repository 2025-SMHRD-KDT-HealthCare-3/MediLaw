from sqlalchemy.orm import Session

from app.ai.ad_copy_analyzer import analyze_ad_copy_stub
from app.repositories import ai_ad_copy_repository
from app.schemas.ai_ad_copy_schema import AiAdCopyCreate


def analyze_and_create(db: Session, data: AiAdCopyCreate):
    analysis = analyze_ad_copy_stub(data.input_text, data.input_language)
    return ai_ad_copy_repository.create(db, data, analysis)


def list_ai_ad_copies(db: Session, user_id: int | None = None):
    return ai_ad_copy_repository.get_list(db, user_id=user_id)


def get_ai_ad_copy(db: Session, ai_copy_id: int):
    return ai_ad_copy_repository.get_by_id(db, ai_copy_id)
