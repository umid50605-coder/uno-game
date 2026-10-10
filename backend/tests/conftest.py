"""
Test muhiti.

DIQQAT: har bir testdan oldin barcha jadvallar DROP + CREATE qilinadi.
Shuning uchun TEST_DATABASE_URL majburiy va baza nomida "test" bo'lishi shart.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_test_url = os.environ.get("TEST_DATABASE_URL")
if not _test_url:
    raise RuntimeError("TEST_DATABASE_URL o'rnatilmagan (masalan postgresql://postgres@localhost:5433/unotest)")
if "test" not in _test_url.rsplit("/", 1)[-1].lower():
    raise RuntimeError("TEST_DATABASE_URL bazasi nomida 'test' bo'lishi shart — production bazani ko'rsatmang!")

os.environ["DATABASE_URL"] = _test_url
os.environ.setdefault("BOT_TOKEN", "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
os.environ.setdefault("BOT_USERNAME", "test_bot")
os.environ.setdefault("WEBAPP_URL", "http://localhost:9")
os.environ.setdefault("JWT_SECRET", "j" * 48)
os.environ.setdefault("WEBHOOK_SECRET", "w" * 48)

from fastapi import WebSocketDisconnect  # noqa: E402

from core.database import Base, SessionLocal, engine  # noqa: E402
from models import disconnect_log as _m1  # noqa: E402,F401
from models import room as _m2  # noqa: E402,F401
from models import tournament as _m3  # noqa: E402,F401
from models import user as _m4  # noqa: E402,F401
from models.room import Room, RoomPlayer, RoomStatus, RoomType, generate_room_code  # noqa: E402
from models.user import User  # noqa: E402

_DISCONNECT = object()


class FakeWebSocket:
    """Starlette WebSocket o'rniga ishlatiladigan test ob'ekti."""

    def __init__(self, name: str = "ws"):
        self.name = name
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.accepted = False
        self.close_code: int | None = None
        self.fail_send = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        if self.close_code is not None or self.fail_send:
            raise RuntimeError(f"{self.name}: socket yopiq/buzuq")
        self.sent.append(data)

    async def receive_json(self):
        item = await self.inbox.get()
        if item is _DISCONNECT:
            raise WebSocketDisconnect(code=1001)
        return item

    async def close(self, code: int = 1000):
        if self.close_code is None:
            self.close_code = code
        self.inbox.put_nowait(_DISCONNECT)

    # --- test yordamchilari ---
    def client_send(self, data: dict):
        self.inbox.put_nowait(data)

    def client_disconnect(self):
        self.inbox.put_nowait(_DISCONNECT)

    def types(self) -> list[str]:
        return [m.get("type") for m in self.sent]


async def wait_until(predicate, timeout: float = 5.0, interval: float = 0.01):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    raise AssertionError("wait_until: vaqt tugadi")


@pytest.fixture(autouse=True)
def clean_state():
    from api.routes.websocket import state

    engine.dispose()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    state.game_manager.clear()
    state.manager.rooms.clear()
    state.manager.tournaments.clear()
    state._game_finish_locks.clear()
    yield
    state.game_manager.clear()
    state.manager.rooms.clear()
    state.manager.tournaments.clear()
    state._game_finish_locks.clear()
    engine.dispose()


# ----------------------------------------------------------
# DB yordamchilari
# ----------------------------------------------------------

def make_users(n: int, base: int = 1000, rating: int = 100) -> list[int]:
    with SessionLocal() as db:
        for i in range(n):
            db.add(User(telegram_id=base + i, first_name=f"P{base + i}", rating=rating))
        db.commit()
    return [base + i for i in range(n)]


def make_room(tids: list[int], status: RoomStatus = RoomStatus.PLAYING,
              room_type: RoomType = RoomType.NORMAL) -> int:
    with SessionLocal() as db:
        users = {u.telegram_id: u for u in db.query(User).filter(User.telegram_id.in_(tids)).all()}
        room = Room(code=generate_room_code(), host_id=users[tids[0]].id, status=status,
                    max_players=max(4, len(tids)), room_type=room_type)
        db.add(room)
        db.flush()
        for t in tids:
            db.add(RoomPlayer(room_id=room.id, user_id=users[t].id, is_ready=True))
        db.commit()
        return room.id


def make_game(n: int = 2, base: int = 1000):
    """n ta o'yinchi + PLAYING room + RAM'dagi GameEngine."""
    from api.routes.websocket.state import game_manager

    tids = make_users(n, base)
    room_id = make_room(tids)
    names = {t: f"P{t}" for t in tids}
    game = game_manager.create(room_id, list(tids), names)
    return room_id, tids, game


def stats(tid: int) -> dict:
    with SessionLocal() as db:
        u = db.query(User).filter(User.telegram_id == tid).first()
        return {
            "rating": u.rating,
            "games_played": u.games_played,
            "wins": u.wins,
            "forfeit_wins": u.forfeit_wins,
            "times_forfeited": u.times_forfeited,
        }


def room_status(room_id: int) -> RoomStatus:
    with SessionLocal() as db:
        return db.query(Room).filter(Room.id == room_id).first().status


def expire_disconnect(game, tid: int, seconds: int = 31):
    """O'yinchini grace period'i allaqachon tugagan holda 'uzilgan' qiladi."""
    game.disconnected_at[tid] = datetime.now(timezone.utc) - timedelta(seconds=seconds)
