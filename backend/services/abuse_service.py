"""
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
    db.commit()

    count = _count_recent_disconnects(db, telegram_id)
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        return {"count": count, "tier": None}

    user.times_forfeited += 1

    now = datetime.now(timezone.utc)
    tier = None

    if count >= TIER3_THRESHOLD:
        user.is_blacklisted = True
        user.locked_until = now + timedelta(hours=BLACKLIST_LOCK_HOURS)
        tier = "blacklist"
    elif count >= TIER2_THRESHOLD:
        candidate = now + timedelta(hours=TIER2_LOCK_HOURS)
        if user.locked_until is None or candidate > user.locked_until:
            user.locked_until = candidate
        tier = "tier2"
    elif count >= TIER1_THRESHOLD:
        candidate = now + timedelta(minutes=TIER1_LOCK_MINUTES)
        if user.locked_until is None or candidate > user.locked_until:
            user.locked_until = candidate
        tier = "tier1"

    db.commit()
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
    if user.locked_until is not None and user.locked_until > now:
        return {"locked": True, "until": user.locked_until, "blacklisted": user.is_blacklisted}

    return {"locked": False}