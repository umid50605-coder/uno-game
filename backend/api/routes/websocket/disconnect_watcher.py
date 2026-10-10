"""
Disconnect watcher — grace period tugagan playerlarni forfeit qiladi.

backend/api/routes/websocket/disconnect_watcher.py

Vazifalari:

- Har 5 soniyada barcha faol o'yinlarni tekshirish
- Grace period tugagan disconnected playerlarni forfeit qilish
- Forfeit natijasiga qarab o'yinni yakunlash yoki davom ettirish
- Anti-abuse xizmatiga forfeit-disconnect voqeasini qayd qilish
- Yakunlanishi muvaffaqiyatsiz bo'lgan (g'olibi aniq) o'yinlarni qayta yakunlash

FORFEIT LIFECYCLE (audit F-05):

    plan_forfeit()          — RAM O'ZGARMAYDI, natija oldindan hisoblanadi
         |
         v
    DB (T1, bitta tranzaksiya) — finish_game / cancel_game /
                                 forfeit_player_and_continue (finish.py)
         |  commit muvaffaqiyatli
         v
    RAM (GameEngine.forfeit_player)

DB xatosida RAM tegilmagan bo'lib qoladi: o'yinchi hamon ro'yxatda va
`disconnected_at` saqlangan, shuning uchun navbatdagi sikl (5s) uni qayta
uradi. Muvaffaqiyatdan keyin o'yinchi RAM ro'yxatidan chiqib ketadi —
shuning uchun u ikki marta forfeit qilinmaydi va reyting ikki marta
qo'llanmaydi.

DB sessiyalari bu faylda ushlab turilmaydi: har bir DB amali finish.py
ichida o'zining qisqa muddatli sessiyasini ochadi va yopadi.
"""

import asyncio
import logging

from services.game_engine import GameEngine

from .finish import (
    cancel_game,
    finish_game,
    forfeit_player_and_continue,
)
from .state import game_manager

logger = logging.getLogger(__name__)


async def _process_expired_player(
    room_id: int,
    game: GameEngine,
    player_id: int,
) -> None:
    """
    Bitta playerni forfeit qiladi va natijaga qarab o'yinni
    yakunlaydi, bekor qiladi yoki davom ettiradi.

    Har uch yo'lda ham DB avval, RAM keyin (finish.py'da).
    """
    plan = game.plan_forfeit(player_id)

    if not plan.get("ok"):
        return

    if plan.get("empty"):
        await cancel_game(
            room_id=room_id,
            game=game,
            forfeiter=player_id,
        )
        return

    winner = plan.get("winner")

    if winner is not None:
        await finish_game(
            room_id=room_id,
            game=game,
            winner=winner,
            via_forfeit=True,
            loser=player_id,
        )
        return

    await forfeit_player_and_continue(
        room_id=room_id,
        game=game,
        player_id=player_id,
    )


async def _process_room(
    room_id: int,
    game: GameEngine,
) -> None:
    """
    Bitta room uchun:

    1) G'olibi aniq bo'lib, lekin yakunlanmay qolgan o'yin bo'lsa (oldingi
       finish_game() DB xatosi bilan tugagan) — yakunlashni QAYTA uradi.
       Bu DB-darajasida idempotent (finish.py), shuning uchun reyting ikki
       marta qo'llanmaydi.
    2) Aks holda barcha muddati o'tgan disconnectlarni forfeit qiladi.
       O'yin biror sabab bilan tugasa (finish/cancel), qolgan expired
       playerlar qayta ishlov berilmasdan qoldiriladi.
    """
    if game.finished:
        return

    if game.winner is not None:
        logger.warning(
            "Yakunlanmay qolgan o'yin topildi room=%s winner=%s — qayta yakunlanmoqda",
            room_id,
            game.winner,
        )
        await finish_game(
            room_id=room_id,
            game=game,
            winner=game.winner,
        )
        return

    expired_player_ids = game.get_expired_disconnects()

    for player_id in expired_player_ids:
        if game.finished or game.winner is not None:
            return

        try:
            await _process_expired_player(
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

        try:
            games_snapshot = game_manager.items()

            for room_id, game in games_snapshot:
                try:
                    await _process_room(
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
