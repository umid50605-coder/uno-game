"""backend/services/tournament/matches.py

Turnir match natijasi va round -> keyingi bosqich o'tishlari.

TRANSACTION XARITASI (audit F-03/F-06/F-08/F-09):

  T1  (finish.py, o'yin natijasi tranzaksiyasi)
        rating + room FINISHED + record_match_result()   -> BITTA commit
  T2  (shu fayl: handle_tournament_match_*)
        match tekshiruvi -> round FINISHED -> g'oliblar ->
        keyingi round YOKI turnir FINISHED + reward      -> BITTA commit

T1 va T2 ataylab ALOHIDA tranzaksiyalar: haqiqatda o'ynalgan o'yin natijasi
(reyting, room, match g'olibi) turnir logikasidagi xato tufayli hech qachon
yo'qolmasligi kerak. T2 yiqilsa, hech narsa "yarim" commit bo'lmaydi (butun T2
rollback) — round IN_PROGRESS holatida, lekin barcha matchlari FINISHED bo'lib
qoladi. Aynan shu holatni `recover_stalled_rounds()` aniqlaydi va T2'ni
qayta bajaradi (main.py'dagi tournament watcher chaqiradi). T2 idempotent:
qayta bajarilsa ikkinchi marta round/reward yaratmaydi.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import exists
from sqlalchemy.orm import Session

from models.room import RoomStatus
from models.tournament import (
    Tournament,
    TournamentMatch,
    TournamentRound,
    TournamentRoundStatus,
    TournamentStatus,
)
from services.tournament.locks import _get_tournament_lock
from services.tournament.validators import _get_tournament_for_update

logger = logging.getLogger(__name__)

# ESLATMA: `_advance_round_in_tx`/`_finish_tournament_in_tx` (lifecycle.py'dan)
# atayin funksiya ICHIDA import qilinadi, chunki bu ikki modul o'zaro
# kontseptual jihatdan bog'liq — top-level import qilish services/tournament/
# __init__.py'dagi import tartibiga (avval .lifecycle, keyin .matches)
# jimgina bog'liq bo'lib qolardi. _get_tournament_lock esa hech qanday
# tournament ichki modulidan import qilmaydigan "barg" modul bo'lgani uchun
# uni top-level import qilish har qanday tartibda xavfsiz.


def _record_match_result(match: TournamentMatch, winner_telegram_id: int | None) -> bool:
    """Match'ni FINISHED qiladi. Idempotent: match allaqachon FINISHED bo'lsa
    (masalan turnir bekor qilinganda yoki avvalgi urinishda) HECH NARSA
    o'zgartirmaydi va False qaytaradi."""
    if match.status == RoomStatus.FINISHED:
        return False

    match.winner_telegram_id = winner_telegram_id
    match.status = RoomStatus.FINISHED
    match.finished_at = datetime.now(timezone.utc)
    return True


def record_match_result(db: Session, room_id: int, winner_telegram_id: int | None) -> int | None:
    """T1 helper: turnir matchining natijasini yozadi — commit QILMAYDI.

    finish.py o'yin natijasi tranzaksiyasi (reyting + room FINISHED) ICHIDA
    chaqiradi, shunda "o'yin tugadi, lekin match natijasi yo'q" holati
    bo'lmaydi.

    Returns:
        tournament_id — room turnir matchiga tegishli bo'lsa (T2 kerak),
        None          — room hech qaysi turnir matchiga tegishli emas.
    """
    match = (
        db.query(TournamentMatch)
        .filter(TournamentMatch.room_id == room_id)
        .with_for_update()
        .first()
    )
    if match is None:
        return None

    _record_match_result(match, winner_telegram_id)
    db.flush()
    return match.round.tournament_id


def _advance_if_round_complete(db: Session, tournament: Tournament, round_id: int) -> bool:
    """Round'dagi BARCHA matchlar tugagan bo'lsa, o'tishni bajaradi:

        round FINISHED -> g'oliblar -> keyingi round YOKI turnir FINISHED + reward

    LOCK ICHIDA chaqirilishi va chaqiruvchi commit qilishi SHART (bu funksiya
    commit qilmaydi — hamma narsa bitta tranzaksiya).

    IDEMPOTENT: round allaqachon FINISHED bo'lsa, turnir faol bo'lmasa yoki
    hali tugamagan match bo'lsa — hech narsa qilmaydi (False).
    """
    from services.tournament.lifecycle import _advance_round_in_tx, _finish_tournament_in_tx

    if tournament.status != TournamentStatus.IN_PROGRESS:
        return False

    round_obj = (
        db.query(TournamentRound)
        .filter(TournamentRound.id == round_id)
        .populate_existing()
        .first()
    )
    if round_obj is None or round_obj.tournament_id != tournament.id:
        return False
    if round_obj.status == TournamentRoundStatus.FINISHED:
        return False

    matches = (
        db.query(TournamentMatch)
        .filter(TournamentMatch.round_id == round_id)
        .populate_existing()
        .all()
    )
    if not matches or any(m.status != RoomStatus.FINISHED for m in matches):
        return False

    round_obj.status = TournamentRoundStatus.FINISHED
    round_obj.finished_at = datetime.now(timezone.utc)

    winners = [m.winner_telegram_id for m in matches if m.winner_telegram_id]

    if len(winners) == 0:
        tournament.status = TournamentStatus.CANCELLED
        db.flush()
        logger.warning(
            "Tournament %s CANCELLED: round %s da hech qanday g'olib chiqmadi",
            tournament.id,
            round_obj.round_number,
        )
        return True

    if len(winners) == 1:
        _finish_tournament_in_tx(db, tournament, winners[0])
    else:
        _advance_round_in_tx(db, tournament, winners)

    return True


def _complete_transition(db: Session, tournament_id: int, round_id: int) -> bool:
    """T2: lock ostida round o'tishini bajaradi va BITTA commit qiladi.
    Xatoda butun T2 rollback qilinadi va xato qayta ko'tariladi (jim yutilmaydi).

    Returns: o'tish HAQIQATDA bajarildimi (False — allaqachon bajarilgan edi)."""
    with _get_tournament_lock(tournament_id):
        try:
            tournament = _get_tournament_for_update(db, tournament_id)
            transitioned = _advance_if_round_complete(db, tournament, round_id)
            db.commit()
            return transitioned
        except Exception:
            db.rollback()
            raise


def handle_tournament_match_finished(db: Session, room_id: int, winner_telegram_id: int) -> None:
    """Turnir xonasi (haqiqiy g'olib bilan) yakunlanganda chaqiriladi.

    Idempotent: match natijasi T1'da allaqachon yozilgan bo'lsa ham
    (finish.py shunday qiladi), bu funksiya faqat round o'tishini bajaradi.
    Match hali yozilmagan bo'lsa (to'g'ridan-to'g'ri chaqirilganda) uni ham
    yozadi. Boshqa mutatsion natijani O'ZGARTIRMAYDI."""
    _handle_match_result(db, room_id, winner_telegram_id)


def handle_tournament_match_abandoned(db: Session, room_id: int) -> None:
    """Turnir xonasi g'olibsiz yakunlanganda chaqiriladi."""
    logger.warning("Tournament match room=%s g'olibsiz yakunlandi (abandoned)", room_id)
    _handle_match_result(db, room_id, None)


def _handle_match_result(db: Session, room_id: int, winner_telegram_id: int | None) -> None:
    match = db.query(TournamentMatch).filter(TournamentMatch.room_id == room_id).first()
    if match is None:
        return

    tournament_id = match.round.tournament_id
    round_id = match.round_id

    with _get_tournament_lock(tournament_id):
        try:
            tournament = _get_tournament_for_update(db, tournament_id)

            fresh_match = (
                db.query(TournamentMatch)
                .filter(TournamentMatch.room_id == room_id)
                .populate_existing()
                .first()
            )
            if fresh_match is not None:
                _record_match_result(fresh_match, winner_telegram_id)
                db.flush()

            _advance_if_round_complete(db, tournament, round_id)
            db.commit()
        except Exception:
            db.rollback()
            raise


def recover_stalled_rounds(db: Session) -> int:
    """Failure recovery (audit F-09): barcha matchlari FINISHED bo'lgan, lekin
    hali o'tish bajarilmagan (round IN_PROGRESS, turnir IN_PROGRESS) roundlarni
    topib, T2'ni qayta bajaradi.

    Bunday holat T2 (round o'tishi) xato bilan tugaganda yoki server T1 va T2
    orasida to'xtaganda yuzaga keladi. Funksiya idempotent — o'tish allaqachon
    bajarilgan bo'lsa hech narsa qilmaydi. Har bir turnir alohida
    tranzaksiyada qayta ishlanadi: bittasidagi xato qolganlarni to'xtatmaydi.

    Returns: haqiqatda qayta tiklangan (o'tish bajarilgan) roundlar soni.
    """
    stalled = (
        db.query(TournamentRound.id, TournamentRound.tournament_id)
        .join(Tournament, Tournament.id == TournamentRound.tournament_id)
        .filter(
            Tournament.status == TournamentStatus.IN_PROGRESS,
            TournamentRound.status == TournamentRoundStatus.IN_PROGRESS,
            ~exists().where(
                TournamentMatch.round_id == TournamentRound.id,
                TournamentMatch.status != RoomStatus.FINISHED,
            ),
        )
        .all()
    )
    # So'rov natijasi (tuple'lar) session holatidan mustaqil — o'qishdan keyin
    # ochiq tranzaksiyani tugatamiz, keyingi _complete_transition() yangi
    # tranzaksiyada boshlansin.
    pairs = [(row.tournament_id, row.id) for row in stalled]
    db.rollback()

    recovered = 0
    for tournament_id, round_id in pairs:
        try:
            if _complete_transition(db, tournament_id, round_id):
                recovered += 1
                logger.warning(
                    "Tournament %s round %s o'tishi qayta tiklandi (recovery sweep)",
                    tournament_id,
                    round_id,
                )
        except Exception:
            logger.exception(
                "Tournament %s round %s o'tishini qayta tiklashda xato (keyingi siklda yana uriniladi)",
                tournament_id,
                round_id,
            )
    return recovered
