from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_session_token
from models.user import User


async def get_current_user_id(authorization: str | None = Header(default=None)) -> int:
    """
    Authorization: Bearer <token> headeridan foydalanuvchi telegram_id sini aniqlaydi.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header topilmadi",
        )

    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_session_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token yaroqsiz yoki muddati o'tgan",
        )

    return int(payload["sub"])


async def get_current_user(
    telegram_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> User:
    """Tokendan telegram_id ni oladi va shu foydalanuvchini DB dan qidirib topadi."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Foydalanuvchi topilmadi",
        )

    return user