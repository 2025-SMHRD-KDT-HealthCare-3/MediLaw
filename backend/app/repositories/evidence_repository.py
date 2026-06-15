from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.schemas.evidence_schema import EvidenceCreate, EvidenceUpdate


def create(db: Session, data: EvidenceCreate) -> Evidence:
    evidence = Evidence(**data.model_dump())
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def get_by_id(db: Session, evidence_id: int) -> Evidence | None:
    return db.get(Evidence, evidence_id)


def get_list(db: Session, ans_id: int | None = None, skip: int = 0, limit: int = 100) -> list[Evidence]:
    # TODO: add source filtering if multiple law providers are introduced.
    stmt = select(Evidence)
    if ans_id is not None:
        stmt = stmt.where(Evidence.ans_id == ans_id)
    return list(db.scalars(stmt.offset(skip).limit(limit)).all())


def update(db: Session, evidence: Evidence, data: EvidenceUpdate) -> Evidence:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(evidence, key, value)
    db.commit()
    db.refresh(evidence)
    return evidence
