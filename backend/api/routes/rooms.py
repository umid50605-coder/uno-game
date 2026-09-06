"""
backend/api/routes/rooms.py 
"""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import get_current_user_id
from core.database import get_db
from models.schemas import CreateRoomRequest, JoinRoomRequest, LeaveRoomResponse, ReadyRequest, RoomOut
from services import room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])


# ==========================================================
# TUZATILDI (HIGH — join_code brute force): xona kodi bilan qo'shilishga
# urinishlarni cheklaydi. Xotirada saqlanadi — WEB_CONCURRENCY=1 bo'lgani
# uchun bu yetarli; bir nechta worker/instance ishlatilsa, umumiy do'kon
# (Redis va h.k.) kerak bo'ladi.
# ==========================================================
_JOIN_ATTEMPT_WINDOW_SECONDS = 60
_JOIN_ATTEMPT_MAX = 5
_join_attempts: dict[int, deque[float]] = defaultdict(deque)


def _enforce_join_attempt_limit(telegram_id: int) -> None:
    now = time.monotonic()
    attempts = _join_attempts[telegram_id]

    while attempts and now - attempts[0] > _JOIN_ATTEMPT_WINDOW_SECONDS:
        attempts.popleft()

    if len(attempts) >= _JOIN_ATTEMPT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Juda ko'p urinish. {_JOIN_ATTEMPT_WINDOW_SECONDS} soniyadan keyin qayta urinib ko'ring.",
        )

    attempts.append(now)


@router.post("", response_model=RoomOut)
async def create_room(
    payload: CreateRoomRequest,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    # TUZATILDI (MEDIUM — dublikat tekshiruv): abuse-lock tekshiruvi endi
    # FAQAT room_service ichida (avval bu yerda ham takrorlanardi — ikki
    # marta DB so'rovi va ikki xil xabar matni bilan).
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
    room = room_service.get_room(db, room_id, telegram_id)

    # TUZATILDI (HIGH — IDOR): avval har qanday autentifikatsiyalangan
    # foydalanuvchi istalgan room_id bo'yicha to'liq ishtirokchilar
    # ro'yxatini (telegram_id, first_name) ko'ra olardi — room_id ketma-ket
    # va oson taxmin qilinadigan raqam. Endi faqat shu xonaning a'zosi
    # ko'ra oladi.
    if not any(p.telegram_id == telegram_id for p in room.players):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Siz bu xonaga a'zo emassiz",
        )

    return room


@router.post("/{room_id}/join", response_model=RoomOut)
async def join_room(
    room_id: int,
    payload: JoinRoomRequest = JoinRoomRequest(),
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    if payload.join_code:
        # Faqat xona kodi bilan (security xona) qo'shilishga urinishlar
        # brute-force limitiga tushadi — public xonaga (join_code=None)
        # qo'shilish bunga tegishli emas.
        _enforce_join_attempt_limit(telegram_id)

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