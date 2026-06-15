from sqlalchemy.orm import Session

from app.ai.ad_copy_analyzer import analyze_ad_copy_stub
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.user import User
from app.repositories import ai_ad_copy_repository
from app.schemas.ai_ad_copy_schema import AiAdCopyCreate


def analyze_and_create(db: Session, current_user: User, data: AiAdCopyCreate):
    """Analyze an ad copy with stub logic and persist the user's history."""
    analysis = analyze_ad_copy_stub(data.input_text, data.input_language)
    try:
        ai_copy = ai_ad_copy_repository.create(db, current_user.user_id, data, analysis)
        db.commit()
        db.refresh(ai_copy)
        return ai_copy
    except Exception:
        db.rollback()
        raise


def list_ai_ad_copies(db: Session, current_user: User, skip: int = 0, limit: int = 100):
    # TODO: admins may use a dedicated endpoint/filter to review all ad-copy analyses.
    user_id = None if current_user.role == "ADMIN" else current_user.user_id
    return ai_ad_copy_repository.get_list(db, user_id=user_id, skip=skip, limit=limit)


def get_ai_ad_copy(db: Session, ai_copy_id: int, current_user: User):
    ai_copy = ai_ad_copy_repository.get_by_id(db, ai_copy_id)
    if ai_copy is None:
        raise NotFoundError("ai ad copy not found")
    if current_user.role != "ADMIN" and ai_copy.user_id != current_user.user_id:
        raise ForbiddenError("ai ad copy access denied")
    return ai_copy
