"""
Initial state helper.

backend/api/routes/websocket/initial_state.py

Vazifalari:

- Initial state yuborish
- Reconnect holatini tiklash
- O'yinchi chiqarilgan bo'lsa ulanishni yopish
"""

import logging

from fastapi import (
    WebSocket,
    status,
)

from services.game_engine import GameEngine

from .state import manager

logger = logging.getLogger(__name__)


async def _safe_close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:
        pass


async def send_initial_state(
    *,
    websocket: WebSocket,
    room_id: int,
    telegram_id: int,
    game: GameEngine,
) -> bool:
    """
    O'yinchiga boshlang'ich holatni yuboradi.

    Returns:
        True  -> o'yinni davom ettirish mumkin.
        False -> WebSocket yopildi (yoki ulanish allaqachon o'lik).
    """

    initial_state = game.get_state(
        telegram_id,
    )

    # O'yinchi allaqachon forfeit bo'lgan
    if initial_state.get("type") == "not_in_game":

        try:
            await websocket.send_json(
                {
                    "type": "forfeited",
                    "message": (
                        "Siz ushbu o'yindan "
                        "chiqarilgansiz."
                    ),
                },
            )
        except Exception:
            logger.exception(
                "Forfeited message yuborilmadi "
                "room=%s player=%s",
                room_id,
                telegram_id,
            )

        await _safe_close(websocket, status.WS_1008_POLICY_VIOLATION)

        return False

    # Reconnect
    was_reconnected = game.is_disconnected(
        telegram_id,
    )

    if was_reconnected:
        game.mark_reconnected(
            telegram_id,
        )

    # Initial state yuborish
    try:
        await websocket.send_json(
            initial_state,
        )
    except Exception:
        logger.exception(
            "Initial state yuborilmadi room=%s player=%s",
            room_id,
            telegram_id,
        )
        # Ulanish aslida o'lik — buni oddiy uzilish sifatida qaytaramiz,
        # chaqiruvchi tomon o'z disconnect-cleanup yo'lini bajaradi.
        return False

    # Reconnect bo'lganini boshqalarga aytish. Bu BEST-EFFORT xabar —
    # muvaffaqiyatsiz bo'lsa ham JORIY o'yinchining ulanishi buzilmasin,
    # shuning uchun alohida try/except bilan o'ralgan va xatolik yuqoriga
    # chiqarilmaydi.
    if was_reconnected:

        try:
            await manager.broadcast_raw(
                room_id,
                {
                    "type": "player_reconnected",
                    "player_id": telegram_id,
                },
            )
        except Exception:
            logger.exception(
                "player_reconnected broadcast qilinmadi room=%s player=%s",
                room_id,
                telegram_id,
            )

        try:
            await manager.broadcast_state(
                room_id,
                game,
            )
        except Exception:
            logger.exception(
                "broadcast_state qilinmadi room=%s player=%s",
                room_id,
                telegram_id,
            )

        logger.info(
            "Player reconnected room=%s player=%s",
            room_id,
            telegram_id,
        )

    else:
        # DIQQAT: avvalgi versiyada bu log har doim "reconnected" deb
        # yozilardi — hatto birinchi marta ulanayotgan o'yinchi uchun ham.
        # Endi ikkisi aniq ajratilgan.
        logger.info(
            "Player connected room=%s player=%s",
            room_id,
            telegram_id,
        )

    return True