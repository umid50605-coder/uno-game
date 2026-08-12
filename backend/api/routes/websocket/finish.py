"""
Game finish helpers.

backend/api/routes/websocket/finish.py

Vazifalari:

- O'yinni xavfsiz yakunlash
- Reytingni hisoblash
- Room holatini yakunlash
- game_over event yuborish
- Active GameEngine ni xotiradan o'chirish
"""

import logging

from sqlalchemy.orm import Session

from services.game_engine import GameEngine
from services.rating_service import apply_game_result
from services.room_service import finish_room

from .state import (
    game_finish_lock,
    game_manager,
    manager,
)

logger = logging.getLogger(__name__)


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

    # Dasturchi xatosi (loser berilmagan) — bu holatni "keyinroq qayta
    # urinib ko'ramiz" deb yashirish noto'g'ri, shuning uchun lock/try
    # ichiga kirmasdan darhol ko'rinadigan qilib chiqaramiz.
    if via_forfeit and loser is None:
        raise ValueError("loser required when via_forfeit=True")

    async with game_finish_lock:

        if game.finished:
            return False

        game.finished = True

        # 1-QISM — KRITIK: reyting va room holatini yakunlash.
        # Bu ikkisidan biri muvaffaqiyatsiz bo'lsa, o'yin haqiqatan ham
        # yakunlanmagan hisoblanadi — shuning uchun finished=False qaytariб,
        # keyinroq qayta urinishga ruxsat beramiz (xavfsiz, chunki hech
        # narsa hali qat'iy yozilmagan/broadcast qilinmagan).
        try:

            if via_forfeit:
                if loser is None:
                    raise ValueError(
                        "loser required when via_forfeit=True"
                    )
                
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

            finish_room(
                db,
                room_id,
            )

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

        # 2-QISM — KRITIK EMAS: bu nuqtadan keyingi har qanday xato
        # o'yin holatini ORQAGA QAYTARMAYDI. Reyting va room holati
        # allaqachon muvaffaqiyatli yozilgan — broadcast yoki xotiradan
        # tozalash muvaffaqiyatsiz bo'lishi reytingni QAYTA hisoblashga
        # (ya'ni ikki marta ball berilishiga) sabab bo'lmasligi kerak.
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
            game_manager.remove(
                room_id,
            )
        except Exception:
            logger.exception(
                "remove_game muvaffaqiyatsiz "
                "room=%s",
                room_id,
            )

        logger.info(
            "Game finished room=%s winner=%s",
            room_id,
            winner,
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

    DIQQAT — signatura o'zgardi: avval bu funksiya None qaytarardi,
    endi bool qaytaradi (True -> bekor qilindi, False -> avval
    yakunlangan/bekor qilingan yoki xatolik). disconnect_watcher.py
    hali yozilmagani uchun bu xavfsiz o'zgarish — lekin uni chaqirganda
    shunga mos yozing.

    Returns:
        True  -> muvaffaqiyatli bekor qilindi
        False -> avval yakunlangan/bekor qilingan yoki xatolik yuz berdi
    """

    async with game_finish_lock:

        # DIQQAT: avvalgi versiyada bu tekshiruv/o'rnatish lock'siz
        # bajarilardi — bu finish_game() bilan bir vaqtda chaqirilsa,
        # ikkalasi ham bir xil o'yinni ikki marta yakunlashi (ikki marta
        # finish_room/broadcast/remove_game) mumkin edi. Endi finish_game
        # bilan bir xil lock ishlatiladi.
        if game.finished:
            return False

        game.finished = True

        try:
            finish_room(
                db,
                room_id,
            )
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

        try:
            await manager.broadcast_raw(
                room_id,
                {
                    "type": "game_cancelled",
                },
            )
        except Exception:
            logger.exception(
                "game_cancelled broadcast qilinmadi room=%s",
                room_id,
            )

        try:
            game_manager.remove(
                room_id,
            )
        except Exception:
            logger.exception(
                "remove_game muvaffaqiyatsiz room=%s",
                room_id,
            )

        logger.info(
            "Game cancelled room=%s",
            room_id,
        )

        return True
    