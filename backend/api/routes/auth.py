"""
backend/api/routes/auth.py
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.database import get_db
from models.schemas import AuthRequest, AuthResponse
from services.auth_service import authenticate_with_init_data

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post(
    "",
    response_model=AuthResponse,
    summary="Telegram WebApp autentifikatsiyasi",
    description="Telegram initData orqali foydalanuvchini autentifikatsiya qiladi va JWT session token qaytaradi.",
)
async def auth(
    payload: AuthRequest,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """
    Telegram WebApp initData ni tekshiradi.

    Muvaffaqiyatli bo'lsa foydalanuvchini yaratadi (yoki yangilaydi)
    va JWT session token qaytaradi.
    """

    logger.debug("Autentifikatsiya so'rovi qabul qilindi")

    return authenticate_with_init_data(
        db=db,
        init_data=payload.initData,
    )