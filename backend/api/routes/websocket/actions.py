"""
WebSocket client action dispatcher.

backend/api/routes/websocket/action.py fayli 

Vazifalari:

- Client'dan kelgan action'larni tekshirish (validation)
- Tekshirilgan parametrlar bilan tegishli GameEngine metodini chaqirish
"""

import logging
from typing import Any

from services.game_engine import GameEngine

logger = logging.getLogger(__name__)


async def handle_action(
    game: GameEngine,
    telegram_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Client action'ini tegishli GameEngine metodiga dispatch qiladi.

    GameEngine metodlari o'zi {"ok": bool, ...} shaklida natija
    qaytaradi deb hisoblanadi — bu funksiya faqat validation qilib,
    natijani o'zgarishsiz qaytaradi.
    """
    action = data.get("action")

    try:
        if action == "play_card":
            return _handle_play_card(
                game,
                telegram_id,
                data,
            )

        if action == "draw_card":
            return game.draw_card(
                player_id=telegram_id,
            )

        if action == "call_uno":
            return game.call_uno(
                player_id=telegram_id,
            )

        if action == "catch_uno":
            return _handle_catch_uno(
                game,
                telegram_id,
                data,
            )

        return {
            "ok": False,
            "error": f"Noma'lum action: {action!r}",
        }

    except Exception:
        logger.exception(
            "handle_action xatosi action=%s player=%s",
            action,
            telegram_id,
        )
        return {
            "ok": False,
            "error": "Ichki xatolik yuz berdi",
        }


def _handle_play_card(
    game: GameEngine,
    telegram_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    card_index = data.get("card_index")
    if not isinstance(card_index, int) or isinstance(card_index, bool):
        return {
            "ok": False,
            "error": "card_index int bo'lishi kerak",
        }

    chosen_color = data.get("chosen_color")
    if chosen_color is not None and not isinstance(chosen_color, str):
        return {
            "ok": False,
            "error": "chosen_color None yoki str bo'lishi kerak",
        }

    call_uno = bool(data.get("call_uno", False))

    return game.play_card(
        player_id=telegram_id,
        card_index=card_index,
        chosen_color=chosen_color,
        call_uno=call_uno,
    )


def _handle_catch_uno(
    game: GameEngine,
    telegram_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    target_id = data.get("target_id")
    if not isinstance(target_id, int) or isinstance(target_id, bool):
        return {
            "ok": False,
            "error": "target_id int bo'lishi kerak",
        }

    return game.catch_uno(
        catcher_id=telegram_id,
        target_id=target_id,
    )