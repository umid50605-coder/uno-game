"""
Disconnect watcher — grace period tugagan playerlarni forfeit qiladi.

backend/api/routes/websocket/disconnect_watcher.py

Vazifalari:

- Har 5 soniyada barcha faol o'yinlarni tekshirish
- Grace period tugagan disconnected playerlarni forfeit qilish
- Forfeit natijasiga qarab o'yinni yakunlash yoki davom ettirish
- Anti-abuse xizmatiga forfeit-disconnect voqeasini qayd qilish
"""

import asyncio
import logging

from sqlalchemy.orm import Session

from api.deps import get_db
from services import abuse_service
from services.game_engine import GameEngine
from services.rating_service import apply_forfeit_result

from .finish import (
    cancel_game,
    finish_game,
)
from .state import (
    game_manager,
    manager,
)

logger = logging.getLogger(__name__)


async def _process_expired_player(
    db: Session,
    room_id: int,
    game: GameEngine,
    player_id: int,
) -> None:
    """
    Bitta playerni forfeit qiladi va natijaga qarab o'yinni
    yakunlaydi, bekor qiladi yoki davom ettiradi.
    """
    result = game.forfeit_player(player_id)

    if not result.get("ok"):
        return

    try:
        abuse_service.record_forfeit_disconnect(
            db,
            player_id,
        )
    except Exception:
        logger.exception(
            "record_forfeit_disconnect xatosi room=%s player=%s",
            room_id,
            player_id,
        )

    try:
        await manager.broadcast_raw(
            room_id,
            {
                "type": "player_forfeited",
                "player_id": player_id,
            },
        )
    except Exception:
        logger.exception(
            "player_forfeited broadcast qilinmadi room=%s player=%s",
            room_id,
            player_id,
        )

    if result.get("empty"):
        await cancel_game(
            db=db,
            room_id=room_id,
            game=game,
        )
        return

    winner = result.get("winner")

    if winner is not None:
        await finish_game(
            db=db,
            room_id=room_id,
            game=game,
            winner=winner,
            via_forfeit=True,
            loser=player_id,
        )
        return

    apply_forfeit_result(
        db,
        player_id,
        game.player_ids,
    )

    db.commit()

    try:
        await manager.broadcast_state(
            room_id,
            game,
        )
    except Exception:
        logger.exception(
            "broadcast_state qilinmadi room=%s player=%s",
            room_id,
            player_id,
        )


async def _process_room(
    db: Session,
    room_id: int,
    game: GameEngine,
) -> None:
    """
    Bitta room uchun barcha muddati o'tgan disconnectlarni forfeit
    qiladi. O'yin biror sabab bilan tugasa (finish/cancel), qolgan
    expired playerlar qayta ishlov berilmasdan qoldiriladi.
    """
    if game.finished:
        return

    expired_player_ids = game.get_expired_disconnects()

    for player_id in expired_player_ids:
        if game.finished:
            return

        try:
            await _process_expired_player(
                db,
                room_id,
                game,
                player_id,
            )
        except Exception:
            logger.exception(
                "disconnect_watcher: forfeit xatosi room=%s player=%s",
                room_id,
                player_id,
            )
            try:
                db.rollback()
            except Exception:
                logger.exception(
                    "disconnect_watcher: db.rollback() ham "
                    "muvaffaqiyatsiz room=%s",
                    room_id,
                )


async def disconnect_watcher() -> None:
    """
    Fon jarayoni: har 5 soniyada barcha faol o'yinlarni tekshirib,
    grace period tugagan disconnected playerlarni forfeit qiladi.

    Bu funksiya hech qachon o'zi to'xtamasligi kerak — bitta room yoki
    bitta playerda yuz bergan xato faqat o'sha bitta ishlov berishni
    to'xtatadi, keyingi tsikl davom etadi.
    """
    while True:
        await asyncio.sleep(5)

        db_gen = get_db()
        try:
            db = next(db_gen)
        except Exception:
            logger.exception(
                "disconnect_watcher: DB sessiyasini olishda xato",
            )
            try:
                db_gen.close()
            except Exception:
                pass
            continue

        try:

            games_snapshot = game_manager.items()

            for room_id, game in games_snapshot:
                try:
                    await _process_room(
                        db,
                        room_id,
                        game,
                    )
                except Exception:
                    logger.exception(
                        "disconnect_watcher: room=%s ishlov berishda xato",
                        room_id,
                    )
        except Exception:
            logger.exception(
                "disconnect_watcher: kutilmagan xato",
            )
        finally:
            try:
                db_gen.close()
            except Exception:
                pass
            