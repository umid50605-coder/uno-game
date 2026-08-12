"""
Disconnect helper.

backend/api/routes/websocket/disconnect.py fayli

Vazifalari:

- WebSocket ulanishini uzish
- O'yinchini disconnected deb belgilash
- Grace Period boshlash
- Boshqa o'yinchilarga xabar yuborish
"""

import logging

from fastapi import WebSocket

from services.game_engine import (
    GameEngine,
    GRACE_PERIOD_SECONDS,
)

from .state import manager

logger = logging.getLogger(__name__)


async def disconnect_player(
    *,
    room_id: int,
    telegram_id: int,
    websocket: WebSocket,
    game: GameEngine | None,
) -> None:
    """
    O'yinchi uzilganda bajariladi.

    Bu funksiya har doim CLEANUP yo'lida (except/finally ichida)
    chaqiriladi, shuning uchun o'zi hech qachon exception tashlamasligi
    SHART — aks holda chaqiruvchi tomondagi qolgan cleanup bajarilmay
    qolishi mumkin. Shu sabab har bir xavfli chaqiruv alohida
    try/except bilan o'ralgan.
    """

    try:
        manager.disconnect(
            room_id,
            telegram_id,
            websocket,
        )
    except Exception:
        logger.exception(
            "manager.disconnect xatosi room=%s player=%s",
            room_id,
            telegram_id,
        )

    if game is None:
        return

    if game.finished:
        return

    try:
        game.mark_disconnected(
            telegram_id,
        )
    except Exception:
        logger.exception(
            "mark_disconnected xatosi room=%s player=%s",
            room_id,
            telegram_id,
        )
        return

    if not game.is_disconnected(
        telegram_id,
    ):
        return

    disconnected_at = game.disconnected_at.get(
        telegram_id,
    )

    if disconnected_at is None:
        logger.warning(
            "disconnect time topilmadi room=%s player=%s",
            room_id,
            telegram_id,
        )
        return

    try:
        await manager.broadcast_raw(
            room_id,
            {
                "type": "player_disconnected",
                "player_id": telegram_id,
                "disconnected_at": disconnected_at.isoformat(),
                "grace_period_seconds": GRACE_PERIOD_SECONDS,
            },
        )
    except Exception:
        logger.exception(
            "player_disconnected broadcast qilinmadi room=%s player=%s",
            room_id,
            telegram_id,
        )

    logger.info(
        "Player disconnected room=%s player=%s",
        room_id,
        telegram_id,
    )
    