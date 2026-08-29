"""
backend/bot/keyboards.py
"""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from core.config import get_settings

settings = get_settings()


def main_keyboard() -> InlineKeyboardMarkup:
    """Oddiy 'O'ynash' tugmasi — hech qanday qo'shimcha parametrsiz WebApp ochadi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 UNO O'ynash",
                    web_app=WebAppInfo(url=settings.WEBAPP_URL),
                )
            ]
        ]
    )


def tournament_keyboard(tournament_id: int, invite_token: str) -> InlineKeyboardMarkup:
    """Tournament invite havolasi bosilganda ochiladigan tugma.

    MUHIM: tournament_id/invite_token WebApp URL'ning QUERY-STRING qismiga
    qo'shiladi (tg.initDataUnsafe.start_param EMAS), chunki inline keyboard
    WebAppInfo tugmasi orqali ochilgan Mini App'da start_param mexanizmi
    ishlamaydi — bu faqat t.me/bot?startapp=... to'g'ridan-to'g'ri havola
    (attachment menu) orqali ochilganda ishlaydi. Query-string har doim
    ishonchli ishlaydi, chunki frontend uni window.location.search orqali
    o'qiydi."""
    url = f"{settings.WEBAPP_URL}?tournament={tournament_id}&invite_token={invite_token}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏆 Turnirga qo'shilish",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )