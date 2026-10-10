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
- O'yin DAVOM ETAYOTGANDA (3+ o'yinchi) forfeit qilish

TRANSACTION EGALIGI (audit F-01/F-02/F-03/F-04/F-05/F-09)
=========================================================

Bu fayl o'yin natijasi bo'yicha YAGONA transaction egasi. Quyi qatlam
funksiyalari (rating_service.*, room_service.finish_room,
abuse_service.record_forfeit_disconnect, tournament.record_match_result)
HECH QACHON commit qilmaydi.

  finish_game
    +-- T1  (BITTA tranzaksiya, o'zining SessionLocal() sessiyasida)
    |     +-- Room qatorini SELECT ... FOR UPDATE bilan qulflash
    |     +-- room.status == FINISHED bo'lsa -> HECH NARSA qo'llamaymiz (idempotent)
    |     +-- rating mutation (apply_game_result)
    |     +-- forfeit bo'lsa: abuse log (SAVEPOINT ichida, jiddiy emas)
    |     +-- room mutation (finish_room -> FINISHED)
    |     +-- turnir xonasi bo'lsa: match natijasi (record_match_result)
    |     +-- COMMIT  (xatoda ROLLBACK — hech narsa yarim qolmaydi)
    +-- RAM yangilash (forfeit bo'lsa: GameEngine.forfeit_player)  <- DB'dan KEYIN
    +-- T2  (turnir xonasi bo'lsa; alohida thread + alohida SessionLocal())
    |     +-- match -> round FINISHED -> keyingi round / turnir FINISHED + reward
    |     +-- BITTA COMMIT (xatoda ROLLBACK; keyin recovery sweep qayta urinadi)
    +-- broadcast (game_over) va xotirani tozalash  (best-effort)

IDEMPOTENTLIK: finish qayta urinilsa ham reyting/games_played/wins/
forfeit_wins ikki marta qo'llanmaydi, chunki "room FINISHED"ga o'tish
reytingni yozish bilan BIR tranzaksiyada commit bo'ladi: commit bo'lgan bo'lsa
room FINISHED (keyingi urinish o'tkazib yuboradi), commit bo'lmagan bo'lsa ham
reyting, ham room o'zgarishi yo'q (keyingi urinish toza boshlanadi).
Bu DB-darajasidagi idempotentlik — `game.finished` RAM bayrog'iga bog'liq emas.
"""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.database import SessionLocal
from models.room import Room, RoomStatus, RoomType
from services import abuse_service, tournament_service
from services.game_engine import GameEngine
from services.rating_service import apply_forfeit_result, apply_game_result
from services.room_service import finish_room

from .state import (
    discard_game_finish_lock,
    game_manager,
    get_game_finish_lock,
    manager,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PersistResult:
    # DB'da room allaqachon FINISHED edi -> bu urinishda HECH NARSA qo'llanmadi.
    already_finished: bool
    # Room turnir matchiga tegishli -> T2 (tournament transition) kerak.
    tournament_match: bool


# ==========================================================
# T1 — o'yin natijasi tranzaksiyasi (sync, o'zining sessiyasi)
# ==========================================================

def _record_forfeit_abuse(db: Session, telegram_id: int) -> None:
    """Forfeit abuse logini SAVEPOINT ichida yozadi.

    Avvalgi xulq saqlanadi: abuse-log yozishdagi xato o'yin natijasini
    yiqitmasligi (faqat log qilinishi) kerak. SAVEPOINT shu xatoni asosiy
    tranzaksiyani buzmasdan ajratib beradi (PostgreSQL'da oddiy xato butun
    tranzaksiyani 'aborted' holatiga tushirib qo'yardi)."""
    try:
        with db.begin_nested():
            abuse_service.record_forfeit_disconnect(db, telegram_id)
    except Exception:
        logger.exception("record_forfeit_disconnect xatosi player=%s", telegram_id)


def _persist_game_result(
    *,
    room_id: int,
    player_ids: list[int],
    winner: int | None,
    via_forfeit: bool,
    loser: int | None,
    cancelled: bool,
) -> _PersistResult:
    """Rating + room + (turnir match) ni BITTA tranzaksiyada yozadi.

    O'zining SessionLocal()'ini ochadi va yopadi — chaqiruvchining
    (WebSocket handler) sessiyasi ishlatilmaydi va boshqa threadga
    uzatilmaydi. Xatoda rollback qilib xatoni qayta ko'taradi."""
    db = SessionLocal()
    try:
        room = (
            db.query(Room)
            .filter(Room.id == room_id)
            .with_for_update()
            .first()
        )

        if room is not None and room.status == RoomStatus.FINISHED:
            db.rollback()
            return _PersistResult(already_finished=True, tournament_match=False)

        if room is None:
            logger.error(
                "finish: room=%s DB'da topilmadi — natija baribir yoziladi, "
                "idempotentlik tekshiruvi mumkin emas",
                room_id,
            )

        if not cancelled:
            if via_forfeit:
                if loser is None or winner is None:
                    raise ValueError("loser and winner required when via_forfeit=True")
                apply_game_result(
                    db=db,
                    player_ids=[loser, winner],
                    winner_id=winner,
                    via_forfeit=True,
                )
            else:
                if winner is None:
                    raise ValueError("winner required for a non-cancelled game")
                apply_game_result(
                    db=db,
                    player_ids=player_ids,
                    winner_id=winner,
                )

        if loser is not None:
            _record_forfeit_abuse(db, loser)

        finish_room(db, room_id)

        tournament_match = False
        if room is not None and room.room_type == RoomType.TOURNAMENT:
            tournament_match = (
                tournament_service.record_match_result(
                    db,
                    room_id,
                    None if cancelled else winner,
                )
                is not None
            )

        db.commit()
        return _PersistResult(already_finished=False, tournament_match=tournament_match)

    except Exception:
        try:
            db.rollback()
        except Exception:
            logger.exception("db.rollback() ham muvaffaqiyatsiz room=%s", room_id)
        raise
    finally:
        db.close()


def _persist_midgame_forfeit(player_id: int, remaining_ids: list[int]) -> None:
    """O'yin DAVOM etayotganda (3+ o'yinchi) forfeit natijasi: forfeit
    qilgan o'yinchining reyting jazosi + qolganlarga bonus + abuse log —
    BITTA tranzaksiya."""
    db = SessionLocal()
    try:
        apply_forfeit_result(db, player_id, remaining_ids)
        _record_forfeit_abuse(db, player_id)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            logger.exception("db.rollback() ham muvaffaqiyatsiz player=%s", player_id)
        raise
    finally:
        db.close()


# ==========================================================
# T2 — tournament transition (alohida thread, alohida sessiya)
# ==========================================================

def _tournament_transition_sync(room_id: int, winner: int | None) -> None:
    """Worker thread ichida ishlaydi va O'ZINING SessionLocal()'ini ochadi.

    Audit F-01: avval WebSocket handlerning `db` Session'i
    asyncio.to_thread() orqali boshqa threadga uzatilardi — SQLAlchemy Session
    thread-safe emas. Endi thread'ga faqat primitiv qiymatlar (room_id, winner)
    uzatiladi."""
    db = SessionLocal()
    try:
        if winner is None:
            tournament_service.handle_tournament_match_abandoned(db, room_id)
        else:
            tournament_service.handle_tournament_match_finished(db, room_id, winner)
    finally:
        db.close()


async def _run_tournament_transition(room_id: int, winner: int | None) -> None:
    """T2'ni threadda ishga tushiradi.

    Xato JIM YUTILMAYDI (audit F-09): ERROR darajasida stacktrace bilan log
    qilinadi. T2 yiqilsa butun T2 rollback bo'lgan, o'yin natijasi (T1) esa
    saqlangan — round "barcha match FINISHED, lekin o'tish yo'q" holatida
    qoladi va main.py'dagi tournament watcher (recover_stalled_rounds) uni
    qayta bajaradi. Bu o'yin natijasini (reyting/room) rollback QILMAYDI."""
    try:
        await asyncio.to_thread(_tournament_transition_sync, room_id, winner)
    except Exception:
        logger.exception(
            "TOURNAMENT TRANSITION MUVAFFAQIYATSIZ room=%s winner=%s — "
            "o'yin natijasi saqlangan, recovery sweep qayta urinadi",
            room_id,
            winner,
        )


# ==========================================================
# RAM yordamchilari
# ==========================================================

def _sync_forfeit_to_ram(game: GameEngine, player_id: int) -> None:
    """DB commit MUVAFFAQIYATLI bo'lgandan KEYIN RAM'ni DB'ga moslaydi
    (o'yinchini ro'yxatdan chiqaradi / g'olibni belgilaydi)."""
    try:
        game.forfeit_player(player_id)
    except Exception:
        logger.exception(
            "forfeit_player RAM yangilanishi xatosi room=%s player=%s",
            game.room_id,
            player_id,
        )


async def broadcast_player_forfeited(room_id: int, player_id: int) -> None:
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


# ==========================================================
# Public API
# ==========================================================

async def finish_game(
    *,
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
        False -> avval yakunlangan, forfeit endi dolzarb emas yoki
                 xatolik yuz berdi (RAM o'zgarmaydi — qayta urinish mumkin)
    """

    if via_forfeit and loser is None:
        raise ValueError("loser required when via_forfeit=True")

    if game.finished:
        return False

    async with get_game_finish_lock(room_id):

        if game.finished:
            return False

        # Lock kutilgan paytda o'yinchi qayta ulangan yoki holat o'zgargan
        # bo'lishi mumkin — forfeit hali ham dolzarbligini qayta tekshiramiz.
        if via_forfeit and not game.forfeit_is_due(loser):
            return False

        game.finished = True

        # 1-QISM — KRITIK (T1): reyting + room + turnir match, BITTA tranzaksiya.
        try:
            persisted = _persist_game_result(
                room_id=room_id,
                player_ids=list(game.player_ids),
                winner=winner,
                via_forfeit=via_forfeit,
                loser=loser,
                cancelled=False,
            )
        except Exception:
            # T1 to'liq rollback qilingan: na reyting, na room o'zgargan.
            # RAM o'zgarmagan (forfeit bo'lsa o'yinchi hali ro'yxatda va
            # disconnected_at saqlangan) — watcher keyingi siklda qayta uriladi.
            game.finished = False
            logger.exception(
                "finish_game: reyting/room yakunlashda xato room=%s "
                "(qayta uriniladi)",
                room_id,
            )
            return False

        if persisted.already_finished:
            logger.warning(
                "finish_game: room=%s DB'da allaqachon FINISHED — reyting "
                "QAYTA qo'llanmadi, faqat xotira tozalanadi",
                room_id,
            )

        # RAM'ni DB'ga moslash (DB commit'dan KEYIN).
        if via_forfeit and loser is not None:
            _sync_forfeit_to_ram(game, loser)

        # 2-QISM: T2 (turnir) va best-effort qadamlar.
        if persisted.tournament_match:
            await _run_tournament_transition(room_id, winner)

        if via_forfeit and loser is not None:
            await broadcast_player_forfeited(room_id, loser)

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

        discard_game_finish_lock(room_id)

        logger.info(
            "Game finished room=%s winner=%s",
            room_id, winner,
        )

        return True


async def cancel_game(
    *,
    room_id: int,
    game: GameEngine,
    forfeiter: int | None = None,
) -> bool:
    """
    Xona bekor qilinganda yoki bo'shab qolganda chaqiriladi.
    Reyting hisoblanmaydi.

    forfeiter — agar bekor qilish oxirgi qolgan o'yinchining forfeit
    qilinishi sabab bo'lsa, uning abuse logi shu tranzaksiyada yoziladi.

    Returns:
        True  -> muvaffaqiyatli bekor qilindi
        False -> avval yakunlangan/bekor qilingan, forfeit dolzarb emas
                 yoki xatolik yuz berdi (RAM o'zgarmaydi)
    """

    if game.finished:
        return False

    async with get_game_finish_lock(room_id):

        if game.finished:
            return False

        if forfeiter is not None and not game.forfeit_is_due(forfeiter):
            return False

        game.finished = True

        try:
            persisted = _persist_game_result(
                room_id=room_id,
                player_ids=list(game.player_ids),
                winner=None,
                via_forfeit=False,
                loser=forfeiter,
                cancelled=True,
            )
        except Exception:
            game.finished = False
            logger.exception(
                "cancel_game: finish_room xatosi room=%s (qayta uriniladi)",
                room_id,
            )
            return False

        if forfeiter is not None:
            _sync_forfeit_to_ram(game, forfeiter)

        # KRITIK EMAS: tournament signal (g'olibsiz yakunlanish), broadcast, tozalash.
        if persisted.tournament_match:
            await _run_tournament_transition(room_id, None)

        if forfeiter is not None:
            await broadcast_player_forfeited(room_id, forfeiter)

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

        discard_game_finish_lock(room_id)

        logger.info("Game cancelled room=%s", room_id)

        return True


async def forfeit_player_and_continue(
    *,
    room_id: int,
    game: GameEngine,
    player_id: int,
) -> bool:
    """O'yin DAVOM ETAYOTGANDA (forfeitdan keyin kamida 2 o'yinchi qoladi)
    grace period tugagan o'yinchini forfeit qiladi.

    Audit F-05 tartibi (avval teskari edi — RAM avval o'zgarardi):

        1. forfeit hali dolzarbligini tekshirish (plan_forfeit — RAM o'zgarmaydi)
        2. DB: reyting + abuse log -> BITTA tranzaksiya, COMMIT
        3. FAQAT shundan keyin RAM: GameEngine.forfeit_player()
        4. broadcast (best-effort)

    DB yiqilsa RAM tegilmagan: o'yinchi hamon ro'yxatda va `disconnected_at`
    saqlangan, shuning uchun watcher keyingi siklda (5s) qayta urinadi.
    O'yinchi 3-bandda ro'yxatdan chiqib ketgani uchun ikki marta forfeit
    qilinmaydi va reyting ikki marta qo'llanmaydi.

    2-3-band orasida `await` YO'Q — event loop bu oraliqda boshqa coroutine'ni
    (masalan o'yinchining qayta ulanishini) ishga tushira olmaydi.

    Returns: True — forfeit qo'llandi."""

    if game.finished:
        return False

    async with get_game_finish_lock(room_id):

        if game.finished or not game.forfeit_is_due(player_id):
            return False

        plan = game.plan_forfeit(player_id)
        if not plan.get("ok") or plan.get("empty") or plan.get("winner") is not None:
            # Bu yo'l faqat "o'yin davom etadi" holati uchun. G'olibli/bo'sh
            # holatlar finish_game()/cancel_game() orqali yuradi.
            return False

        try:
            _persist_midgame_forfeit(player_id, plan["remaining"])
        except Exception:
            logger.exception(
                "forfeit DB yozuvi muvaffaqiyatsiz room=%s player=%s "
                "(RAM o'zgarmadi, qayta uriniladi)",
                room_id,
                player_id,
            )
            return False

        _sync_forfeit_to_ram(game, player_id)

    await broadcast_player_forfeited(room_id, player_id)

    try:
        await manager.broadcast_state(room_id, game)
    except Exception:
        logger.exception(
            "broadcast_state qilinmadi room=%s player=%s",
            room_id,
            player_id,
        )

    return True
