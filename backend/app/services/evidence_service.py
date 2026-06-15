from sqlalchemy.orm import Session

from app.repositories import evidence_repository
from app.schemas.evidence_schema import EvidenceCreate


def create_evidence(db: Session, data: EvidenceCreate):
    return evidence_repository.create(db, data)


def list_answer_evidences(db: Session, ans_id: int):
    return evidence_repository.get_list(db, ans_id=ans_id)
