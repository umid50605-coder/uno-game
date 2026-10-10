"""
backend/main.py 
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from bot.handlers.start import router as start_router

from api.routes import auth, game, rooms, users, tournament
from api.routes.websocket.disconnect_watcher import disconnect_watcher
from api.routes.websocket.router import router as websocket_router

from core.config import get_settings
from core.database import Base, SessionLocal, engine

from models import disconnect_log as disconnect_log_model  # noqa: F401
from models import room as room_model  # noqa: F401
from models import user as user_model  # noqa: F401
from models import tournament as tournament_model  # noqa: F401
from models.tournament import Tournament, TournamentStatus

from services.room_service import cleanup_stale_rooms
from services.self_ping import self_ping_loop
from services.tournament_service import recover_stalled_rounds, start_tournament


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


def _ensure_schema_hardening() -> None:
    """DB-darajasidagi cheklovlarni mavjud bazaga ham qo'llaydi (audit F-14).

    Base.metadata.create_all() faqat YO'Q jadvallarni yaratadi — mavjud jadvalga
    yangi UNIQUE cheklov QO'SHMAYDI. Loyihada migratsiya vositasi (Alembic)
    yo'q, shuning uchun model'dagi `uq_tournament_match_room_id` cheklovi
    production bazada shu idempotent buyruq orqali yaratiladi (bir xil nom —
    yangi bazada create_all yaratgan cheklov bilan to'qnashmaydi,
    IF NOT EXISTS tufayli o'tkazib yuboriladi).

    Agar bazada allaqachon dublikat room_id bo'lsa, indeks yaratilmaydi: bu
    holatda server ISHGA TUSHISHI TO'XTATILMAYDI, faqat aniq ogohlantirish
    log qilinadi (dublikatlarni qo'lda tozalab, serverni qayta ishga tushiring).
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tournament_match_room_id "
                    "ON tournament_matches (room_id)"
                )
            )
    except Exception:
        logger.exception(
            "tournament_matches.room_id UNIQUE cheklovini yaratib bo'lmadi "
            "(ehtimol dublikat room_id bor) — qo'lda tekshiring"
        )


_ensure_schema_hardening()

# Single-worker farazi (audit W-14): GameManager, ConnectionManager va
# tournament RLock process-local. Bir nechta worker bo'lsa o'yin holati
# workerlar orasida bo'linib ketadi. Dockerfile `--workers 1` bilan ishga
# tushiradi; bu yerda tasodifiy noto'g'ri sozlamani erta aniqlaymiz.
try:
    _web_concurrency = int(os.getenv("WEB_CONCURRENCY", "1") or "1")
except ValueError:
    _web_concurrency = 1
if _web_concurrency > 1:
    logging.getLogger(__name__).warning(
        "WEB_CONCURRENCY=%s: bu ilova FAQAT bitta worker bilan to'g'ri ishlaydi "
        "(o'yin holati va WebSocket ulanishlari process-local). README'ga qarang.",
        _web_concurrency,
    )

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
app.include_router(websocket_router)
app.include_router(tournament.router)


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


def _tournament_watcher_tick() -> None:
    """Watcher'ning bitta sikli. SINXRON funksiya — asyncio.to_thread() ichida,
    O'ZINING SessionLocal()'i bilan ishlaydi (event loop'ni bloklamaydi;
    tournament_service threading.RLock ishlatadi va worker threadda
    ishlatilishi kerak).

    1) Registration vaqti tugagan turnirlarni boshlaydi.
    2) Failure recovery (audit F-09): barcha matchlari tugagan, lekin round
       o'tishi bajarilmay qolgan roundlarni qayta tiklaydi (idempotent).
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expired_ids = [
            row.id
            for row in db.query(Tournament.id)
            .filter(
                Tournament.status == TournamentStatus.REGISTRATION,
                Tournament.registration_expires_at <= now,
            )
            .all()
        ]
        db.rollback()

        for tournament_id in expired_ids:
            try:
                start_tournament(db, tournament_id)
            except Exception:
                db.rollback()
                logger.exception(
                    "Turnirni avtomatik boshlashda xato tournament=%s", tournament_id,
                )

        recover_stalled_rounds(db)
    finally:
        db.close()


async def _tournament_watcher_loop():
    """Har 5 soniyada registration vaqti tugagan turnirlarni boshlaydi va
    qotib qolgan turnir o'tishlarini qayta tiklaydi. Bu YAGONA joy — bunday
    tekshiruv boshqa hech qayerda (masalan _room_cleanup_loop ichida)
    takrorlanmasligi kerak."""
    while True:
        try:
            await asyncio.to_thread(_tournament_watcher_tick)
        except Exception:
            logger.exception("Turnir watcher xatosi")

        await asyncio.sleep(5)


# ==========================================================
# Startup
# ==========================================================

@app.on_event("startup")
async def startup():
    app.state.cleanup_task = asyncio.create_task(_room_cleanup_loop())
    app.state.disconnect_task = asyncio.create_task(disconnect_watcher())
    app.state.self_ping_task = asyncio.create_task(self_ping_loop(settings.WEBAPP_URL))
    app.state.tournament_task = asyncio.create_task(_tournament_watcher_loop())

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
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

    if secret != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        data = await request.json()
        logger.debug("Webhook update: %s", data)
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Webhook update qayta ishlashda xato")

    return {"ok": True}


# ==========================================================
# Pages
# ==========================================================

@app.api_route("/", methods=["GET", "HEAD"])
async def home():
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="index.html topilmadi")
    return FileResponse(INDEX_FILE)


@app.get("/healthz")
async def health():
    return {"status": "ok"}