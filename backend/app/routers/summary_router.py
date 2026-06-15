from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.response import success_response
from app.schemas.summary_schema import SummaryCreate, SummaryResponse
from app.services import summary_service

router = APIRouter(tags=["summaries"])


@router.post("/rooms/{room_id}/summaries")
def create_summary(room_id: int, data: SummaryCreate, db: Session = Depends(get_db)):
    summary = summary_service.create_summary(db, room_id, data)
    return success_response(jsonable_encoder(SummaryResponse.model_validate(summary)))


@router.get("/rooms/{room_id}/summaries")
def list_room_summaries(room_id: int, db: Session = Depends(get_db)):
    summaries = summary_service.list_room_summaries(db, room_id)
    return success_response(
        jsonable_encoder([SummaryResponse.model_validate(item) for item in summaries])
    )


@router.patch("/summaries/{summary_id}/confirm")
def confirm_summary(summary_id: int, db: Session = Depends(get_db)):
    summary = summary_service.confirm_summary(db, summary_id)
    if summary is None:
        raise NotFoundError("summary not found")
    return success_response(jsonable_encoder(SummaryResponse.model_validate(summary)))
