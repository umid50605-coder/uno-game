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

        # Kelajakdan yuborilgan auth_date ni rad etish
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

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_session_token(token: str) -> dict | None:
    """
    JWT tokenni tekshiradi.

    Xato bo'lsa None qaytaradi.
    """

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
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
                    "type",  # type maydoni majburiy qilindi
                ]
            },
        )

        if payload.get("type") != "access":
            logger.warning("JWT type noto'g'ri")
            return None

        return payload

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