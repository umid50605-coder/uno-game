"""
backend/bot/keyboards.py
"""
from urllib.parse import urlencode

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from core.config import get_settings

settings = get_settings()


def _base_webapp_url() -> str:
    return settings.WEBAPP_URL.rstrip("/")


def _webapp_url(**query_params: str | int) -> str:
    query = urlencode({key: str(value) for key, value in query_params.items()})
    if not query:
        return _base_webapp_url()
    return f"{_base_webapp_url()}?{query}"


def main_keyboard() -> InlineKeyboardMarkup:
    """Oddiy 'O'ynash' tugmasi — hech qanday qo'shimcha parametrsiz WebApp ochadi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 UNO O'ynash",
                    web_app=WebAppInfo(url=_base_webapp_url()),
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
    if not isinstance(tournament_id, int) or tournament_id <= 0:
        return main_keyboard()

    normalized_token = (invite_token or "").strip()
    if not normalized_token:
        return main_keyboard()

    url = _webapp_url(tournament=tournament_id, invite_token=normalized_token)
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