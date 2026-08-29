"""
backend/api/routes/tournament.py
"""
import logging

from fastapi import APIRouter, Depends
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
    result = tournament_service.cancel_tournament(db, tournament_id, telegram_id)

    # Ishtirokchilarga real-vaqtda bildirish (kritik emas — xato bersa
    # cancel natijasi baribir qaytariladi).
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
    db: Session = Depends(get_db),
):
    return tournament_service.get_tournament(db, tournament_id)


@router.get("/{tournament_id}/bracket", response_model=TournamentOut)
def get_bracket(
    tournament_id: int,
    db: Session = Depends(get_db),
):
    """Hozircha to'liq tournament holati bilan bir xil (players+rounds+matches
    allaqachon TournamentOut ichida bor) — kelajakda faqat bracket qismini
    qaytaradigan qisqartirilgan sxema kerak bo'lsa, alohida ajratish mumkin."""
    return tournament_service.get_tournament(db, tournament_id)