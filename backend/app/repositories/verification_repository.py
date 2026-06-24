from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.verification import Verification
from app.schemas.verification_schema import VerificationCreate, VerificationUpdate


def create(db: Session, data: VerificationCreate) -> Verification:
    verification = Verification(**data.model_dump())
    db.add(verification)
    db.flush()
    db.refresh(verification)
    return verification


def get_by_id(db: Session, verification_id: int) -> Verification | None:
    return db.get(Verification, verification_id)


def get_list(
    db: Session,
    ans_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Verification]:
    # TODO: add admin filters by status and confidence range.
    stmt = select(Verification).order_by(Verification.verified_at.desc())
    if ans_id is not None:
        stmt = stmt.where(Verification.ans_id == ans_id)
    return list(db.scalars(stmt.offset(skip).limit(limit)).all())


def delete_for_answer(db: Session, ans_id: int) -> None:
    db.execute(delete(Verification).where(Verification.ans_id == ans_id))
    db.flush()


def update(db: Session, verification: Verification, data: VerificationUpdate) -> Verification:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(verification, key, value)
    db.flush()
    db.refresh(verification)
    return verification
