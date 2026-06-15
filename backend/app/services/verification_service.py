from sqlalchemy.orm import Session

from app.ai.citation_verifier import verify_citation_stub
from app.repositories import verification_repository
from app.schemas.verification_schema import VerificationCreate


def create_verification(db: Session, data: VerificationCreate):
    return verification_repository.create(db, data)


def list_answer_verifications(db: Session, ans_id: int):
    return verification_repository.get_list(db, ans_id=ans_id)


def verify_answer_stub(db: Session, ans_id: int, user_id: int):
    result = verify_citation_stub({"law_name": "의료법", "article_no": "제56조"})
    data = VerificationCreate(ans_id=ans_id, user_id=user_id, **result)
    return verification_repository.create(db, data)


def list_verifications(db: Session):
    return verification_repository.get_list(db)
