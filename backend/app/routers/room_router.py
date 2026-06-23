from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models.user import User
from app.schemas.room_schema import RoomCreate, RoomResponse, RoomUpdate
from app.services import room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("")
def create_room(
    data: RoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room = room_service.create_room(db, current_user.user_id, data)
    return success_response(jsonable_encoder(RoomResponse.model_validate(room)))


@router.get("")
def list_rooms(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rooms = room_service.list_rooms(db, current_user, skip=skip, limit=limit)
    return success_response(jsonable_encoder([RoomResponse.model_validate(room) for room in rooms]))


@router.get("/{room_id}")
def get_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room = room_service.ensure_room_access(db, room_id, current_user)
    return success_response(jsonable_encoder(RoomResponse.model_validate(room)))


@router.post("/{room_id}/leave")
def leave_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room = room_service.leave_room(db, room_id, current_user)
    return success_response(
        jsonable_encoder(RoomResponse.model_validate(room)),
        message="room left",
    )


@router.post("/{room_id}/close")
def close_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room = room_service.close_room(db, room_id, current_user)
    return success_response(
        jsonable_encoder(RoomResponse.model_validate(room)),
        message="room closed",
    )


@router.delete("/{room_id}")
def delete_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = room_service.delete_room(db, room_id, current_user)
    return success_response(result, message="room deleted")


@router.patch("/{room_id}")
def update_room(
    room_id: int,
    data: RoomUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room = room_service.update_room(db, room_id, data, current_user)
    return success_response(jsonable_encoder(RoomResponse.model_validate(room)))
