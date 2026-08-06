from dataclasses import dataclass

from fastapi import WebSocket, status
from sqlalchemy.orm import Session

from api.deps import get_db
from core.security import decode_session_token
from models.room import Room, RoomStatus
from services.room_service import get_room_player_ids


@dataclass(slots=True)
class AuthResult:
    telegram_id: int
    room_player_ids: list[int]
    db: Session
    db_gen: object


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

    payload = decode_session_token(token)

    if payload is None:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
        )
        return None

    sub = payload.get("sub")

    if sub is None:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
        )
        return None

    try:
        telegram_id = int(sub)
    except (TypeError, ValueError):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
        )
        return None

    db_gen = get_db()
    db = next(db_gen)

    room = (
        db.query(Room)
        .filter(Room.id == room_id)
        .first()
    )

    if room is None:
        db_gen.close()

        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
        )
        return None

    if room.status != RoomStatus.PLAYING:
        db_gen.close()

        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
        )
        return None

    room_player_ids = get_room_player_ids(
        db,
        room_id,
    )

    if telegram_id not in room_player_ids:
        db_gen.close()

        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
        )
        return None

    return AuthResult(
        telegram_id=telegram_id,
        room_player_ids=room_player_ids,
        db=db,
        db_gen=db_gen,
    )