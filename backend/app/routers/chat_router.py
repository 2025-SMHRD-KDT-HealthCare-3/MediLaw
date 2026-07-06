from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models.user import User
from app.repositories import evidence_repository, verification_repository
from app.schemas.chat_schema import ChatCreate, ChatResponse
from app.schemas.evidence_schema import EvidenceResponse
from app.schemas.verification_schema import VerificationResponse
from app.services import chat_service

router = APIRouter(prefix="/rooms/{room_id}/chats", tags=["chats"])


@router.get("")
def list_chats(
    room_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chats = chat_service.list_chats(db, room_id, current_user, skip=skip, limit=limit)
    # AI 답변에는 저장돼 있는 근거(evidences)·검증(verifications)을 함께 실어 준다.
    # 이렇게 해야 프론트가 대화를 다시 불러올 때(새로고침·방 재진입)에도 ai-answer 응답과
    # 동일하게 근거 법령 카드와 신뢰도 점수를 복원할 수 있다(원래는 라이브 응답에만 붙었음).
    items = []
    for chat in chats:
        data = ChatResponse.model_validate(chat).model_dump()
        if chat.speaker_type == "AI":
            evs = evidence_repository.get_list(db, ans_id=chat.chat_id, limit=100)
            vfs = verification_repository.get_list(db, ans_id=chat.chat_id, limit=100)
            data["evidences"] = [EvidenceResponse.model_validate(e).model_dump() for e in evs]
            data["verifications"] = [VerificationResponse.model_validate(v).model_dump() for v in vfs]
        else:
            data["evidences"] = []
            data["verifications"] = []
        items.append(data)
    return success_response(jsonable_encoder(items))


@router.post("")
def create_chat(
    room_id: int,
    data: ChatCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chat = chat_service.create_chat(db, room_id, current_user, data)
    return success_response(jsonable_encoder(ChatResponse.model_validate(chat)))
