"""O'yin yakunlash, forfeit va DB atomicity testlari (audit F-01..F-05, F-12)."""
import asyncio
import inspect

import pytest

from api.routes.websocket import finish as finish_mod
from api.routes.websocket.actions import handle_action
from api.routes.websocket.disconnect_watcher import _process_room
from api.routes.websocket.finish import _persist_game_result, finish_game
from api.routes.websocket.handler import websocket_handler
from api.routes.websocket.state import (
    game_manager,
    get_game_finish_lock,
    manager,
)
from core.database import SessionLocal
from core.security import create_ws_ticket
from models.disconnect_log import DisconnectLog
from models.room import RoomStatus

from .conftest import (
    FakeWebSocket,
    expire_disconnect,
    make_game,
    room_status,
    stats,
    wait_until,
)

WIN, LOSS = 10, 5
BASE = 100  # make_users() boshlang'ich reyting


# ---------------------------------------------------------- Game 1-7

async def test_01_normal_game_finish():
    room_id, (a, b), game = make_game(2)
    ws_a, ws_b = FakeWebSocket("a"), FakeWebSocket("b")
    await manager.connect(room_id, a, ws_a)
    await manager.connect(room_id, b, ws_b)

    game.winner = a
    assert await finish_game(room_id=room_id, game=game, winner=a) is True

    assert stats(a) == {"rating": BASE + WIN, "games_played": 1, "wins": 1, "forfeit_wins": 0, "times_forfeited": 0}
    assert stats(b) == {"rating": BASE - LOSS, "games_played": 1, "wins": 0, "forfeit_wins": 0, "times_forfeited": 0}
    assert room_status(room_id) == RoomStatus.FINISHED
    assert game.finished and room_id not in game_manager
    assert "game_over" in ws_a.types() and "game_over" in ws_b.types()


async def test_02_forfeit_finish_two_players():
    room_id, (a, b), game = make_game(2)
    expire_disconnect(game, b)

    await _process_room(room_id, game)

    assert stats(a)["rating"] == BASE + WIN
    assert stats(a)["wins"] == 1 and stats(a)["forfeit_wins"] == 1
    assert stats(b)["rating"] == BASE - LOSS
    assert stats(b)["games_played"] == 1 and stats(b)["times_forfeited"] == 1
    with SessionLocal() as db:
        assert db.query(DisconnectLog).filter(DisconnectLog.telegram_id == b).count() == 1
    assert room_status(room_id) == RoomStatus.FINISHED
    # RAM DB bilan mos: g'olib belgilangan, forfeit qilgan o'yinchi ro'yxatdan chiqqan
    assert game.winner == a and game.player_ids == [a]
    assert room_id not in game_manager


async def test_03_forfeit_leaves_one_player_no_double_apply():
    room_id, (a, b, c), game = make_game(3)

    # C forfeit -> o'yin davom etadi
    expire_disconnect(game, c)
    await _process_room(room_id, game)
    assert game.player_ids == [a, b] and c not in game.disconnected_at
    assert room_status(room_id) == RoomStatus.PLAYING
    c_after_first = stats(c)
    assert c_after_first["rating"] == BASE - LOSS and c_after_first["games_played"] == 1
    assert stats(a)["rating"] == BASE + WIN // 2 and stats(a)["games_played"] == 0

    # Watcher qayta yursa C ikkinchi marta jazolanmaydi
    await _process_room(room_id, game)
    await _process_room(room_id, game)
    assert stats(c) == c_after_first

    # B ham forfeit -> A yagona qoldi va g'olib
    expire_disconnect(game, b)
    await _process_room(room_id, game)
    assert game.winner == a and room_status(room_id) == RoomStatus.FINISHED
    assert stats(a)["wins"] == 1 and stats(a)["forfeit_wins"] == 1
    assert stats(a)["rating"] == BASE + WIN // 2 + WIN
    assert stats(b)["games_played"] == 1
    assert stats(c) == c_after_first, "C ning natijasi qayta hisoblanmasligi kerak"


async def test_04_player_reconnect_after_forfeit_is_rejected():
    room_id, (a, b, c), game = make_game(3)
    expire_disconnect(game, c)
    await _process_room(room_id, game)
    before = stats(c)

    ws = FakeWebSocket("c")
    task = asyncio.create_task(websocket_handler(ws, create_ws_ticket(c), room_id))
    await asyncio.wait_for(task, 5)

    assert "forfeited" in ws.types()
    assert ws.close_code == 1008
    assert game.player_ids == [a, b] and not game.is_disconnected(c)
    assert stats(c) == before


async def test_05_action_after_winner_rejected():
    room_id, (a, b), game = make_game(2)
    game.winner = a
    await finish_game(room_id=room_id, game=game, winner=a)

    for pid in (a, b):
        res = await handle_action(game=game, telegram_id=pid, data={"action": "draw_card"})
        assert res["ok"] is False


async def test_06_invalid_player_action():
    room_id, (a, b), game = make_game(2)
    outsider = 999999

    res = await handle_action(game=game, telegram_id=outsider, data={"action": "draw_card"})
    assert res["ok"] is False

    res = await handle_action(game=game, telegram_id=a, data={"action": "no_such_action"})
    assert res["ok"] is False

    res = await handle_action(game=game, telegram_id=a, data={"action": "play_card", "card_index": "x"})
    assert res["ok"] is False

    # tartibsiz yurish: navbat a'da bo'lmasa b yura olmaydi
    current = game._current_player()
    other = b if current == a else a
    res = await handle_action(game=game, telegram_id=other, data={"action": "draw_card"})
    assert res["ok"] is False


async def test_07_duplicate_finish_attempt():
    room_id, (a, b), game = make_game(2)
    game.winner = a

    results = await asyncio.gather(
        finish_game(room_id=room_id, game=game, winner=a),
        finish_game(room_id=room_id, game=game, winner=a),
    )
    assert sorted(results) == [False, True]
    assert stats(a)["rating"] == BASE + WIN and stats(a)["wins"] == 1
    assert stats(b)["rating"] == BASE - LOSS and stats(b)["games_played"] == 1

    # RAM bayrog'i yo'qolgan (masalan yangi GameEngine) bo'lsa ham DB gate ishlaydi:
    game2 = game_manager.create(room_id, [a, b], {a: "a", b: "b"})
    game2.winner = a
    await finish_game(room_id=room_id, game=game2, winner=a)
    assert stats(a)["rating"] == BASE + WIN and stats(b)["rating"] == BASE - LOSS

    # va to'g'ridan-to'g'ri T1 funksiyasi ham ikkinchi marta hech narsa yozmaydi
    res = _persist_game_result(room_id=room_id, player_ids=[a, b], winner=a,
                               via_forfeit=False, loser=None, cancelled=False)
    assert res.already_finished is True
    assert stats(a)["rating"] == BASE + WIN


# ---------------------------------------------------------- Database 21-23

async def test_21_rating_and_room_are_atomic(monkeypatch):
    room_id, (a, b), game = make_game(2)
    game.winner = a

    def boom(db, rid):
        raise RuntimeError("finish_room yiqildi")

    monkeypatch.setattr(finish_mod, "finish_room", boom)

    ok = await finish_game(room_id=room_id, game=game, winner=a)

    assert ok is False
    # reyting ham, room ham o'zgarmagan: "rating = committed, room = not committed" YO'Q
    assert stats(a)["rating"] == BASE and stats(a)["wins"] == 0
    assert stats(b)["rating"] == BASE and stats(b)["games_played"] == 0
    assert room_status(room_id) == RoomStatus.PLAYING
    assert game.finished is False and room_id in game_manager


async def test_22_failed_room_finish_keeps_forfeit_state(monkeypatch):
    room_id, (a, b), game = make_game(2)
    expire_disconnect(game, b)

    def boom(db, rid):
        raise RuntimeError("DB yiqildi")

    monkeypatch.setattr(finish_mod, "finish_room", boom)
    await _process_room(room_id, game)

    # DB tegilmagan
    assert stats(a)["rating"] == BASE and stats(b)["rating"] == BASE
    assert room_status(room_id) == RoomStatus.PLAYING
    with SessionLocal() as db:
        assert db.query(DisconnectLog).count() == 0
    # RAM ham tegilmagan: forfeit yo'qolmagan, retry imkoniyati bor
    assert game.player_ids == [a, b]
    assert game.winner is None and game.finished is False
    assert b in game.get_expired_disconnects()


async def test_23_retry_after_failure_applies_exactly_once(monkeypatch):
    room_id, (a, b), game = make_game(2)
    expire_disconnect(game, b)
    real = finish_mod.finish_room
    calls = {"n": 0}

    def flaky(db, rid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("vaqtinchalik DB xatosi")
        return real(db, rid)

    monkeypatch.setattr(finish_mod, "finish_room", flaky)

    await _process_room(room_id, game)          # 1-urinish: yiqiladi
    assert stats(a)["rating"] == BASE and room_status(room_id) == RoomStatus.PLAYING

    await _process_room(room_id, game)          # retry: muvaffaqiyatli
    assert stats(a) == {"rating": BASE + WIN, "games_played": 1, "wins": 1, "forfeit_wins": 1, "times_forfeited": 0}
    assert stats(b)["rating"] == BASE - LOSS and stats(b)["times_forfeited"] == 1
    with SessionLocal() as db:
        assert db.query(DisconnectLog).filter(DisconnectLog.telegram_id == b).count() == 1
    assert room_status(room_id) == RoomStatus.FINISHED

    await _process_room(room_id, game)          # keyingi sikl hech narsani o'zgartirmaydi
    assert stats(a)["rating"] == BASE + WIN


async def test_23b_pending_normal_finish_is_retried_by_watcher(monkeypatch):
    """Oddiy g'alaba (play_card) finish'i yiqilsa, watcher uni qayta yakunlaydi."""
    room_id, (a, b), game = make_game(2)
    game.winner = a
    real = finish_mod.finish_room
    state = {"fail": True}

    def flaky(db, rid):
        if state["fail"]:
            raise RuntimeError("DB xatosi")
        return real(db, rid)

    monkeypatch.setattr(finish_mod, "finish_room", flaky)
    assert await finish_game(room_id=room_id, game=game, winner=a) is False
    assert game.finished is False and stats(a)["rating"] == BASE

    state["fail"] = False
    await _process_room(room_id, game)
    assert stats(a)["rating"] == BASE + WIN and stats(a)["wins"] == 1
    assert room_status(room_id) == RoomStatus.FINISHED


async def test_23c_midgame_forfeit_db_failure_keeps_ram_and_retries(monkeypatch):
    room_id, (a, b, c), game = make_game(3)
    expire_disconnect(game, c)
    real = finish_mod._persist_midgame_forfeit
    state = {"fail": True}

    def flaky(pid, remaining):
        if state["fail"]:
            raise RuntimeError("DB yiqildi")
        return real(pid, remaining)

    monkeypatch.setattr(finish_mod, "_persist_midgame_forfeit", flaky)

    await _process_room(room_id, game)
    assert game.player_ids == [a, b, c] and c in game.disconnected_at
    assert stats(c)["rating"] == BASE

    state["fail"] = False
    await _process_room(room_id, game)
    assert game.player_ids == [a, b]
    assert stats(c)["rating"] == BASE - LOSS and stats(c)["games_played"] == 1
    await _process_room(room_id, game)
    assert stats(c)["rating"] == BASE - LOSS


async def test_forfeit_not_applied_if_player_reconnected_while_waiting_for_lock():
    room_id, (a, b), game = make_game(2)
    expire_disconnect(game, b)

    lock = get_game_finish_lock(room_id)
    await lock.acquire()
    task = asyncio.create_task(_process_room(room_id, game))
    await asyncio.sleep(0.05)
    game.mark_reconnected(b)          # lock kutilayotgan paytda qayta ulandi
    lock.release()
    await asyncio.wait_for(task, 5)

    assert stats(a)["rating"] == BASE and stats(b)["rating"] == BASE
    assert room_status(room_id) == RoomStatus.PLAYING and game.player_ids == [a, b]


# ---------------------------------------------------------- broadcast failure (12)

async def test_12_broadcast_failure_does_not_roll_back_game():
    room_id, (a, b), game = make_game(2)
    ws_a, ws_b = FakeWebSocket("a"), FakeWebSocket("b")
    await manager.connect(room_id, a, ws_a)
    await manager.connect(room_id, b, ws_b)
    ws_a.fail_send = ws_b.fail_send = True

    game.winner = a
    assert await finish_game(room_id=room_id, game=game, winner=a) is True
    assert stats(a)["rating"] == BASE + WIN
    assert room_status(room_id) == RoomStatus.FINISHED
    assert room_id not in game_manager


# ---------------------------------------------------------- F-12 per-room lock

async def test_12b_finish_locks_are_per_room():
    assert get_game_finish_lock(1) is get_game_finish_lock(1)
    assert get_game_finish_lock(1) is not get_game_finish_lock(2)

    room1, (a1, b1), game1 = make_game(2, base=1000)
    room2, (a2, b2), game2 = make_game(2, base=2000)

    lock1 = get_game_finish_lock(room1)
    await lock1.acquire()
    try:
        # 1-xona lock'i band — 2-xona to'siqsiz yakunlanadi
        game2.winner = a2
        assert await asyncio.wait_for(finish_game(room_id=room2, game=game2, winner=a2), 5) is True

        # 1-xonaning o'zida esa finish lock bo'shaguncha kutadi
        game1.winner = a1
        t = asyncio.create_task(finish_game(room_id=room1, game=game1, winner=a1))
        await asyncio.sleep(0.1)
        assert not t.done()
    finally:
        lock1.release()
    assert await asyncio.wait_for(t, 5) is True


def test_finish_game_has_no_db_parameter():
    """F-01/F-11: WebSocket handler sessiyasi finish'ga uzatilmaydi."""
    assert "db" not in inspect.signature(finish_game).parameters
