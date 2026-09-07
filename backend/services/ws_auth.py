"""
backend/services/ws_auth.py 
WebSocket authentication/authorization helper.

Vazifalari:
- WS ticket'ni tekshirish (qisqa muddatli, decode_session_token EMAS)
- DB sessiya ochish
- Xona va o'yinchi validatsiyasi

MUHIM (resurs egaligi haqida kelishuv):
- Agar authenticate_websocket() None qaytarsa, u WebSocket'ni allaqachon
  yopgan va (agar ochilgan bo'lsa) DB sessiyasini ham yopib ulgurgan
  bo'ladi — chaqiruvchi tomon hech narsa tozalashi shart emas.
- Agar AuthResult qaytarilsa, undagi db_gen'ni yopish (db_gen.close())
  MAS'ULIYATI CHAQIRUVCHI TOMONDA (handler.py). Buni albatta `finally`
  blokida bajarish kerak — aks holda har bir WebSocket ulanishida bitta
  DB sessiya oqib qoladi (connection/session leak).
"""

import logging
from dataclasses import dataclass

from fastapi import WebSocket, status
from sqlalchemy.orm import Session, joinedload

from collections.abc import Generator

from api.deps import get_db
from core.security import decode_ws_ticket
from models.room import Room, RoomPlayer, RoomStatus

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class AuthResult:
    telegram_id: int
    room_player_ids: list[int]
    player_names: dict[int, str]
    db: Session
    db_gen: Generator[Session, None, None]


async def _reject(
    websocket: WebSocket,
    code: int,
    db_gen: Generator[Session, None, None] | None = None,
) -> None:
    if db_gen is not None:
        try:
            db_gen.close()
        except Exception:
            pass

    try:
        await websocket.close(code=code)
    except Exception:
        pass


async def authenticate_websocket(
    websocket: WebSocket,
    room_id: int,
    token: str,
) -> AuthResult | None:
    """
    WebSocket ulanishini tekshiradi.

    Tekshiradi:
      - WS ticket (qisqa muddatli, decode_ws_ticket orqali)
      - room mavjudligi
      - room PLAYING holati
      - foydalanuvchi room ichidaligi
    """

    try:
        payload = decode_ws_ticket(token)
    except Exception:
        logger.exception("WS ticket'ni dekodlashda kutilmagan xato")
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    if payload is None:
        logger.warning("WS AUTH FAIL: ticket invalid")
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    sub = payload.get("sub")

    if sub is None or str(sub).strip() == "":
        # 4 chi: WS ticket ichidagi `sub` bo'sh bo'lsa, foydalanuvchi
        # identifikatori noto'g'ri bo'lib qoladi. Buni darhol rad etamiz.
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    try:
        telegram_id = int(str(sub))
    except (TypeError, ValueError):
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    db_gen = get_db()

    try:
        db = next(db_gen)
    except Exception:
        logger.exception("DB sessiyasini olishda xato")
        await _reject(websocket, status.WS_1011_INTERNAL_ERROR, db_gen)
        return None

    try:
        room = (
            db.query(Room)
            .options(joinedload(Room.players).joinedload(RoomPlayer.user))
            .filter(Room.id == room_id)
            .first()
        )

        if room is None:
            logger.warning(
                "WS AUTH FAIL: room not found room=%s telegram_id=%s",
                room_id,
                telegram_id,
            )
            await _reject(websocket, status.WS_1008_POLICY_VIOLATION, db_gen)
            return None

        if room.status != RoomStatus.PLAYING:
            logger.warning(
                "WS AUTH FAIL: room status=%s room=%s telegram_id=%s",
                room.status,
                room_id,
                telegram_id,
            )
            await _reject(websocket, status.WS_1008_POLICY_VIOLATION, db_gen)
            return None

        sorted_players = sorted(room.players, key=lambda p: p.joined_at)
        room_player_ids = [p.user.telegram_id for p in sorted_players]
        player_names = {p.user.telegram_id: p.user.first_name for p in sorted_players}

        logger.info(
            "WS AUTH: room=%s telegram_id=%s players=%s status=%s",
            room_id,
            telegram_id,
            room_player_ids,
            room.status,
        )

        if telegram_id not in room_player_ids:
            logger.warning(
                "WS AUTH FAIL: player roomda yo'q "
                "room=%s telegram_id=%s players=%s",
                room_id,
                telegram_id,
                room_player_ids,
            )
            await _reject(websocket, status.WS_1008_POLICY_VIOLATION, db_gen)
            return None
        return AuthResult(
            telegram_id=telegram_id,
            room_player_ids=room_player_ids,
            player_names=player_names,
            db=db,
            db_gen=db_gen,
        )

    except Exception:
        logger.exception(
            "Xona ma'lumotini tekshirishda xato room=%s telegram_id=%s",
            room_id,
            telegram_id,
        )
        await _reject(websocket, status.WS_1011_INTERNAL_ERROR, db_gen)
        return None