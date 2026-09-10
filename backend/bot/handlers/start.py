"""
backend/bot/handlers/start.py
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot.keyboards import main_keyboard, tournament_keyboard

router = Router()


@router.message(CommandStart())
async def start(message: Message, command: CommandObject):
    """
    Oddiy /start — asosiy o'ynash tugmasi.

    Deep link orqali kelgan bo'lsa (masalan Telegram guruhida ulashilgan
    tournament havolasi: t.me/<bot>?start=trny_<id>_<token>), buni ushlab,
    tournament'ga mos WebApp tugmasini ko'rsatadi.
    """
    payload = (command.args or "").strip()  # masalan "trny_123_AbCdEf..."

    if payload.startswith("trny_"):
        prefix, _, remainder = payload.partition("_")
        if prefix == "trny" and remainder:
            tournament_id_str, separator, invite_token = remainder.partition("_")
            if separator and tournament_id_str.isdigit() and invite_token.strip():
                tournament_id = int(tournament_id_str)
                if tournament_id > 0:
                    await message.answer(
                        "🏆 Sizni turnirga taklif qilishdi!\n\n"
                        "Qo'shilish uchun tugmani bosing:",
                        reply_markup=tournament_keyboard(tournament_id, invite_token.strip()),
                    )
                    return

    await message.answer(
        "🎮 UNO botiga xush kelibsiz!",
        reply_markup=main_keyboard(),
    )


@router.message(Command("qoidalar"))
async def rules(message: Message):
    await message.answer(
        "📜 <b>Qoidalar</b>\n\n"
        "🔌 <b>Uzilish:</b>\n"
        "Internet uzilsa, 30 soniya ichida qayta ulansangiz o'yin davom etadi.\n\n"
        "⚠️ <b>Ko'p marta uzilish:</b>\n"
        "• 3 marta — 10 daqiqa blok\n"
        "• 6 marta — 4 soat blok\n"
        "• 15 marta — qora ro'yxat",
        parse_mode="HTML",
    )