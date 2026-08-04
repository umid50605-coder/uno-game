import json
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.security import create_session_token, validate_init_data
from models.schemas import AuthResponse, TelegramUser
from models.user import User

logger = logging.getLogger(__name__)


def _upsert_user(db: Session, telegram_user: TelegramUser) -> User:
    """Telegramdan kelgan ma'lumot asosida foydalanuvchini topadi yoki yangi yozuv yaratadi."""
    user = db.query(User).filter(User.telegram_id == telegram_user.id).first()

    if user is None:
        user = User(telegram_id=telegram_user.id, first_name=telegram_user.first_name)
        db.add(user)

    user.first_name = telegram_user.first_name
    user.last_name = telegram_user.last_name
    user.username = telegram_user.username
    user.language_code = telegram_user.language_code
    user.is_premium = bool(telegram_user.is_premium)
    user.photo_url = telegram_user.photo_url

    db.commit()
    db.refresh(user)
    return user


def authenticate_with_init_data(db: Session, init_data: str) -> AuthResponse:
    parsed = validate_init_data(init_data)

    if parsed is None:
        logger.warning("Yaroqsiz initData bilan urinish.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="initData yaroqsiz",
        )

    raw_user = parsed.get("user")
    if not raw_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Foydalanuvchi ma'lumoti topilmadi",
        )

    user_data = json.loads(raw_user)
    telegram_user = TelegramUser(**user_data)

    db_user = _upsert_user(db, telegram_user)

    token = create_session_token(db_user.telegram_id)

    logger.info("Foydalanuvchi muvaffaqiyatli autentifikatsiya qilindi: %s", db_user.telegram_id)

    return AuthResponse(ok=True, token=token, user=telegram_user)