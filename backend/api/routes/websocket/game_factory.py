"""
GameEngine factory va active_games registri bilan ishlash.

Vazifalari:

- Room uchun GameEngine olish yoki yaratish
- active_games registridan game qidirish
- active_games registridan game o'chirish
"""

import logging

from sqlalchemy.orm import Session

from models.user import User
from services.game_engine import GameEngine

from .state import (
    active_games,
    game_create_lock,
)

logger = logging.getLogger(__name__)


async def get_or_create_game(
    *,
    db: Session,
    room_id: int,
    player_ids: list[int],
) -> GameEngine:
    """
    Room uchun GameEngine qaytaradi — mavjud bo'lsa xotiradagisini,
    bo'lmasa yangisini yaratib active_games ga yozadi.
    """
    async with game_create_lock:

        existing = active_games.get(room_id)
        if existing is not None:
            return existing

        users = (
            db.query(User)
            .filter(User.telegram_id.in_(player_ids))
            .all()
        )

        # DIQQAT: nickname maydoni models/user.py da shu nom bilan
        # mavjud deb qabul qilindi — boshqacha nomlangan bo'lsa
        # (masalan first_name/username), shu qatorni moslashtiring.
        player_names: dict[int, str] = {
            user.telegram_id: (
                user.username
                or user.first_name
                or str(user.telegram_id)
            )
            for user in users
        }

        game = GameEngine(
            room_id,
            player_ids,
            player_names,
        )

        active_games[room_id] = game

        return game


def get_game(
    room_id: int,
) -> GameEngine | None:
    """
    active_games registridan room uchun GameEngine qaytaradi,
    topilmasa None.
    """
    return active_games.get(room_id)


async def remove_game(
    room_id: int,
) -> None:
    """
    active_games registridan room uchun GameEngine ni o'chiradi.
    Mavjud bo'lmasa ham xavfsiz — hech qanday xato tashlamaydi.
    """
    async with game_create_lock:
        active_games.pop(room_id, None)