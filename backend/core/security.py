"""
backend/core/security.py
"""
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import jwt
from jwt import (
    DecodeError,
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
)

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60  # 24 soat

# TUZATILDI (MEDIUM — uzoq muddatli JWT WS URL'da oshkor bo'lishi): WS
# ulanish uchun ishlatiladigan ticket'ning amal qilish muddati. Asosiy
# session JWT (JWT_EXPIRE_MINUTES, odatda 1440 daqiqa = 24 soat) endi
# WS URL'ga umuman qo'yilmaydi — faqat shu qisqa muddatli ticket qo'yiladi.
WS_TICKET_EXPIRE_SECONDS = 30


def validate_init_data(init_data: str) -> dict | None:
    """
    Telegram WebApp initData ni tekshiradi.

    HMAC tekshiriladi va auth_date eskirmagan bo'lsa
    parse qilingan ma'lumot qaytariladi.
    """

    if not init_data:
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))

        received_hash = parsed.pop("hash", None)

        if received_hash is None:
            logger.warning("initData hash topilmadi")
            return None

        data_check_string = "\n".join(
            f"{k}={v}"
            for k, v in sorted(parsed.items())
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

        if not hmac.compare_digest(
            calculated_hash,
            received_hash,
        ):
            logger.warning("initData hash noto'g'ri")
            return None

        auth_date_raw = parsed.get("auth_date")

        if auth_date_raw is None:
            logger.warning("auth_date topilmadi")
            return None

        try:
            auth_date = datetime.fromtimestamp(
                int(auth_date_raw),
                tz=timezone.utc,
            )
        except (TypeError, ValueError):
            logger.warning("auth_date noto'g'ri")
            return None

        now = datetime.now(timezone.utc)

        if auth_date > now + timedelta(minutes=5):
            logger.warning("initData auth_date kelajakdan yuborilgan")
            return None

        if now - auth_date > timedelta(
            seconds=MAX_INIT_DATA_AGE_SECONDS
        ):
            logger.info("initData muddati tugagan")
            return None

        return parsed

    except Exception:
        logger.exception("initData tekshirishda xato")
        return None


def _require_jwt_secret() -> str:
    # 4 chi: JWT secret bo'sh bo'lsa, token yaratish xavfsiz bo'lmaydi va
    # konfiguratsiya xatosi yashirincha `jwt.encode()` orqali o'z-o'zidan
    # davom etib ketishi mumkin. Bu holatda xatoni erta qaytarish kerak.
    secret = getattr(settings, "JWT_SECRET", None)
    if not secret:
        raise ValueError("JWT_SECRET not configured")
    return secret


def create_session_token(telegram_id: int) -> str:
    now = datetime.now(timezone.utc)

    timestamp = int(now.timestamp())
    expire_at = int(
        (
            now + timedelta(
                minutes=settings.JWT_EXPIRE_MINUTES
            )
        ).timestamp()
    )

    payload = {
        "sub": str(telegram_id),
        "iat": timestamp,
        "nbf": timestamp,
        "exp": expire_at,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "type": "access",
    }

    secret = _require_jwt_secret()
    return jwt.encode(
        payload,
        secret,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_session_token(token: str) -> dict | None:
    """
    Asosiy (uzoq muddatli) session JWT'ni tekshiradi.

    MUHIM: bu funksiya endi WebSocket auth'da ISHLATILMAYDI — WS uchun
    decode_ws_ticket() ishlatiladi (pastda). Bu funksiya faqat oddiy
    REST so'rovlar (Authorization header orqali) uchun qoladi.

    Xato bo'lsa None qaytaradi.
    """

    try:
        secret = _require_jwt_secret()
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require": [
                    "exp",
                    "iat",
                    "nbf",
                    "iss",
                    "aud",
                    "sub",
                    "type",
                ]
            },
        )

        if payload.get("type") != "access":
            logger.warning("JWT type noto'g'ri")
            return None

        sub = payload.get("sub")
        # 4 chi: JWT ichidagi `sub` maydoni bo'sh yoki int/str bo'lmagan
        # formatda kelishi mumkin; bunday tokenlar foydalanuvchi identifikatori
        # sifatida ishlatilganda xatolikka olib keladi. Ularni rad etamiz.
        if sub is None or str(sub).strip() == "":
            logger.warning("JWT token ichida 'sub' mavjud emas")
            return None
        try:
            int(str(sub))
        except (TypeError, ValueError):
            logger.warning("JWT token ichidagi 'sub' noto'g'ri formatda")
            return None

        return payload

    except ValueError:
        logger.warning("JWT_SECRET konfiguratsiyasi noto'g'ri")

    except ExpiredSignatureError:
        logger.info("JWT muddati tugagan")

    except InvalidSignatureError:
        logger.warning("JWT imzosi noto'g'ri")

    except InvalidAudienceError:
        logger.warning("JWT audience noto'g'ri")

    except InvalidIssuerError:
        logger.warning("JWT issuer noto'g'ri")

    except DecodeError:
        logger.warning("JWT decode xatosi")

    except jwt.PyJWTError:
        logger.warning("JWT xatosi")

    except Exception:
        logger.exception("JWT tekshirishda kutilmagan xato")

    return None


def create_ws_ticket(telegram_id: int) -> str:
    """
    WebSocket ulanishi uchun QISQA MUDDATLI ticket yaratadi.

    TUZATILDI (MEDIUM — uzoq muddatli JWT WS URL'da oshkor bo'lishi):
    Avval /ws/rooms/{id}?token=... va /ws/tournament/{id}?token=...
    to'g'ridan-to'g'ri asosiy session JWT'ni (24 soat amal qiladi) URL
    query-string'ga qo'yardi. Reverse-proxy/CDN loglari odatda to'liq
    URL'ni (query-string bilan birga) yozib boradi — bu 24 soatlik
    amal qiluvchi credential'ni log fayllarida qoldirib ketardi.

    Bu funksiya orqali WS ulanish OLDIDAN, alohida REST so'rov bilan
    (Authorization header orqali, URL'da EMAS) so'ralgan, atigi
    WS_TICKET_EXPIRE_SECONDS soniya amal qiladigan token yaratiladi.
    Shu qisqa muddatli ticket keyin WS URL'ga qo'yiladi — hatto loglarda
    qolib ketsa ham, amal qilish muddati tezda tugagan bo'ladi.
    """
    now = datetime.now(timezone.utc)
    timestamp = int(now.timestamp())
    expire_at = timestamp + WS_TICKET_EXPIRE_SECONDS

    payload = {
        "sub": str(telegram_id),
        "iat": timestamp,
        "nbf": timestamp,
        "exp": expire_at,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "type": "ws_ticket",
    }

    secret = _require_jwt_secret()
    return jwt.encode(
        payload,
        secret,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_ws_ticket(token: str) -> dict | None:
    """
    WS ticket'ni tekshiradi.

    decode_session_token()ga o'xshash, lekin "type" maydoni "ws_ticket"
    bo'lishini talab qiladi — shuning uchun:
      - Oddiy uzoq muddatli session JWT bu yerda HECH QACHON qabul
        qilinmaydi (agar kimdir eski frontend/eski havola orqali asosiy
        tokenni yuborsa, "type" mos kelmagani uchun rad etiladi).
      - Ws ticket, aksincha, oddiy REST endpointlarda (masalan /me)
        ishlamaydi, chunki decode_session_token "type" != "access"
        bo'lsa uni rad etadi.
    Bu ikki token turini bir-biridan qat'iy ajratadi.
    """
    try:
        secret = _require_jwt_secret()
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require": ["exp", "iat", "nbf", "iss", "aud", "sub", "type"],
            },
        )

        if payload.get("type") != "ws_ticket":
            logger.warning("WS ticket type noto'g'ri")
            return None

        sub = payload.get("sub")
        # 4 chi: WS ticket ichidagi `sub` maydoni yaroqsiz bo'lsa, websocket
        # autentifikatsiyasi noto'g'ri userga biriktirilishi mumkin. Uning
        # formatini ham tekshiramiz.
        if sub is None or str(sub).strip() == "":
            logger.warning("WS ticket ichida 'sub' mavjud emas")
            return None
        try:
            int(str(sub))
        except (TypeError, ValueError):
            logger.warning("WS ticket ichidagi 'sub' noto'g'ri formatda")
            return None

        return payload

    except ValueError:
        logger.warning("WS ticket uchun JWT_SECRET konfiguratsiyasi noto'g'ri")

    except ExpiredSignatureError:
        logger.info("WS ticket muddati tugagan")

    except InvalidSignatureError:
        logger.warning("WS ticket imzosi noto'g'ri")

    except InvalidAudienceError:
        logger.warning("WS ticket audience noto'g'ri")

    except InvalidIssuerError:
        logger.warning("WS ticket issuer noto'g'ri")

    except DecodeError:
        logger.warning("WS ticket decode xatosi")

    except jwt.PyJWTError:
        logger.warning("WS ticket xatosi")

    except Exception:
        logger.exception("WS ticket tekshirishda kutilmagan xato")

    return None