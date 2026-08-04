import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

if not TOKEN:
    raise ValueError("BOT_TOKEN muhit o'zgaruvchilarida topilmadi.")

if not WEBAPP_URL:
    raise ValueError("WEBAPP_URL muhit o'zgaruvchilarida topilmadi.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎮 UNO O'ynash",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]
    ]
)


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "🎮 UNO botiga xush kelibsiz!",
        reply_markup=keyboard,
    )


@dp.message(Command("qoidalar"))
async def rules(message: Message) -> None:
    await message.answer(
        "📜 <b>Qoidalar</b>\n\n"
        "🔌 <b>Uzilish:</b> O'yin davomida internetingiz uzilsa, 30 soniya ichida "
        "qayta ulansangiz o'yin davom etadi. Agar bu vaqtda qaytmasangiz, o'yindan "
        "chiqarilgan hisoblanasiz va qolgan o'yinchilar davom etadi.\n\n"
        "⚠️ <b>Ko'p marta uzilish:</b> Ball to'plash uchun ataylab uzilish aniqlansa:\n"
        "- 1 soatda 3 martadan ko'p — 10 daqiqaga bloklanasiz\n"
        "- 1 soatda 6 martadan ko'p — 4 soatga bloklanasiz\n"
        "- 1 soatda 15 martadan ko'p — qora ro'yxatga tushasiz",
        parse_mode="HTML",
    )


async def main() -> None:
    logger.info("Bot ishga tushmoqda...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot to'xtatildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot foydalanuvchi tomonidan to'xtatildi (Ctrl+C).")
