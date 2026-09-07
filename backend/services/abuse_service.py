"""
backend/services/abuse_service.py 
Stage 14 — uzilishni suiiste'mol qilishning oldini olish.

Qoida: faqat forfeit'gacha borgan uzilishlar sanaladi (grace period ichida
qaytib ulangan oddiy internet uzilishi hisobga olinmaydi — aks holda
interneti yomon odamlar bekorga jazolanadi). Oxirgi 1 soat (sliding window)
ichida nechta forfeit bo'lgani sanaladi.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models.disconnect_log import DisconnectLog
from models.user import User

WINDOW_HOURS = 1

TIER1_THRESHOLD = 3
TIER1_LOCK_MINUTES = 10

TIER2_THRESHOLD = 6
TIER2_LOCK_HOURS = 4

TIER3_THRESHOLD = 15  # qora ro'yxat — siz aytgan 10-20 oralig'idagi boshlang'ich qiymat
BLACKLIST_LOCK_HOURS = 24 * 14  # amalda "qo'lda ochilguncha" ga yaqin


def _normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _count_recent_disconnects(db: Session, telegram_id: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    return (
        db.query(DisconnectLog)
        .filter(DisconnectLog.telegram_id == telegram_id, DisconnectLog.occurred_at >= since)
        .count()
    )


def record_forfeit_disconnect(db: Session, telegram_id: int) -> dict:
    """Har bir forfeit sodir bo'lganda chaqiriladi (routes/game.py'dagi
    disconnect_watcher'dan). Yangi log yozadi, so'ng zinapoyaga qarab
    User'ni bloklaydi."""
    db.add(DisconnectLog(telegram_id=telegram_id))

    count = _count_recent_disconnects(db, telegram_id)
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        return {"count": count, "tier": None}

    user.times_forfeited += 1

    now = datetime.now(timezone.utc)
    tier = None

    if count >= TIER3_THRESHOLD:
        # Xato: qora ro'yxat bosqichida eski, uzunroq lock ni qisqartirish
        # mumkin edi; eng katta kandidatni saqlab qolish xavfsizroq.
        user.is_blacklisted = True
        candidate = now + timedelta(hours=BLACKLIST_LOCK_HOURS)
        existing = _normalize_utc(user.locked_until)
        if existing is None or candidate > existing:
            user.locked_until = candidate
        tier = "blacklist"
    elif count >= TIER2_THRESHOLD:
        # Xato: tier2/3 yoxud boshqa avvalgi lockni qayta yozib yuborishi
        # mumkin; uzunroq lock saqlanib qolishi kerak.
        candidate = now + timedelta(hours=TIER2_LOCK_HOURS)
        existing = _normalize_utc(user.locked_until)
        if existing is None or candidate > existing:
            user.locked_until = candidate
        tier = "tier2"
    elif count >= TIER1_THRESHOLD:
        # Xato: tier1 uchun ham oldingi aylanma lockni bir xil mezon bilan
        # taqqoslash kerak, aks holda zaifroq bloklash ishlaydi.
        candidate = now + timedelta(minutes=TIER1_LOCK_MINUTES)
        existing = _normalize_utc(user.locked_until)
        if existing is None or candidate > existing:
            user.locked_until = candidate
        tier = "tier1"

    return {
        "count": count,
        "tier": tier,
        "locked_until": user.locked_until,
        "is_blacklisted": user.is_blacklisted,
    }


def check_lock(db: Session, telegram_id: int) -> dict:
    """Xona yaratish/qo'shilishdan oldin chaqiriladi."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        return {"locked": False}

    now = datetime.now(timezone.utc)
    locked_until = _normalize_utc(user.locked_until)

    # Xato: DBdan o'qilgan locked_until naive bo'lsa, UTC bilan solishtirish
    # xatolikka olib keladi; normalizatsiya qilish kerak.
    if user.is_blacklisted:
        # Xato: qora ro'yxatdagi foydalanuvchi lock muddati tugagandan keyin ham
        # blokdan chiqib ketishi mumkin; is_blacklisted ko'rsatkichi ustunlikka ega.
        return {"locked": True, "until": locked_until, "blacklisted": True}

    if locked_until is not None and locked_until > now:
        return {"locked": True, "until": locked_until, "blacklisted": user.is_blacklisted}

    return {"locked": False, "blacklisted": user.is_blacklisted, "until": locked_until}