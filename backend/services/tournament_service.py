"""
backend/services/tournament_service.py
"""
import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from models.room import Room, RoomStatus, RoomPlayer
from models.tournament import (
    Tournament,
    TournamentPlayer,
    TournamentPlayerStatus,
    TournamentRound,
    TournamentMatch,
    TournamentStatus,
    TournamentRoundStatus,
)
from models.user import User
from services import room_service, abuse_service
from services.rating_service import apply_tournament_reward

logger = logging.getLogger(__name__)

REGISTRATION_SECONDS = 60
MIN_TOURNAMENT_PLAYERS = 2
IDEAL_MATCH_SIZE = 4
REWARD_PER_PARTICIPANT = 5

# ==========================================================
# Concurrency: har bir tournament uchun alohida lock.
#
# MUHIM CHEKLOV: bu threading.Lock (asyncio.Lock emas), chunki
# tournament_service funksiyalari HAM sync REST endpointlardan (FastAPI
# ularni threadpool'da ishga tushiradi), HAM async WebSocket/finish.py
# kodidan (asyncio event loop ichida, sync chaqiruv sifatida) chaqiriladi.
# asyncio.Lock faqat bitta event loop ichida ishlaydi va threadpool bilan
# aralashmaydi — shuning uchun threading.Lock tanlandi.
#
# Amaliy ta'siri: agar bitta tournament uchun lock band bo'lsa, uni band
# qilgan tomon operatsiyani tugatguncha chaqiruvchi thread bloklanadi. Bu
# operatsiyalar (DB yozish, xona yaratish) qisqa va tez tugaydi, shuning
# uchun bu loyihaning ko'lami uchun oqilona kelishuv — lekin юк baland
# concurrency talab qilinadigan katta tizimda buni Postgres advisory lock
# yoki Redis lock bilan almashtirish kerak bo'lardi.
# ==========================================================
_tournament_locks: dict[int, threading.Lock] = {}
_tournament_locks_meta_lock = threading.Lock()


def _get_tournament_lock(tournament_id: int) -> threading.Lock:
    with _tournament_locks_meta_lock:
        lock = _tournament_locks.get(tournament_id)
        if lock is None:
            lock = threading.Lock()
            _tournament_locks[tournament_id] = lock
        return lock


def _get_tournament_or_404(db: Session, tournament_id: int) -> Tournament:
    tournament = (
        db.query(Tournament)
        .options(
            joinedload(Tournament.players),
            joinedload(Tournament.rounds).joinedload(TournamentRound.matches),
        )
        .filter(Tournament.id == tournament_id)
        .first()
    )
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turnir topilmadi")
    return tournament


def _get_user_or_404(db: Session, telegram_id: int) -> User:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foydalanuvchi topilmadi")
    return user


def _generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _tournament_to_dict(tournament: Tournament) -> dict:
    db = Session.object_session(tournament)

    all_room_ids = [
        m.room_id
        for r in tournament.rounds
        for m in r.matches
    ]

    players_by_room_id: dict[int, list[int]] = {}
    if all_room_ids and db is not None:
        rooms = (
            db.query(Room)
            .options(joinedload(Room.players).joinedload(RoomPlayer.user))
            .filter(Room.id.in_(all_room_ids))
            .all()
        )
        for room in rooms:
            players_by_room_id[room.id] = [p.user.telegram_id for p in room.players]

    return {
        "id": tournament.id,
        "creator_telegram_id": tournament.creator_telegram_id,
        "status": tournament.status.value,
        "registration_started_at": tournament.registration_started_at.isoformat() if tournament.registration_started_at else None,
        "registration_expires_at": tournament.registration_expires_at.isoformat() if tournament.registration_expires_at else None,
        "started_at": tournament.started_at.isoformat() if tournament.started_at else None,
        "finished_at": tournament.finished_at.isoformat() if tournament.finished_at else None,
        "current_round": tournament.current_round,
        "participant_count": tournament.participant_count,
        "winner_telegram_id": tournament.winner_telegram_id,
        "reward_points": tournament.reward_points,
        "created_at": tournament.created_at.isoformat() if tournament.created_at else None,
        "players": [
            {
                "telegram_id": p.telegram_id,
                "status": p.status.value,
                "ready": p.ready,
                "joined_at": p.joined_at.isoformat() if p.joined_at else None,
                "eliminated_at": p.eliminated_at.isoformat() if p.eliminated_at else None,
                "eliminated_round": p.eliminated_round,
                "final_position": p.final_position,
            }
            for p in tournament.players
        ],
        "rounds": [
            {
                "id": r.id,
                "round_number": r.round_number,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "matches": [
                    {
                        "id": m.id,
                        "round_id": m.round_id,
                        "room_id": m.room_id,
                        "status": m.status.value,
                        "winner_telegram_id": m.winner_telegram_id,
                        "started_at": m.started_at.isoformat() if m.started_at else None,
                        "finished_at": m.finished_at.isoformat() if m.finished_at else None,
                        "player_telegram_ids": players_by_room_id.get(m.room_id, []),
                    }
                    for m in r.matches
                ],
            }
            for r in tournament.rounds
        ],
    }


def _group_players(player_ids: List[int]) -> List[List[int]]:
    """n >= 2 deb taxmin qilinadi (chaqiruvchi tomon buni tekshiradi)."""
    n = len(player_ids)
    k = (n + IDEAL_MATCH_SIZE - 1) // IDEAL_MATCH_SIZE
    base = n // k
    rem = n % k
    groups = []
    idx = 0
    for i in range(k):
        size = base + (1 if i < rem else 0)
        groups.append(player_ids[idx:idx + size])
        idx += size
    return groups


def _eliminate_players(db: Session, tournament: Tournament, telegram_ids: list[int], round_number: int, reason: str) -> None:
    if not telegram_ids:
        return
    now = _utc_now()
    id_set = set(telegram_ids)
    for p in tournament.players:
        if p.telegram_id in id_set and p.status == TournamentPlayerStatus.ACTIVE:
            p.status = TournamentPlayerStatus.ELIMINATED
            p.eliminated_round = round_number
            p.eliminated_at = now
    logger.info(
        "Tournament %s: %s sababli eliminatsiya qilindi (round=%s): %s",
        tournament.id, reason, round_number, telegram_ids,
    )


# ================= CREATE =================

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


# ================= JOIN =================

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
        if _utc_now() >= tournament.registration_expires_at:
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
    """REST qatlami uchun qulay wrapper — bir xil imzo, faqat nomi orqali
    'token bilan qo'shilish' ekanligini aniqroq ko'rsatadi. Ichida
    join_tournament() ni chaqiradi, duplicate logika yo'q."""
    return join_tournament(db, tournament_id, telegram_id, invite_token)


# ================= LEAVE =================

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


# ================= READY =================

def mark_ready(db: Session, tournament_id: int, telegram_id: int, ready: bool) -> dict:
    tournament = _get_tournament_or_404(db, tournament_id)
    if tournament.status != TournamentStatus.REGISTRATION:
        raise HTTPException(status_code=400, detail="Turnir hozir ro'yxatdan o'tish bosqichida emas")
    player = next((p for p in tournament.players if p.telegram_id == telegram_id), None)
    if player is None:
        raise HTTPException(status_code=400, detail="Siz bu turnirda emassiz")
    player.ready = ready
    db.commit()
    return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))


# ================= GET =================

def get_tournament(db: Session, tournament_id: int) -> dict:
    return _tournament_to_dict(_get_tournament_or_404(db, tournament_id))


# ================= CANCEL =================

def cancel_tournament(db: Session, tournament_id: int, telegram_id: int) -> dict:
    with _get_tournament_lock(tournament_id):
        tournament = _get_tournament_or_404(db, tournament_id)
        if tournament.creator_telegram_id != telegram_id:
            raise HTTPException(status_code=403, detail="Faqat turnir yaratuvchisi bekor qila oladi")
        if tournament.status == TournamentStatus.FINISHED:
            raise HTTPException(status_code=400, detail="Tugagan turnirni bekor qilib bo'lmaydi")
        if tournament.status == TournamentStatus.CANCELLED:
            raise HTTPException(status_code=400, detail="Turnir allaqachon bekor qilingan")

        was_in_progress = tournament.status == TournamentStatus.IN_PROGRESS
        tournament.status = TournamentStatus.CANCELLED
        db.commit()

        if was_in_progress:
            # Faol (hali FINISHED bo'lmagan) matchlarni ham yakunlab qo'yamiz —
            # aks holda ular DB'da abadiy PLAYING holida osilib qoladi va
            # disconnect_watcher ularni tekshirishda davom etaveradi.
            _cancel_active_matches_for_tournament(db, tournament.id)

        return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))


def _cancel_active_matches_for_tournament(db: Session, tournament_id: int) -> None:
    """Tournament CANCELLED bo'lganda, hali tugamagan matchlarni FINISHED
    (g'olibsiz) deb belgilaydi. E'TIBOR: bu funksiya faqat DB yozuvini
    yopadi — haqiqiy GameEngine/Room hali xotirada faol bo'lishi mumkin.
    Xonalarni WS orqali majburiy yopish (hozircha) amalga oshirilmagan —
    o'yinchilar match'ni tabiiy tarzda tugatishi yoki disconnect_watcher
    ularni forfeit qilishi bilan Room.status barfibir FINISHED bo'ladi.
    Bu yerda faqat TournamentMatch/TournamentRound yozuvlari "osilib
    qolmasligi" ta'minlanadi."""
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
    db.commit()


# ================= START =================

def start_tournament(db: Session, tournament_id: int) -> dict:
    with _get_tournament_lock(tournament_id):
        tournament = _get_tournament_or_404(db, tournament_id)
        if tournament.status != TournamentStatus.REGISTRATION:
            raise HTTPException(status_code=400, detail="Turnir allaqachon boshlangan yoki yakunlangan")

        not_ready = [p for p in tournament.players if not p.ready]
        for p in not_ready:
            db.delete(p)
            tournament.participant_count -= 1

        db.flush()
        active_players = [p for p in tournament.players if p.status == TournamentPlayerStatus.ACTIVE and p.ready]

        if len(active_players) < MIN_TOURNAMENT_PLAYERS:
            tournament.status = TournamentStatus.CANCELLED
            db.commit()
            logger.info(
                "Tournament %s CANCELLED: yetarli tayyor o'yinchi yo'q (%d)",
                tournament.id, len(active_players),
            )
            return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))

        tournament.status = TournamentStatus.IN_PROGRESS
        tournament.started_at = _utc_now()
        tournament.current_round = 1
        db.commit()

    # create_round o'zining ichida qayta lock oladi — shuning uchun
    # tashqi `with` blokidan chiqqandan keyin chaqiramiz (bir xil
    # threading.Lock qayta-qayta (re-entrant emas) olinmasligi uchun).
    create_round(db, tournament_id, 1)
    return _tournament_to_dict(_get_tournament_or_404(db, tournament_id))


# ================= ROUND / MATCH =================

def create_round(db: Session, tournament_id: int, round_number: int) -> dict:
    with _get_tournament_lock(tournament_id):
        tournament = _get_tournament_or_404(db, tournament_id)
        if tournament.status != TournamentStatus.IN_PROGRESS:
            raise HTTPException(status_code=400, detail="Turnir faol emas")

        active_players = [p.telegram_id for p in tournament.players if p.status == TournamentPlayerStatus.ACTIVE]

        # 1-QADAM: bloklangan (abuse-lock) o'yinchilarni GURUHLASHDAN OLDIN
        # aniqlab, eliminatsiya qilamiz — shu bilan "guruh yaratildi-yu,
        # ichidagi biror o'yinchi kira olmadi" holati BUTUNLAY oldi olinadi.
        locked_out = [tid for tid in active_players if abuse_service.check_lock(db, tid)["locked"]]
        eligible = [tid for tid in active_players if tid not in locked_out]

        if locked_out:
            _eliminate_players(db, tournament, locked_out, round_number, reason="bloklangan")
            db.flush()

        # 2-QADAM: chekka holatlar.
        if len(eligible) == 0:
            tournament.status = TournamentStatus.CANCELLED
            db.commit()
            logger.warning(
                "Tournament %s CANCELLED: round %s uchun faol o'yinchi qolmadi",
                tournament.id, round_number,
            )
            return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))

        if len(eligible) == 1:
            db.commit()
            return finish_tournament(db, tournament_id, eligible[0])

        # 3-QADAM: oddiy holat — guruhlash va matchlar yaratish.
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
            # create_tournament_match_room o'z ichida yana check_lock qiladi
            # (himoya qatlami sifatida), lekin yuqorida allaqachon filtrlangani
            # uchun bu yerda odatda hech kim qaytarilmasligi kerak.
            room, still_locked_out = room_service.create_tournament_match_room(db, group)

            if still_locked_out:
                # Nazariy jihatdan bo'lmasligi kerak (yuqorida filtrlandi),
                # lekin himoya sifatida: agar shunday holat yuz bersa ham,
                # bu o'yinchilarni ham eliminatsiya qilamiz, jim qoldirmaymiz.
                _eliminate_players(db, tournament, still_locked_out, round_number, reason="bloklangan (matchda)")

            match = TournamentMatch(
                round_id=round_obj.id,
                room_id=room.id,
                status=RoomStatus.PLAYING,
                started_at=_utc_now(),
                finished_at=None,
            )
            db.add(match)

        round_obj.status = TournamentRoundStatus.IN_PROGRESS
        db.commit()
        return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))


def handle_tournament_match_finished(db: Session, room_id: int, winner_telegram_id: int) -> None:
    """Turnir xonasi (haqiqiy g'olib bilan) yakunlanganda chaqiriladi.
    finish.py'ning finish_game() ichidan chaqiriladi."""
    match = db.query(TournamentMatch).filter(TournamentMatch.room_id == room_id).first()
    if match is None:
        return  # normal (tournamentga aloqasi bo'lmagan) xona

    tournament_id = match.round.tournament_id

    with _get_tournament_lock(tournament_id):
        # Lock ichida qayta yuklaymiz — boshqa thread bir vaqtda shu matchni
        # allaqachon yakunlagan bo'lishi mumkin.
        db.refresh(match)
        if match.status == RoomStatus.FINISHED:
            return

        match.winner_telegram_id = winner_telegram_id
        match.status = RoomStatus.FINISHED
        match.finished_at = _utc_now()
        db.flush()

        _maybe_advance_after_match(db, match)


def handle_tournament_match_abandoned(db: Session, room_id: int) -> None:
    """Turnir xonasi G'OLIBSIZ yakunlanganda chaqiriladi (masalan, barcha
    o'yinchilar disconnect bo'lib forfeit qilindi va xona bo'shab qoldi).
    finish.py'ning cancel_game() ichidan chaqiriladi.

    Bu match uchun hech kim keyingi roundga o'tmaydi — bu tournament
    tuzilishida kamdan-kam, lekin mumkin bo'lgan holat."""
    match = db.query(TournamentMatch).filter(TournamentMatch.room_id == room_id).first()
    if match is None:
        return

    tournament_id = match.round.tournament_id

    with _get_tournament_lock(tournament_id):
        db.refresh(match)
        if match.status == RoomStatus.FINISHED:
            return

        match.winner_telegram_id = None
        match.status = RoomStatus.FINISHED
        match.finished_at = _utc_now()
        db.flush()

        logger.warning(
            "Tournament match room=%s g'olibsiz yakunlandi (abandoned)", room_id,
        )

        _maybe_advance_after_match(db, match)


def _maybe_advance_after_match(db: Session, match: TournamentMatch) -> None:
    """LOCK ICHIDA chaqirilishi shart. Round barcha matchlari tugaganmi
    tekshiradi, agar shunday bo'lsa keyingi bosqichga o'tadi."""
    round_obj = match.round
    db.refresh(round_obj)

    if not all(m.status == RoomStatus.FINISHED for m in round_obj.matches):
        return  # hali boshqa matchlar davom etyapti

    round_obj.status = TournamentRoundStatus.FINISHED
    round_obj.finished_at = _utc_now()

    tournament = round_obj.tournament
    winners = [m.winner_telegram_id for m in round_obj.matches if m.winner_telegram_id]

    if len(winners) == 0:
        # Hamma match g'olibsiz tugadi (juda kamdan-kam, masalan hammasi
        # abandoned bo'lsa) — tournament davom eta olmaydi.
        tournament.status = TournamentStatus.CANCELLED
        db.commit()
        logger.warning(
            "Tournament %s CANCELLED: round %s da hech qanday g'olib chiqmadi",
            tournament.id, round_obj.round_number,
        )
        return

    db.commit()

    if len(winners) == 1:
        finish_tournament(db, tournament.id, winners[0])
    else:
        advance_round(db, tournament.id, winners)


def advance_round(db: Session, tournament_id: int, winners: List[int]) -> dict:
    tournament = _get_tournament_or_404(db, tournament_id)
    if tournament.status != TournamentStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Turnir faol emas")

    current_round = tournament.current_round
    winners_set = set(winners)
    for p in tournament.players:
        if p.status != TournamentPlayerStatus.ACTIVE:
            continue  # allaqachon eliminatsiya qilingan (masalan lock sababli)
        if p.telegram_id not in winners_set:
            p.status = TournamentPlayerStatus.ELIMINATED
            p.eliminated_round = current_round
            p.eliminated_at = _utc_now()

    next_round_number = current_round + 1
    tournament.current_round = next_round_number
    db.commit()

    create_round(db, tournament.id, next_round_number)
    return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))


def finish_tournament(db: Session, tournament_id: int, winner_telegram_id: int) -> dict:
    tournament = _get_tournament_or_404(db, tournament_id)
    if tournament.status == TournamentStatus.FINISHED:
        raise HTTPException(status_code=400, detail="Turnir allaqachon yakunlangan")

    tournament.status = TournamentStatus.FINISHED
    tournament.finished_at = _utc_now()
    tournament.winner_telegram_id = winner_telegram_id
    reward_points = tournament.participant_count * REWARD_PER_PARTICIPANT
    tournament.reward_points = reward_points

    winner_player = next((p for p in tournament.players if p.telegram_id == winner_telegram_id), None)
    if winner_player:
        winner_player.status = TournamentPlayerStatus.WINNER
        winner_player.final_position = 1

    db.commit()

    # Reward alohida, tayyor rating_service funksiyasi orqali beriladi —
    # shu funksiya faqat SHU tranzaksiyada bir marta chaqirilgani uchun
    # double-reward xavfi yo'q (finish_tournament o'zi ikki marta
    # chaqirilmasligi status==FINISHED tekshiruvi orqali kafolatlangan).
    apply_tournament_reward(db, winner_telegram_id, reward_points)

    logger.info(
        "Tournament %s FINISHED: winner=%s reward=%d",
        tournament.id, winner_telegram_id, reward_points,
    )

    return _tournament_to_dict(_get_tournament_or_404(db, tournament.id))