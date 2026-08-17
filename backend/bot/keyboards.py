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

main_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎮 UNO O'ynash",
                web_app=WebAppInfo(url=settings.WEBAPP_URL),
            )
        ]
    ]
)