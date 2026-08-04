import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import jwt

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60  # Telegram tavsiyasi bo'yicha 24 soat


def validate_init_data(init_data: str) -> dict | None:
    """Telegram initData ni HMAC orqali tekshiradi va parse qilingan dict qaytaradi."""
    if not init_data:
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(parsed.items())
        )

        secret_key = hmac.new(
            key=b"WebAppData",
            msg=settings.BOT_TOKEN.encode(),
            digestmod=hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        # YANGI: auth_date yangiligini tekshirish — eski initData'ni
        # qayta-qayta ishlatib (replay) session olishning oldini oladi
        auth_date_raw = parsed.get("auth_date")
        if not auth_date_raw:
            return None
        try:
            auth_date = datetime.fromtimestamp(int(auth_date_raw), tz=timezone.utc)
        except (TypeError, ValueError):
            return None

        if datetime.now(timezone.utc) - auth_date > timedelta(seconds=MAX_INIT_DATA_AGE_SECONDS):
            logger.info("initData rad etildi: auth_date juda eski.")
            return None

        return parsed
    except Exception:
        logger.exception("initData tekshirishda xatolik yuz berdi.")
        return None


def create_session_token(telegram_id: int) -> str:
    """Foydalanuvchi uchun JWT session token yaratadi."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(telegram_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_session_token(token: str) -> dict | None:
    """JWT tokenni tekshiradi va payloadni qaytaradi, xato bo'lsa None."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        logger.info("Yaroqsiz yoki muddati o'tgan token.")
        return None