import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.handlers.start import router as start_router
from api.routes import auth, rooms, users, game
from core.config import get_settings
from core.database import Base, engine, SessionLocal
from models import disconnect_log as disconnect_log_model  # noqa: F401
from models import room as room_model  # noqa: F401
from models import user as user_model  # noqa: F401
from services.room_service import cleanup_stale_rooms

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(title="UNO Game Backend")

# ------------------- Telegram bot -------------------
bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()
dp.include_router(start_router)

# Bu yerda sizning bot handlerlaringizni import qilib, dp ga ro'yxatdan o'tkazing
# Masalan:
# from bot.handlers import router
# dp.include_router(router)

# ------------------- Webhook endpoint -------------------
@app.post("/webhook")
async def webhook(request: Request) -> dict:
    """Telegram webhook manzili."""
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}

# ------------------- Statik fayllar -------------------
FRONTEND_DIR = settings.frontend_dir
INDEX_FILE = FRONTEND_DIR / "index.html"

if not FRONTEND_DIR.exists():
    raise RuntimeError(f"Frontend papkasi topilmadi: {FRONTEND_DIR}")

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

app.include_router(users.leaderboard_router)
app.include_router(game.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)

# ------------------- Fon vazifalari -------------------
async def _room_cleanup_loop():
    while True:
        try:
            db = SessionLocal()
            try:
                cleanup_stale_rooms(db)
            finally:
                db.close()
        except Exception:
            logger.exception("Xonalarni avtomatik tozalashda xato yuz berdi")
        await asyncio.sleep(5)

@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(_room_cleanup_loop())
    asyncio.create_task(game.disconnect_watcher())
    # Webhookni o‘rnatish
    await bot.set_webhook(settings.WEBHOOK_URL)
    logger.info(f"Webhook o'rnatildi: {settings.WEBHOOK_URL}")

@app.on_event("shutdown")
async def shutdown_webhook():
    await bot.delete_webhook()
    logger.info("Webhook o'chirildi")

# ------------------- Asosiy sahifalar -------------------
@app.get("/")
async def home():
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="index.html topilmadi")
    return FileResponse(INDEX_FILE)

@app.get("/health")
async def health():
    return {"status": "ok"}