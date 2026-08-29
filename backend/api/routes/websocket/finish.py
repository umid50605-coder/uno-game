"""
Game finish helpers.

backend/api/routes/websocket/finish.py

Vazifalari:

- O'yinni xavfsiz yakunlash
- Reytingni hisoblash
- Room holatini yakunlash
- game_over event yuborish
- Active GameEngine ni xotiradan o'chirish
- Agar xona tournamentga tegishli bo'lsa, tournament_service'ga signal berish
"""

import logging

from sqlalchemy.orm import Session

from models.room import Room, RoomType
from services.game_engine import GameEngine
from services import tournament_service
from services.rating_service import apply_game_result
from services.room_service import finish_room

from .state import (
    game_finish_lock,
    game_manager,
    manager,
)

logger = logging.getLogger(__name__)


def _notify_tournament_if_needed(db: Session, room_id: int, winner: int | None) -> None:
    """Xona tournamentga tegishli bo'lsa, tegishli tournament_service
    funksiyasini chaqiradi. Bu KRITIK BO'LMAGAN qadam — xato bersa faqat
    logga yoziladi, o'yin natijasi (rating/room) allaqachon yozib bo'lingan."""
    try:
        room = db.query(Room).filter(Room.id == room_id).first()
        if room is None or room.room_type != RoomType.TOURNAMENT:
            return

        if winner is not None:
            tournament_service.handle_tournament_match_finished(db, room_id, winner)
        else:
            tournament_service.handle_tournament_match_abandoned(db, room_id)

    except Exception:
        logger.exception(
            "Tournament match holatini yangilashda xato room=%s winner=%s",
            room_id, winner,
        )


async def finish_game(
    *,
    db: Session,
    room_id: int,
    game: GameEngine,
    winner: int,
    via_forfeit: bool = False,
    loser: int | None = None,
) -> bool:
    """
    O'yinni xavfsiz yakunlaydi.

    Returns:
        True  -> muvaffaqiyatli yakunlandi
        False -> avval yakunlangan yoki xatolik yuz berdi
    """

    if via_forfeit and loser is None:
        raise ValueError("loser required when via_forfeit=True")

    async with game_finish_lock:

        if game.finished:
            return False

        game.finished = True

        # 1-QISM — KRITIK: reyting va room holatini yakunlash.
        try:
            if via_forfeit:
                if loser is None:
                    raise ValueError("loser required when via_forfeit=True")

                apply_game_result(
                    db=db,
                    player_ids=[loser, winner],
                    winner_id=winner,
                    via_forfeit=True,
                )
            else:
                apply_game_result(
                    db=db,
                    player_ids=game.player_ids,
                    winner_id=winner,
                )

            finish_room(db, room_id)
            db.commit()

        except Exception:

            game.finished = False

            try:
                db.rollback()
            except Exception:
                logger.exception(
                    "db.rollback() ham muvaffaqiyatsiz room=%s",
                    room_id,
                )

            logger.exception(
                "finish_game: reyting/room yakunlashda xato room=%s",
                room_id,
            )

            return False

        # 2-QISM — KRITIK EMAS: tournament signal, broadcast, xotira tozalash.
        _notify_tournament_if_needed(db, room_id, winner)

        try:
            await manager.broadcast_raw(
                room_id,
                {
                    "type": "game_over",
                    "winner": winner,
                },
            )
        except Exception:
            logger.exception(
                "game_over broadcast qilinmadi room=%s",
                room_id,
            )

        try:
            game_manager.remove(room_id)
        except Exception:
            logger.exception(
                "remove_game muvaffaqiyatsiz room=%s",
                room_id,
            )

        logger.info(
            "Game finished room=%s winner=%s",
            room_id, winner,
        )

        return True


async def cancel_game(
    *,
    db: Session,
    room_id: int,
    game: GameEngine,
) -> bool:
    """
    Xona bekor qilinganda yoki bo'shab qolganda chaqiriladi.
    Reyting hisoblanmaydi.

    Returns:
        True  -> muvaffaqiyatli bekor qilindi
        False -> avval yakunlangan/bekor qilingan yoki xatolik yuz berdi
    """

    async with game_finish_lock:

        if game.finished:
            return False

        game.finished = True

        try:
            finish_room(db, room_id)
            db.commit()

        except Exception:

            game.finished = False

            try:
                db.rollback()
            except Exception:
                logger.exception(
                    "db.rollback() ham muvaffaqiyatsiz room=%s",
                    room_id,
                )

            logger.exception(
                "cancel_game: finish_room xatosi room=%s",
                room_id,
            )

            return False

        # KRITIK EMAS: tournament signal (g'olibsiz yakunlanish), broadcast, tozalash.
        _notify_tournament_if_needed(db, room_id, winner=None)

        try:
            await manager.broadcast_raw(
                room_id,
                {"type": "game_cancelled"},
            )
        except Exception:
            logger.exception(
                "game_cancelled broadcast qilinmadi room=%s",
                room_id,
            )

        try:
            game_manager.remove(room_id)
        except Exception:
            logger.exception(
                "remove_game muvaffaqiyatsiz room=%s",
                room_id,
            )

        logger.info("Game cancelled room=%s", room_id)

        return True