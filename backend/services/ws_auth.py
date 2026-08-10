"""
WebSocket authentication/authorization helper.

Vazifalari:
- JWT tokenni tekshirish
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
from sqlalchemy.orm import Session

from collections.abc import Generator

from api.deps import get_db
from core.security import decode_session_token
from models.room import Room, RoomStatus
from services.room_service import get_room_player_ids

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class AuthResult:
    telegram_id: int
    room_player_ids: list[int]
    db: Session
    db_gen: Generator[Session, None, None]


async def _reject(
    websocket: WebSocket,
    code: int,
    db_gen: Generator[Session, None, None] | None = None,
) -> None:
    """
    Ulanishni rad etadi: avval (agar ochilgan bo'lsa) DB sessiyasini,
    keyin websocket'ni xavfsiz yopadi. Ikkalasi ham xato tashlasa
    ham davom etadi — rad etish jarayoni har doim yakunlanishi kerak.
    """
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
      - JWT token
      - room mavjudligi
      - room PLAYING holati
      - foydalanuvchi room ichidaligi
    """

    try:
        payload = decode_session_token(token)
    except Exception:
        logger.exception("Tokenni dekodlashda kutilmagan xato")
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    if payload is None:
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    sub = payload.get("sub")

    if sub is None:
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    try:
        telegram_id = int(sub)
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
            .filter(Room.id == room_id)
            .first()
        )

        if room is None:
            await _reject(websocket, status.WS_1008_POLICY_VIOLATION, db_gen)
            return None

        if room.status != RoomStatus.PLAYING:
            await _reject(websocket, status.WS_1008_POLICY_VIOLATION, db_gen)
            return None

        room_player_ids = get_room_player_ids(db, room_id)

        if telegram_id not in room_player_ids:
            await _reject(websocket, status.WS_1008_POLICY_VIOLATION, db_gen)
            return None

    except Exception:
        logger.exception(
            "Xona ma'lumotini tekshirishda xato room=%s telegram_id=%s",
            room_id,
            telegram_id,
        )
        await _reject(websocket, status.WS_1011_INTERNAL_ERROR, db_gen)
        return None

    return AuthResult(
        telegram_id=telegram_id,
        room_player_ids=room_player_ids,
        db=db,
        db_gen=db_gen,
    )
