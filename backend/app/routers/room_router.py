from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user_id
from app.core.response import success_response
from app.schemas.room_schema import RoomCreate, RoomResponse, RoomUpdate
from app.services import room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("")
def create_room(
    data: RoomCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    room = room_service.create_room(db, current_user_id, data)
    return success_response(jsonable_encoder(RoomResponse.model_validate(room)))


@router.get("")
def list_rooms(db: Session = Depends(get_db)):
    rooms = room_service.list_rooms(db)
    return success_response(jsonable_encoder([RoomResponse.model_validate(room) for room in rooms]))


@router.get("/{room_id}")
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = room_service.get_room(db, room_id)
    return success_response(jsonable_encoder(RoomResponse.model_validate(room)))


@router.patch("/{room_id}")
def update_room(room_id: int, data: RoomUpdate, db: Session = Depends(get_db)):
    room = room_service.update_room(db, room_id, data)
    return success_response(jsonable_encoder(RoomResponse.model_validate(room)))
