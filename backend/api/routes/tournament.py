"""
backend/api/routes/tournament.py
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import get_current_user_id
from core.database import get_db
from models.schemas import (
    TournamentCreateOut,
    TournamentJoinRequest,
    TournamentOut,
    TournamentReadyRequest,
)
from services import tournament_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


def _ensure_tournament_member(tournament: dict, telegram_id: int) -> None:
    """TUZATILDI (HIGH — autentifikatsiyasiz ma'lumot oshkorligi): GET
    endpointlar avval HECH QANDAY autentifikatsiyasiz butun turnir holatini
    (barcha ishtirokchilarning telegram_id'lari, statuslari, match room
    ro'yxati) qaytarardi. Endi faqat turnir yaratuvchisi yoki ishtirokchi-
    laridan biri ko'ra oladi — bu WebSocket tomonidagi (tournament_ws.py)
    xuddi shunday tekshiruv bilan izchil."""
    if tournament.get("creator_telegram_id") == telegram_id:
        return
    if any(p["telegram_id"] == telegram_id for p in tournament.get("players", [])):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Siz bu turnir a'zosi emassiz",
    )


@router.post("", response_model=TournamentCreateOut)
def create_tournament(
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return tournament_service.create_tournament(db, telegram_id)


@router.post("/{tournament_id}/join", response_model=TournamentOut)
def join_tournament(
    tournament_id: int,
    payload: TournamentJoinRequest,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return tournament_service.join_tournament(db, tournament_id, telegram_id, payload.invite_token)


@router.post("/{tournament_id}/ready", response_model=TournamentOut)
def mark_ready(
    tournament_id: int,
    payload: TournamentReadyRequest,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return tournament_service.mark_ready(db, tournament_id, telegram_id, payload.ready)


@router.post("/{tournament_id}/leave", response_model=TournamentOut)
def leave_tournament(
    tournament_id: int,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return tournament_service.leave_tournament(db, tournament_id, telegram_id)


@router.post("/{tournament_id}/cancel", response_model=TournamentOut)
async def cancel_tournament(
    tournament_id: int,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    # TUZATILDI (CRITICAL — butun serverni muzlatib qo'yishi mumkin edi):
    # tournament_service.cancel_tournament ichida threading.Lock ishlatiladi
    # (chunki bu funksiya HAM sync REST route'lardan, HAM async WebSocket
    # kodidan chaqiriladi). Bu endpoint `async def` (broadcast uchun await
    # kerak) — uni to'g'ridan-to'g'ri chaqirish, lock band bo'lgan paytda
    # asyncio event loop'ning yagona threadini bloklab, o'sha daqiqada
    # BARCHA xonalardagi WebSocket ulanishlarini muzlatib qo'yishi mumkin
    # edi. asyncio.to_thread orqali alohida threadga chiqaramiz — xuddi
    # FastAPI sync route'larni threadpool'da ishga tushirgani kabi.
    result = await asyncio.to_thread(
        tournament_service.cancel_tournament, db, tournament_id, telegram_id
    )

    try:
        from api.routes.websocket.state import manager
        await manager.broadcast_to_tournament(
            tournament_id,
            {"type": "tournament_cancelled"},
        )
    except Exception:
        logger.exception(
            "tournament_cancelled broadcast qilinmadi tournament=%s",
            tournament_id,
        )

    return result


@router.get("/{tournament_id}", response_model=TournamentOut)
def get_tournament(
    tournament_id: int,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = tournament_service.get_tournament(db, tournament_id)
    _ensure_tournament_member(result, telegram_id)
    return result


@router.get("/{tournament_id}/bracket", response_model=TournamentOut)
def get_bracket(
    tournament_id: int,
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Hozircha to'liq tournament holati bilan bir xil (players+rounds+matches
    allaqachon TournamentOut ichida bor) — kelajakda faqat bracket qismini
    qaytaradigan qisqartirilgan sxema kerak bo'lsa, alohida ajratish mumkin."""
    result = tournament_service.get_tournament(db, tournament_id)
    _ensure_tournament_member(result, telegram_id)
    return result