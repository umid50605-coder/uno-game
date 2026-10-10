"""
backend/services/ws_auth.py
WebSocket authentication/authorization helper.

Vazifalari:
- WS ticket'ni tekshirish (qisqa muddatli, decode_session_token EMAS)
- Xona va o'yinchi validatsiyasi

MUHIM (audit F-11 — DB session lifecycle):
Avval bu funksiya SQLAlchemy Session ochib, uni BUTUN WebSocket ulanishi
davomida (o'yin soatlab davom etishi mumkin) ushlab turardi. Ko'p uzoq ulanish
DB connection pool'ni to'ldirib qo'yishi mumkin edi. Endi:

    authenticate -> query -> session YOPILADI -> (keyin) socket bilan ishlash

AuthResult hech qanday Session saqlamaydi — faqat oddiy qiymatlar (int, str).
Keyingi DB amallari (o'yin yakunlash, forfeit, turnir) kerak bo'lganda o'zining
qisqa muddatli sessiyasini ochadi (api/routes/websocket/finish.py).

Resurs egaligi: authenticate_websocket() None qaytarsa, u WebSocket'ni
allaqachon yopib ulgurgan — chaqiruvchi hech narsa tozalashi shart emas.
"""

import logging
from dataclasses import dataclass

from fastapi import WebSocket, status
from sqlalchemy.orm import joinedload

from core.database import SessionLocal
from core.security import decode_ws_ticket
from models.room import Room, RoomPlayer, RoomStatus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AuthResult:
    telegram_id: int
    room_player_ids: list[int]
    player_names: dict[int, str]


@dataclass(slots=True)
class _RoomSnapshot:
    """Room haqida DB sessiyasidan MUSTAQIL (faqat oddiy qiymatlar) nusxa."""
    status: RoomStatus
    player_ids: list[int]
    player_names: dict[int, str]


def _load_room_snapshot(room_id: int) -> _RoomSnapshot | None:
    """Qisqa muddatli sessiyada xona ma'lumotini o'qiydi va sessiyani YOPADI."""
    db = SessionLocal()
    try:
        room = (
            db.query(Room)
            .options(joinedload(Room.players).joinedload(RoomPlayer.user))
            .filter(Room.id == room_id)
            .first()
        )
        if room is None:
            return None

        sorted_players = sorted(room.players, key=lambda p: p.joined_at)
        return _RoomSnapshot(
            status=room.status,
            player_ids=[p.user.telegram_id for p in sorted_players],
            player_names={p.user.telegram_id: p.user.first_name for p in sorted_players},
        )
    finally:
        db.close()


async def _reject(websocket: WebSocket, code: int) -> None:
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

    try:
        snapshot = _load_room_snapshot(room_id)
    except Exception:
        logger.exception(
            "Xona ma'lumotini tekshirishda xato room=%s telegram_id=%s",
            room_id,
            telegram_id,
        )
        await _reject(websocket, status.WS_1011_INTERNAL_ERROR)
        return None

    # Bu nuqtadan boshlab DB sessiyasi allaqachon yopilgan.

    if snapshot is None:
        logger.warning(
            "WS AUTH FAIL: room not found room=%s telegram_id=%s",
            room_id,
            telegram_id,
        )
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    if snapshot.status != RoomStatus.PLAYING:
        logger.warning(
            "WS AUTH FAIL: room status=%s room=%s telegram_id=%s",
            snapshot.status,
            room_id,
            telegram_id,
        )
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    logger.info(
        "WS AUTH: room=%s telegram_id=%s players=%s status=%s",
        room_id,
        telegram_id,
        snapshot.player_ids,
        snapshot.status,
    )

    if telegram_id not in snapshot.player_ids:
        logger.warning(
            "WS AUTH FAIL: player roomda yo'q "
            "room=%s telegram_id=%s players=%s",
            room_id,
            telegram_id,
            snapshot.player_ids,
        )
        await _reject(websocket, status.WS_1008_POLICY_VIOLATION)
        return None

    return AuthResult(
        telegram_id=telegram_id,
        room_player_ids=snapshot.player_ids,
        player_names=snapshot.player_names,
    )
