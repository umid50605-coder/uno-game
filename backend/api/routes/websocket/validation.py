"""
WebSocket validation helpers.

Vazifalari:
- JWT tokenni tekshirish
- Xona va o'yinchi validatsiyasi
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from core.security import decode_session_token
from models.room import Room, RoomStatus
from services.room_service import get_room_player_ids

logger = logging.getLogger(__name__)


async def validate_user(token: str) -> Optional[int]:
    """
    JWT tokenni tekshiradi.

    Returns:
        telegram_id yoki None.
    """
    try:
        payload = decode_session_token(token)
    except Exception:
        logger.exception("Tokenni dekodlashda kutilmagan xato")
        return None

    if payload is None:
        return None

    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None


def get_room_data(
    db: Session,
    room_id: int,
    telegram_id: int,
) -> tuple[Optional[Room], Optional[list[int]]]:
    """
    Xona mavjudligini va foydalanuvchi ushbu xonada ekanligini tekshiradi.

    Returns:
        (room, player_ids)
        yoki
        (None, None)
    """

    room = (
        db.query(Room)
        .filter(Room.id == room_id)
        .first()
    )

    if room is None:
        return None, None

    if room.status != RoomStatus.PLAYING:
        return None, None

    player_ids = list(get_room_player_ids(db, room_id))

    if telegram_id not in player_ids:
        return None, None

    return room, player_ids