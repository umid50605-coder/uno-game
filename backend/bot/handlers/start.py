from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.keyboards import main_keyboard

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🎮 UNO botiga xush kelibsiz!",
        reply_markup=main_keyboard,
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