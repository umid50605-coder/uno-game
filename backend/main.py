"""
backend/main.py 
"""
import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from bot.handlers.start import router as start_router

from api.routes import auth, game, rooms, users
from api.routes.websocket.disconnect_watcher import disconnect_watcher

from core.config import get_settings
from core.database import Base, SessionLocal, engine

from models import disconnect_log as disconnect_log_model  # noqa: F401
from models import room as room_model  # noqa: F401
from models import user as user_model  # noqa: F401

from services.room_service import cleanup_stale_rooms


# ==========================================================
# Logging
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


# ==========================================================
# Settings
# ==========================================================

settings = get_settings()

Base.metadata.create_all(bind=engine)

app = FastAPI(title="UNO Game Backend")


# ==========================================================
# Telegram Bot
# ==========================================================

bot = Bot(token=settings.BOT_TOKEN)

dp = Dispatcher()
dp.include_router(start_router)


# ==========================================================
# Static Files
# ==========================================================

FRONTEND_DIR = settings.frontend_dir
INDEX_FILE = FRONTEND_DIR / "index.html"

if not FRONTEND_DIR.exists():
    raise RuntimeError(f"Frontend papkasi topilmadi: {FRONTEND_DIR}")

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static",
)


# ==========================================================
# Routers
# ==========================================================

app.include_router(users.leaderboard_router)
app.include_router(game.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)


# ==========================================================
# Background Tasks
# ==========================================================

async def _room_cleanup_loop():
    while True:
        try:
            db = SessionLocal()

            try:
                cleanup_stale_rooms(db)
            finally:
                db.close()

        except Exception:
            logger.exception("Xonalarni avtomatik tozalashda xato")

        await asyncio.sleep(5)


# ==========================================================
# Startup
# ==========================================================

@app.on_event("startup")
async def startup():
    # Background vazifalarni ishga tushirish
    app.state.cleanup_task = asyncio.create_task(_room_cleanup_loop())
    app.state.disconnect_task = asyncio.create_task(
        disconnect_watcher()
    )

    try:
        await bot.set_webhook(
            url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET,
        )

        webhook_info = await bot.get_webhook_info()

        logger.info(
            "Webhook muvaffaqiyatli o'rnatildi: %s",
            settings.WEBHOOK_URL,
        )

        logger.info(
            "Webhook holati | pending_updates=%d | last_error=%s",
            webhook_info.pending_update_count,
            webhook_info.last_error_message or "yo'q",
        )

    except Exception:
        logger.exception(
            "Webhook o'rnatishda yoki tekshirishda xato yuz berdi"
        )

# ==========================================================
# Webhook
# ==========================================================

@app.post("/webhook")
async def webhook(request: Request):

    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if secret != settings.WEBHOOK_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Forbidden",
        )

    try:
        data = await request.json()

        logger.debug("Webhook update: %s", data)

        update = Update.model_validate(data)

        await dp.feed_update(bot, update)

    except Exception:
        logger.exception("Webhook update qayta ishlashda xato")

    # Telegram qayta yubormasligi uchun doimo OK qaytaramiz
    return {"ok": True}


# ==========================================================
# Pages
# ==========================================================

@app.api_route("/", methods=["GET", "HEAD"])
async def home():

    if not INDEX_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="index.html topilmadi",
        )

    return FileResponse(INDEX_FILE)


@app.get("/healthz")
async def health():
    return {
        "status": "ok"
    }