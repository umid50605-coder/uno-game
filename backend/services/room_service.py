import logging
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from models.room import Room, RoomPlayer, RoomStatus, generate_room_code
from models.schemas import LeaveRoomResponse, RoomOut, RoomPlayerOut
from models.user import User
from services import abuse_service

logger = logging.getLogger(__name__)

MIN_PLAYERS_TO_START = 2
WAIT_EXTEND_SECONDS = 60


def _to_room_out(room: Room, host_telegram_id: int | None = None) -> RoomOut:
    """RoomOut yasash. host_telegram_id berilsa, join_code ko'rinadi, aks holda yashiriladi."""
    players_out = [
        RoomPlayerOut(
            user_id=p.user_id,
            telegram_id=p.user.telegram_id,
            first_name=p.user.first_name,
            is_ready=p.is_ready,
        )
        for p in room.players
    ]
    # join_code faqat hostga ko'rinadi
    show_code = None
    if host_telegram_id is not None and room.host.telegram_id == host_telegram_id:
        show_code = room.join_code

    return RoomOut(
        id=room.id,
        code=room.code,
        status=room.status.value,
        max_players=room.max_players,
        players=players_out,
        is_public=room.is_public,
        join_code=show_code,
    )

def _get_user_or_404(db: Session, telegram_id: int) -> User:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foydalanuvchi topilmadi")
    return user


def _get_room_or_404(db: Session, room_id: int) -> Room:
    room = (
        db.query(Room)
        .options(joinedload(Room.players).joinedload(RoomPlayer.user), joinedload(Room.host))
        .filter(Room.id == room_id)
        .first()
    )
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Xona topilmadi")
    return room

def _lock_message(lock: dict) -> str:
    if lock.get("blacklisted"):
        return "Ko'p marta ataylab uzilganingiz aniqlandi — hozircha o'yin o'ynay olmaysiz."
    until = lock["until"]
    remaining = until - datetime.now(timezone.utc)
    minutes = max(1, int(remaining.total_seconds() // 60))
    if minutes >= 60:
        hours = minutes // 60
        return f"Ko'p marta uzilganingiz uchun {hours} soatga bloklangansiz."
    return f"Ko'p marta uzilganingiz uchun {minutes} daqiqaga bloklangansiz."


def create_room(db: Session, host_telegram_id: int, is_public: bool = True, join_code: str | None = None) -> RoomOut:
    lock = abuse_service.check_lock(db, host_telegram_id)
    if lock["locked"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_lock_message(lock))

    host = _get_user_or_404(db, host_telegram_id)

    # Security xona uchun kod majburiy
    if not is_public and not join_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Security xona uchun kod kerak")

    code = generate_room_code()
    while db.query(Room).filter(Room.code == code).first() is not None:
        code = generate_room_code()

    room = Room(
        code=code,
        host_id=host.id,
        is_public=is_public,
        join_code=join_code if not is_public else None,
    )
    db.add(room)
    db.flush()

    room.players.append(RoomPlayer(room_id=room.id, user_id=host.id, is_ready=False))

    db.commit()
    room = _get_room_or_404(db, room.id)

    logger.info("Yangi xona yaratildi: %s (host: %s, public=%s)", room.code, host_telegram_id, is_public)
    return _to_room_out(room, host_telegram_id=host_telegram_id)


def get_room(db: Session, room_id: int, telegram_id: int | None = None) -> RoomOut:
    room = _get_room_or_404(db, room_id)
    return _to_room_out(room, host_telegram_id=telegram_id)


def get_room_player_ids(db: Session, room_id: int) -> list[int]:
    room = _get_room_or_404(db, room_id)
    players = sorted(room.players, key=lambda p: p.joined_at)
    return [p.user.telegram_id for p in players]


def list_open_rooms(db: Session) -> list[RoomOut]:
    rooms = (
        db.query(Room)
        .options(joinedload(Room.players).joinedload(RoomPlayer.user))
        .filter(Room.status == RoomStatus.WAITING, Room.is_public == True)
        .order_by(Room.created_at.desc())
        .all()
    )
    return [_to_room_out(room) for room in rooms]


def search_rooms_by_code(db: Session, code: str) -> list[RoomOut]:
    """Kodga mos xonalarni qaytaradi (security va public)."""
    rooms = (
        db.query(Room)
        .options(joinedload(Room.players).joinedload(RoomPlayer.user))
        .filter(Room.code == code, Room.status == RoomStatus.WAITING)
        .all()
    )
    return [_to_room_out(room) for room in rooms]


def get_random_public_room(db: Session) -> RoomOut:
    import random
    rooms = (
        db.query(Room)
        .options(joinedload(Room.players).joinedload(RoomPlayer.user))
        .filter(Room.status == RoomStatus.WAITING, Room.is_public == True)
        .all()
    )
    if not rooms:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hozircha ochiq xona yo'q")
    room = random.choice(rooms)
    return _to_room_out(room)


def join_room(db: Session, room_id: int, telegram_id: int, join_code: str | None = None) -> RoomOut:
    lock = abuse_service.check_lock(db, telegram_id)
    if lock["locked"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_lock_message(lock))

    room = _get_room_or_404(db, room_id)

    if room.status != RoomStatus.WAITING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Xona endi qo'shilish uchun ochiq emas")

    # Security xonada kodni tekshirish
    if not room.is_public:
        if not join_code or join_code != room.join_code:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Noto'g'ri kod")

    user = _get_user_or_404(db, telegram_id)

    already_in = any(p.user_id == user.id for p in room.players)

    if not already_in:
        if len(room.players) >= room.max_players:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Xona to'lgan")
        db.add(RoomPlayer(room_id=room.id, user_id=user.id, is_ready=False))
        db.commit()

    room = _get_room_or_404(db, room_id)
    return _to_room_out(room, host_telegram_id=telegram_id)


# set_ready, extend_wait, leave_room, cleanup_stale_rooms, finish_room — o'zgarishsiz qoldi (yuqoridagi kodni saqlab qolamiz)
# ... (oldingi kodni qoldiramiz, faqat _to_room_out() endi host_telegram_id ni oladi)

def set_ready(db: Session, room_id: int, telegram_id: int, ready: bool) -> RoomOut:
    room = _get_room_or_404(db, room_id)

    if room.status != RoomStatus.WAITING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Xona endi kutish holatida emas",
        )

    user = _get_user_or_404(db, telegram_id)

    player = next((p for p in room.players if p.user_id == user.id), None)
    if player is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Siz bu xonada emassiz")

    player.is_ready = ready
    db.commit()

    room = _get_room_or_404(db, room_id)

    if (
        len(room.players) >= MIN_PLAYERS_TO_START
        and all(p.is_ready for p in room.players)
    ):
        room.status = RoomStatus.PLAYING
        db.commit()
        room = _get_room_or_404(db, room_id)
        logger.info("Xona %s o'yinni boshladi (barcha o'yinchilar tayyor).", room.code)

    return _to_room_out(room)

def extend_wait(db: Session, room_id: int, telegram_id: int) -> RoomOut:
    room = _get_room_or_404(db, room_id)

    if room.status != RoomStatus.WAITING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Xona endi kutish holatida emas",
        )

    user = _get_user_or_404(db, telegram_id)
    player = next((p for p in room.players if p.user_id == user.id), None)
    if player is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Siz bu xonada emassiz")

    room.wait_deadline = datetime.now(timezone.utc) + timedelta(seconds=WAIT_EXTEND_SECONDS)
    db.commit()

    room = _get_room_or_404(db, room_id)
    logger.info("Xona %s kutish muddati uzaytirildi.", room.code)
    return _to_room_out(room)

def leave_room(db: Session, room_id: int, telegram_id: int) -> LeaveRoomResponse:
    room = _get_room_or_404(db, room_id)

    if room.status != RoomStatus.WAITING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O'yin davomida xonadan chiqib bo'lmaydi",
        )

    user = _get_user_or_404(db, telegram_id)

    player = next((p for p in room.players if p.user_id == user.id), None)
    if player is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Siz bu xonada emassiz")

    was_host = room.host_id == user.id

    db.delete(player)
    db.commit()

    room = _get_room_or_404(db, room_id)

    if len(room.players) == 0:
        room_code = room.code          # o'chirishdan OLDIN saqlab olamiz
        db.delete(room)
        db.commit()
        logger.info("Xona %s bekor qilindi (hamma chiqib ketdi).", room_code)
        return LeaveRoomResponse(deleted=True, room=None)

    if was_host:
        new_host = min(room.players, key=lambda p: p.joined_at)
        room.host_id = new_host.user_id
        db.commit()
        room = _get_room_or_404(db, room_id)
        logger.info("Xona %s da yangi host: user_id=%s", room.code, new_host.user_id)

    return LeaveRoomResponse(deleted=False, room=_to_room_out(room, host_telegram_id=telegram_id))

def cleanup_stale_rooms(db: Session) -> None:
    now = datetime.now(timezone.utc)

    stale_rooms = (
        db.query(Room)
        .options(joinedload(Room.players))
        .filter(Room.status == RoomStatus.WAITING, Room.wait_deadline < now)
        .all()
    )

    for room in stale_rooms:
        ready_players = [p for p in room.players if p.is_ready]
        not_ready_players = [p for p in room.players if not p.is_ready]

        if len(ready_players) >= MIN_PLAYERS_TO_START:
            for p in not_ready_players:
                db.delete(p)
            room.status = RoomStatus.PLAYING
            logger.info(
                "Xona %s: kutish muddati tugadi — %d ta tayyor o'yinchi bilan "
                "avtomatik boshlandi (%d kishi chiqarib yuborildi).",
                room.code, len(ready_players), len(not_ready_players),
            )
        else:
            logger.info(
                "Xona %s avtomatik o'chirildi (kutish muddatida yetarli o'yinchi tayyor bo'lmadi).",
                room.code,
            )
            db.delete(room)

    if stale_rooms:
        db.commit()

def finish_room(db: Session, room_id: int) -> None:
    """O'yin tugagach (game.py'dan, ham oddiy g'alaba, ham forfeit holatida)
    chaqiriladi — xona holatini yakunlangan deb belgilaydi, shunda room.js
    noto'g'ri ravishda qayta o'yinga (arvoh sifatida) qaytarib yubormaydi."""
    room = db.query(Room).filter(Room.id == room_id).first()
    if room is not None and room.status != RoomStatus.FINISHED:
        room.status = RoomStatus.FINISHED
        db.commit()
        logger.info("Xona %s yakunlandi (o'yin tugadi).", room.code)