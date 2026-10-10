import logging
import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from models.room import Room, RoomStatus, RoomPlayer
from models.tournament import (
    Tournament,
    TournamentMatch,
    TournamentPlayer,
    TournamentPlayerStatus,
    TournamentRound,
    TournamentRoundStatus,
    TournamentStatus,
)
from models.user import User
from services import abuse_service, room_service
from services.rating_service import apply_tournament_reward
from services.tournament.locks import _get_tournament_lock
from services.tournament.rules import _eliminate_players, _group_players
from services.tournament.serializers import _tournament_to_dict
from services.tournament.utils import _as_aware_utc, _generate_invite_token, _hash_token, _utc_now
from services.tournament.validators import (
    _get_tournament_for_update,
    _get_tournament_or_404,
    _get_user_or_404,
)

logger = logging.getLogger(__name__)

REGISTRATION_SECONDS = 60
MIN_TOURNAMENT_PLAYERS = 2
IDEAL_MATCH_SIZE = 4
REWARD_PER_PARTICIPANT = 5


def create_tournament(db: Session, creator_telegram_id: int) -> dict:
    _get_user_or_404(db, creator_telegram_id)

    lock = abuse_service.check_lock(db, creator_telegram_id)
    if lock["locked"]:
        detail = (
            "Siz qora ro'yxatga tushirilgansiz va turnir yarata olmaysiz."
            if lock.get("blacklisted")
            else f"Siz vaqtincha bloklangansiz. {lock['until'].isoformat()} gacha kuting."
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    now = _utc_now()
    invite_token = _generate_invite_token()

    tournament = Tournament(
        creator_telegram_id=creator_telegram_id,
        invite_token_hash=_hash_token(invite_token),
        status=TournamentStatus.REGISTRATION,
        registration_started_at=now,
        registration_expires_at=now + timedelta(seconds=REGISTRATION_SECONDS),
        started_at=None,
        finished_at=None,
        current_round=0,
        participant_count=1,
        winner_telegram_id=None,
        reward_points=0,
        created_at=now,
    )
    db.add(tournament)
    db.flush()

    creator_player = TournamentPlayer(
        tournament_id=tournament.id,
        telegram_id=creator_telegram_id,
        status=TournamentPlayerStatus.ACTIVE,
        ready=False,
        joined_at=now,
    )
    db.add(creator_player)
    db.commit()

    tournament = _get_tournament_or_404(db, tournament.id)
    result = _tournament_to_dict(tournament)
    result["invite_token"] = invite_token
    logger.info("Tournament created: id=%s creator=%s", tournament.id, creator_telegram_id)
    return result


def join_tournament(db: Session, tournament_id: int, telegram_id: int, invite_token: str) -> dict:
    with _get_tournament_lock(tournament_id):
        tournament = _get_tournament_or_404(db, tournament_id)
        _get_user_or_404(db, telegram_id)

        lock = abuse_service.check_lock(db, telegram_id)
        if lock["locked"]:
            detail = (
                "Siz qora ro'yxatga tushirilgansiz va turnirga qo'shila olmaysiz."
                if lock.get("blacklisted")
                else f"Siz vaqtincha bloklangansiz. {lock['until'].isoformat()} gacha kuting."
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

        if not invite_token:
            raise HTTPException(status_code=403, detail="Taklif havolasi mavjud emas")
        if not secrets.compare_digest(_hash_token(invite_token), tournament.invite_token_hash):
            raise HTTPException(status_code=403, detail="Noto'g'ri taklif havolasi")

        if tournament.status != TournamentStatus.REGISTRATION:
            raise HTTPException(status_code=400, detail="Turnirga qo'shilish yopiq")

        expires_at = _as_aware_utc(tournament.registration_expires_at)
        if expires_at is not None and _utc_now() >= expires_at:
            raise HTTPException(status_code=400, detail="Ro'yxatdan o'tish vaqti tugagan")

        active_elsewhere = (
            db.query(TournamentPlayer)
            .join(Tournament)
            .filter(
                TournamentPlayer.telegram_id == telegram_id,
                TournamentPlayer.tournament_id != tournament_id,
                Tournament.status.in_([TournamentStatus.REGISTRATION, TournamentStatus.IN_PROGRESS]),
            )
            .first()
        )
        if active_elsewhere is not None:
            raise HTTPException(
                status_code=400,
                detail="Siz allaqachon boshqa faol turnirda ishtirok etyapsiz",
            )

        existing = next((p for p in tournament.players if p.telegram_id == telegram_id), None)
        if existing:
            raise HTTPException(status_code=400, detail="Siz allaqachon turnirdasiz")

        player = TournamentPlayer(
            tournament_id=tournament.id,
            telegram_id=telegram_id,
            status=TournamentPlayerStatus.ACTIVE,
            ready=False,
            joined_at=_utc_now(),
        )
        db.add(player)
        tournament.participant_count += 1
        db.commit()

        tournament = _get_tournament_or_404(db, tournament.id)
        return _tournament_to_dict(tournament)


def join_tournament_by_token(db: Session, tournament_id: int, telegram_id: int, invite_token: str) -> dict:
    """Wrapper for token-based join."""
    return join_tournament(db, tournament_id, telegram_id, invite_token)


def leave_tournament(db: Session, tournament_id: int, telegram_id: int) -> dict:
    with _get_tournament_lock(tournament_id):
        tournament = _get_tournament_or_404(db, tournament_id)
        if tournament.status != TournamentStatus.REGISTRATION:
            raise HTTPException(status_code=400, detail="Turnir boshlangach chiqib bo'lmaydi")
        player = next((p for p in tournament.players if p.telegram_id == telegram_id), None)
        if player is None:
            raise HTTPException(status_code=400, detail="Siz bu turnirda emassiz")
        db.delete(player)
        tournament.participant_count = max(0, tournament.participant_count - 1)
        db.commit()
        return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))


def mark_ready(db: Session, tournament_id: int, telegram_id: int, ready: bool) -> dict:
    # MUHIM (tuzatildi): boshqa barcha holat-o'zgartiruvchi funksiyalar kabi
    # (join/leave/cancel/start/create_round) bu yerda ham tournament lock
    # olinadi. Avval bu yo'q edi — start_tournament() aynan shu paytda
    # tournament.players ro'yxatini o'qib, "ready bo'lmaganlarni" o'chirib
    # tashlayotgan bo'lsa, mana shu funksiya ORASIDA (lock'siz) chaqirilib,
    # o'yinchining "ready=True" bosishi yo'qolib ketishi (start_tournament
    # eski, hali "ready=False" bo'lgan holatni o'qib ulgurgani sababli)
    # mumkin edi. Lock endi bu poyga holatini yopadi.
    with _get_tournament_lock(tournament_id):
        tournament = _get_tournament_or_404(db, tournament_id)
        if tournament.status != TournamentStatus.REGISTRATION:
            raise HTTPException(status_code=400, detail="Turnir hozir ro'yxatdan o'tish bosqichida emas")
        player = next((p for p in tournament.players if p.telegram_id == telegram_id), None)
        if player is None:
            raise HTTPException(status_code=400, detail="Siz bu turnirda emassiz")
        player.ready = ready
        db.commit()
        return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))


def get_tournament(db: Session, tournament_id: int) -> dict:
    return _tournament_to_dict(_get_tournament_or_404(db, tournament_id))


def cancel_tournament(db: Session, tournament_id: int, telegram_id: int) -> dict:
    """Turnirni bekor qiladi. Turnir statusi va unga tegishli faol
    match/roundlar BITTA tranzaksiyada o'zgaradi (audit F-06): avval status
    alohida commit bo'lardi, keyin matchlar alohida — oradagi xato
    "turnir CANCELLED, lekin matchlar hali ochiq" holatini qoldirardi."""
    with _get_tournament_lock(tournament_id):
        try:
            tournament = _get_tournament_for_update(db, tournament_id)
            if tournament.creator_telegram_id != telegram_id:
                raise HTTPException(status_code=403, detail="Faqat turnir yaratuvchisi bekor qila oladi")
            if tournament.status == TournamentStatus.FINISHED:
                raise HTTPException(status_code=400, detail="Tugagan turnirni bekor qilib bo'lmaydi")
            if tournament.status == TournamentStatus.CANCELLED:
                raise HTTPException(status_code=400, detail="Turnir allaqachon bekor qilingan")

            was_in_progress = tournament.status == TournamentStatus.IN_PROGRESS
            tournament.status = TournamentStatus.CANCELLED

            if was_in_progress:
                _cancel_active_matches_for_tournament(db, tournament.id)

            db.commit()
        except Exception:
            db.rollback()
            raise

        return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))


def _cancel_active_matches_for_tournament(db: Session, tournament_id: int) -> None:
    """Turnirning tugallanmagan round/matchlarini FINISHED qiladi.

    TRANSACTION QOIDASI (audit F-06): bu funksiya commit QILMAYDI (faqat
    flush) — chaqiruvchi (cancel_tournament) turnir statusi bilan birga
    bitta tranzaksiyada commit qiladi."""
    tournament = _get_tournament_or_404(db, tournament_id)
    now = _utc_now()
    for round_obj in tournament.rounds:
        if round_obj.status == TournamentRoundStatus.FINISHED:
            continue
        for match in round_obj.matches:
            if match.status != RoomStatus.FINISHED:
                match.status = RoomStatus.FINISHED
                match.finished_at = now
        round_obj.status = TournamentRoundStatus.FINISHED
        round_obj.finished_at = now
    db.flush()


def start_tournament(db: Session, tournament_id: int) -> dict:
    """Ro'yxatdan o'tish tugagach turnirni boshlaydi.

    Audit F-06: "status=IN_PROGRESS" va 1-round yaratish BITTA tranzaksiyada.
    Avval status alohida commit bo'lib, keyin create_round() chaqirilardi —
    create_round yiqilsa turnir IN_PROGRESS, lekin round yo'q holatda qolardi."""
    with _get_tournament_lock(tournament_id):
        try:
            tournament = _get_tournament_for_update(db, tournament_id)
            if tournament.status != TournamentStatus.REGISTRATION:
                raise HTTPException(status_code=400, detail="Turnir allaqachon boshlangan yoki yakunlangan")

            not_ready = [p for p in tournament.players if not p.ready]
            for p in not_ready:
                db.delete(p)
                tournament.participant_count -= 1

            db.flush()
            # O'chirilgan (ready bo'lmagan) o'yinchilar `tournament.players`
            # kolleksiyasida qolib ketmasligi uchun uni DB'dan qayta yuklaymiz.
            # (Avval bu commit() orqali bilvosita bajarilardi — endi commit
            # round yaratilgandan KEYIN bo'lgani uchun aniq expire kerak.)
            db.expire(tournament, ["players"])
            active_players = [
                p for p in tournament.players
                if p.status == TournamentPlayerStatus.ACTIVE and p.ready
            ]

            if len(active_players) < MIN_TOURNAMENT_PLAYERS:
                tournament.status = TournamentStatus.CANCELLED
                db.commit()
                logger.info(
                    "Tournament %s CANCELLED: yetarli tayyor o'yinchi yo'q (%d)",
                    tournament.id,
                    len(active_players),
                )
                return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))

            tournament.status = TournamentStatus.IN_PROGRESS
            tournament.started_at = _utc_now()
            tournament.current_round = 1
            db.flush()

            _create_round_in_tx(db, tournament, 1)
            db.commit()
        except Exception:
            db.rollback()
            raise

        return _tournament_to_dict(_get_tournament_or_404(db, tournament_id))


def _create_round_in_tx(db: Session, tournament: Tournament, round_number: int) -> None:
    """Round + match xonalarini yaratadi (yoki turnirni yakunlaydi/bekor qiladi).

    TRANSACTION QOIDASI (audit F-06/F-07): bu funksiya commit QILMAYDI va
    tournament lock'ini O'ZI olmaydi — chaqiruvchi (create_round /
    start_tournament / matches._advance_if_round_complete) lock'ni ushlab
    turishi va oxirida commit qilishi SHART."""
    active_players = [p.telegram_id for p in tournament.players if p.status == TournamentPlayerStatus.ACTIVE]

    locked_out = [tid for tid in active_players if abuse_service.check_lock(db, tid)["locked"]]
    eligible = [tid for tid in active_players if tid not in locked_out]

    if locked_out:
        _eliminate_players(tournament, locked_out, round_number, reason="bloklangan")
        db.flush()

    if len(eligible) == 0:
        tournament.status = TournamentStatus.CANCELLED
        db.flush()
        logger.warning(
            "Tournament %s CANCELLED: round %s uchun faol o'yinchi qolmadi",
            tournament.id,
            round_number,
        )
        return

    if len(eligible) == 1:
        _finish_tournament_in_tx(db, tournament, eligible[0])
        return

    round_obj = TournamentRound(
        tournament_id=tournament.id,
        round_number=round_number,
        status=TournamentRoundStatus.WAITING,
        created_at=_utc_now(),
    )
    db.add(round_obj)
    db.flush()

    groups = _group_players(eligible)

    for group in groups:
        room, still_locked_out = room_service.create_tournament_match_room(db, group)
        if still_locked_out:
            _eliminate_players(tournament, still_locked_out, round_number, reason="bloklangan (matchda)")

        match = TournamentMatch(
            round_id=round_obj.id,
            room_id=room.id,
            status=RoomStatus.PLAYING,
            started_at=_utc_now(),
            finished_at=None,
        )
        db.add(match)

    round_obj.status = TournamentRoundStatus.IN_PROGRESS
    db.flush()


def create_round(db: Session, tournament_id: int, round_number: int) -> dict:
    with _get_tournament_lock(tournament_id):
        try:
            tournament = _get_tournament_for_update(db, tournament_id)
            if tournament.status != TournamentStatus.IN_PROGRESS:
                raise HTTPException(status_code=400, detail="Turnir faol emas")

            _create_round_in_tx(db, tournament, round_number)
            db.commit()
        except Exception:
            db.rollback()
            raise

        return _tournament_to_dict(_get_tournament_or_404(db, tournament_id))


def _advance_round_in_tx(db: Session, tournament: Tournament, winners: list[int]) -> None:
    """Yutmaganlarni eliminatsiya qiladi va keyingi roundni yaratadi.

    TRANSACTION QOIDASI (audit F-06): commit QILMAYDI, lock OLMAYDI —
    chaqiruvchi ikkalasiga ham mas'ul."""
    current_round = tournament.current_round
    winners_set = set(winners)
    for p in tournament.players:
        if p.status != TournamentPlayerStatus.ACTIVE:
            continue
        if p.telegram_id not in winners_set:
            p.status = TournamentPlayerStatus.ELIMINATED
            p.eliminated_round = current_round
            p.eliminated_at = _utc_now()

    next_round_number = current_round + 1
    tournament.current_round = next_round_number
    db.flush()

    _create_round_in_tx(db, tournament, next_round_number)


def advance_round(db: Session, tournament_id: int, winners: list[int]) -> dict:
    """Ommaviy wrapper: eliminatsiya + keyingi round BITTA tranzaksiyada.

    Avval bu funksiya avval current_round'ni commit qilib, keyin create_round()
    ni alohida tranzaksiyada chaqirardi (audit F-06) — oradagi xato
    "round FINISHED, turnir IN_PROGRESS, yangi round yo'q" holatini qoldirardi.

    Lock RLock bo'lgani uchun (locks.py) qayta kirish xavfsiz."""
    with _get_tournament_lock(tournament_id):
        try:
            tournament = _get_tournament_for_update(db, tournament_id)
            if tournament.status != TournamentStatus.IN_PROGRESS:
                raise HTTPException(status_code=400, detail="Turnir faol emas")

            _advance_round_in_tx(db, tournament, winners)
            db.commit()
        except Exception:
            db.rollback()
            raise

        return _tournament_to_dict(_get_tournament_or_404(db, tournament_id))


def _finish_tournament_in_tx(db: Session, tournament: Tournament, winner_telegram_id: int) -> None:
    """Turnirni yakunlaydi va g'olibga reward beradi — commit QILMAYDI.

    Audit F-08/F-15:
      - status FINISHED + g'olib + reward_points + g'olib balansi BITTA
        tranzaksiyada commit bo'ladi (chaqiruvchi commit qiladi). Avval status
        alohida commit bo'lib, reward keyin berilardi — reward yiqilsa
        "FINISHED, lekin reward berilmagan" holati qolardi.
      - Faqat IN_PROGRESS -> FINISHED o'tishiga ruxsat. REGISTRATION va
        CANCELLED turnirni "yakunlab" bo'lmaydi (avval faqat FINISHED
        tekshirilardi).
      - Reward IDEMPOTENT: u faqat shu o'tish ichida beriladi, o'tish esa
        status tekshiruvi (+ chaqiruvchi ushlab turgan lock/DB qatori
        qulfi) tufayli faqat bir marta bajariladi."""
    if tournament.status == TournamentStatus.FINISHED:
        raise HTTPException(status_code=400, detail="Turnir allaqachon yakunlangan")
    if tournament.status != TournamentStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=400,
            detail=f"Turnir '{tournament.status.value}' holatida — uni yakunlab bo'lmaydi",
        )

    winner_player = next((p for p in tournament.players if p.telegram_id == winner_telegram_id), None)
    if winner_player is None:
        raise HTTPException(status_code=400, detail="G'olib shu turnir ishtirokchisi emas")

    reward_points = tournament.participant_count * REWARD_PER_PARTICIPANT

    tournament.status = TournamentStatus.FINISHED
    tournament.finished_at = _utc_now()
    tournament.winner_telegram_id = winner_telegram_id
    tournament.reward_points = reward_points

    winner_player.status = TournamentPlayerStatus.WINNER
    winner_player.final_position = 1

    db.flush()
    apply_tournament_reward(db, winner_telegram_id, reward_points)

    logger.info(
        "Tournament %s FINISHED (commit kutilmoqda): winner=%s reward=%d",
        tournament.id,
        winner_telegram_id,
        reward_points,
    )


def finish_tournament(db: Session, tournament_id: int, winner_telegram_id: int) -> dict:
    """Ommaviy wrapper: turnirni yakunlash + reward BITTA tranzaksiyada."""
    with _get_tournament_lock(tournament_id):
        try:
            tournament = _get_tournament_for_update(db, tournament_id)
            _finish_tournament_in_tx(db, tournament, winner_telegram_id)
            db.commit()
        except Exception:
            db.rollback()
            raise

        return _tournament_to_dict(_get_tournament_or_404(db, tournament_id))
