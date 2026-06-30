from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_admin
from app.core.response import success_response
from app.models.user import User
from app.schemas.summary_schema import SummaryCreate, SummaryResponse
from app.services import summary_service

router = APIRouter(tags=["summaries"])


# 체크리스트 생성·저장은 모든 로그인 사용자가 할 수 있다(admin 전용 아님).
# 방 소유자만 자기 방에 생성하도록 service의 ensure_room_access가 막아주므로
# require_admin 대신 get_current_user로 완화해도 안전하다.
@router.post("/rooms/{room_id}/summaries")
def create_summary(
    room_id: int,
    data: SummaryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    summary = summary_service.create_summary(db, room_id, current_user, data)
    return success_response(jsonable_encoder(SummaryResponse.model_validate(summary)))


@router.get("/rooms/{room_id}/summaries")
def list_room_summaries(
    room_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    summaries = summary_service.list_room_summaries(
        db, room_id, current_user, skip=skip, limit=limit
    )
    return success_response(
        jsonable_encoder([SummaryResponse.model_validate(item) for item in summaries])
    )


@router.patch("/summaries/{summary_id}/confirm")
def confirm_summary(
    summary_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    summary = summary_service.confirm_summary(db, summary_id)
    return success_response(jsonable_encoder(SummaryResponse.model_validate(summary)))
