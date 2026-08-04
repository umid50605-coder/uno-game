from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import get_current_user_id
from core.database import get_db
from models.schemas import CreateRoomRequest, JoinRoomRequest, LeaveRoomResponse, ReadyRequest, RoomOut
from services import abuse_service, room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])


def _ensure_not_locked(db: Session, telegram_id: int) -> None:
    lock = abuse_service.check_lock(db, telegram_id)
    if lock["locked"]:
        if lock.get("blacklisted"):
            detail = "Siz qora ro'yxatga tushirilgansiz va o'yin o'ynay olmaysiz."
        else:
            detail = f"Siz vaqtincha bloklangansiz. {lock['until'].isoformat()} gacha kuting."
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.post("", response_model=RoomOut)
async def create_room(
    payload: CreateRoomRequest,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    _ensure_not_locked(db, telegram_id)
    return room_service.create_room(db, telegram_id, payload.is_public, payload.join_code)


@router.get("", response_model=list[RoomOut])
async def list_rooms(
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[RoomOut]:
    return room_service.list_open_rooms(db)


@router.get("/search", response_model=list[RoomOut])
async def search_rooms(
    code: str,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[RoomOut]:
    """Kod orqali xona qidirish (security/public)."""
    return room_service.search_rooms_by_code(db, code)


@router.get("/random", response_model=RoomOut)
async def random_room(
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    """Tasodifiy public xona tanlash."""
    return room_service.get_random_public_room(db)


@router.get("/{room_id}", response_model=RoomOut)
async def get_room(
    room_id: int,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    return room_service.get_room(db, room_id, telegram_id)


@router.post("/{room_id}/join", response_model=RoomOut)
async def join_room(
    room_id: int,
    payload: JoinRoomRequest = JoinRoomRequest(),
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    _ensure_not_locked(db, telegram_id)
    return room_service.join_room(db, room_id, telegram_id, payload.join_code)


@router.post("/{room_id}/ready", response_model=RoomOut)
async def ready(
    room_id: int,
    payload: ReadyRequest = ReadyRequest(),
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    return room_service.set_ready(db, room_id, telegram_id, payload.ready)


@router.post("/{room_id}/wait", response_model=RoomOut)
async def extend_wait(
    room_id: int,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    return room_service.extend_wait(db, room_id, telegram_id)


@router.post("/{room_id}/leave", response_model=LeaveRoomResponse)
async def leave_room(
    room_id: int,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> LeaveRoomResponse:
    return room_service.leave_room(db, room_id, telegram_id)