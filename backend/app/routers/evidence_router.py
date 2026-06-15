from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import success_response
from app.schemas.evidence_schema import EvidenceResponse
from app.services import evidence_service

router = APIRouter(prefix="/answers/{ans_id}/evidences", tags=["evidences"])


@router.get("")
def list_answer_evidences(ans_id: int, db: Session = Depends(get_db)):
    evidences = evidence_service.list_answer_evidences(db, ans_id)
    return success_response(
        jsonable_encoder([EvidenceResponse.model_validate(item) for item in evidences])
    )
