"""
backend/api/routes/auth.py
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_current_user_id
from core.database import get_db
from core.security import create_ws_ticket
from models.schemas import AuthRequest, AuthResponse, WsTicketOut
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


@router.post(
    "/ws-ticket",
    response_model=WsTicketOut,
    summary="WebSocket ulanishi uchun qisqa muddatli ticket",
    description=(
        "Asosiy session JWT WebSocket URL'ga to'g'ridan-to'g'ri qo'yilmasligi "
        "uchun, bu endpoint orqali (Authorization header bilan, URL'da emas) "
        "atigi bir necha soniya amal qiladigan alohida ticket olinadi."
    ),
)
async def get_ws_ticket(
    telegram_id: int = Depends(get_current_user_id),
) -> WsTicketOut:
    ticket = create_ws_ticket(telegram_id)
    return WsTicketOut(ticket=ticket)