"""
Tournament WebSocket handler.

backend/api/routes/websocket/tournament_ws.py

Vazifalari:
- Tournament darajasidagi real-time holatni kuzatish (lobby, ready, bracket
  progress) uchun WebSocket ulanishini boshqaradi.
- Bu O'YIN emas — o'yin logikasi handler.py/GameEngine orqali ishlaydi.
  Bu yerda faqat tournament_service.get_tournament() natijasi va
  connection_manager.broadcast_to_tournament() orqali yuborilgan eventlar bor.
"""

import logging

from fastapi import WebSocket, status
from sqlalchemy.orm import Session

from core.database import SessionLocal, get_db
from core.security import decode_session_token
from models.tournament import Tournament, TournamentPlayer

from .state import manager

logger = logging.getLogger(__name__)


async def _safe_close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:
        pass


async def authenticate_tournament_ws(
    websocket: WebSocket,
    tournament_id: int,
    token: str,
) -> int | None:
    """JWT token va tournament ishtirokchiligini tekshiradi. telegram_id yoki None qaytaradi."""
    try:
        payload = decode_session_token(token)
    except Exception:
        logger.exception("Tournament WS: tokenni dekodlashda kutilmagan xato")
        await _safe_close(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    if payload is None:
        logger.warning("Tournament WS AUTH FAIL: JWT invalid tournament=%s", tournament_id)
        await _safe_close(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    sub = payload.get("sub")
    if sub is None:
        await _safe_close(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    try:
        telegram_id = int(sub)
    except (TypeError, ValueError):
        await _safe_close(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    db_gen = get_db()
    try:
        db = next(db_gen)
    except Exception:
        logger.exception("Tournament WS: DB sessiyasini olishda xato")
        await _safe_close(websocket, status.WS_1011_INTERNAL_ERROR)
        return None

    try:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        if tournament is None:
            logger.warning(
                "Tournament WS AUTH FAIL: tournament not found id=%s telegram_id=%s",
                tournament_id, telegram_id,
            )
            await _safe_close(websocket, status.WS_1008_POLICY_VIOLATION)
            return None

        player = (
            db.query(TournamentPlayer)
            .filter(
                TournamentPlayer.tournament_id == tournament_id,
                TournamentPlayer.telegram_id == telegram_id,
            )
            .first()
        )
        if player is None:
            logger.warning(
                "Tournament WS AUTH FAIL: player not in tournament id=%s telegram_id=%s",
                tournament_id, telegram_id,
            )
            await _safe_close(websocket, status.WS_1008_POLICY_VIOLATION)
            return None

        return telegram_id

    except Exception:
        logger.exception(
            "Tournament WS: auth tekshirishda xato tournament=%s telegram_id=%s",
            tournament_id, telegram_id,
        )
        await _safe_close(websocket, status.WS_1011_INTERNAL_ERROR)
        return None
    finally:
        try:
            db_gen.close()
        except Exception:
            logger.exception("Tournament WS: db_gen yopishda xato")


async def tournament_websocket_handler(
    websocket: WebSocket,
    tournament_id: int,
    token: str,
) -> None:
    telegram_id = await authenticate_tournament_ws(websocket, tournament_id, token)
    if telegram_id is None:
        return  # websocket allaqachon yopilgan (authenticate ichida)

    await manager.connect_tournament(tournament_id, telegram_id, websocket)

    connected = True
    try:
        # Dastlabki holatni yuborish
        from services import tournament_service  # local import — circular importdan qochish uchun

        db: Session = SessionLocal()
        try:
            data = tournament_service.get_tournament(db, tournament_id)
        finally:
            db.close()

        try:
            await websocket.send_json({"type": "tournament_state", "data": data})
        except Exception:
            logger.exception(
                "Tournament WS: initial state yuborilmadi tournament=%s telegram_id=%s",
                tournament_id, telegram_id,
            )
            connected = False
            return

        # Mijozdan xabar kutish (heartbeat)
        while True:
            msg = await websocket.receive_json()
            if not isinstance(msg, dict):
                continue
            if msg.get("action") == "ping":
                await manager.send_to_tournament(tournament_id, telegram_id, {"type": "pong"})

    except Exception:
        # WebSocketDisconnect ham shu yerga tushadi — bu kutilgan holat,
        # shuning uchun faqat info darajasida logga yozamiz.
        logger.info(
            "Tournament WS uzildi tournament=%s telegram_id=%s",
            tournament_id, telegram_id,
        )
    finally:
        if connected:
            manager.disconnect_tournament(tournament_id, telegram_id, websocket)