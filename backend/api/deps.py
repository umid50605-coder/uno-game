"""
backend/api/deps.py 
"""
import logging

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_session_token
from models.user import User

logger = logging.getLogger(__name__)


async def get_current_user_id(
    authorization: str | None = Header(default=None),
) -> int:
    """
    Authorization: Bearer <JWT_TOKEN>

    JWT tokenni tekshiradi va undan foydalanuvchining
    telegram_id qiymatini qaytaradi.
    """

    if not authorization:
        logger.warning("Authorization header mavjud emas")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header topilmadi",
        )

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        logger.warning("Authorization header noto'g'ri formatda")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header noto'g'ri",
        )

    payload = decode_session_token(token.strip())

    if payload is None:
        logger.warning("Yaroqsiz yoki muddati o'tgan JWT token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token yaroqsiz yoki muddati o'tgan",
        )

    sub = payload.get("sub")

    if sub is None:
        logger.warning("JWT token ichida 'sub' mavjud emas")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token noto'g'ri",
        )

    try:
        telegram_id = int(sub)
    except (TypeError, ValueError):
        logger.warning("JWT token ichidagi 'sub' noto'g'ri formatda")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token noto'g'ri",
        )

    return telegram_id


async def get_current_user(
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> User:
    """
    JWT token orqali aniqlangan foydalanuvchini
    ma'lumotlar bazasidan qaytaradi.
    """

    user = (
        db.query(User)
        .filter(User.telegram_id == telegram_id)
        .first()
    )

    if user is None:
        logger.warning(
            "Foydalanuvchi topilmadi (telegram_id=%s)",
            telegram_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Foydalanuvchi topilmadi",
        )

    return user