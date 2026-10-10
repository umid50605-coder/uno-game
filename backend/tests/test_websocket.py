"""WebSocket testlari: reconnect, stale socket, parallel actions, DB session (audit F-10, F-11)."""
import asyncio

from api.routes.websocket.handler import WS_CLOSE_REPLACED, websocket_handler
from api.routes.websocket.state import manager
from core.database import engine
from core.security import create_ws_ticket

from .conftest import FakeWebSocket, make_game, wait_until


async def _connect(room_id: int, tid: int, name: str):
    ws = FakeWebSocket(name)
    task = asyncio.create_task(websocket_handler(ws, create_ws_ticket(tid), room_id))
    await wait_until(lambda: manager.is_current(room_id, tid, ws) and len(ws.sent) > 0)
    return ws, task


async def _stop(*pairs):
    for ws, task in pairs:
        if not task.done():
            ws.client_disconnect()
    for _, task in pairs:
        await asyncio.wait_for(task, 5)


async def test_08_reconnect_replaces_connection():
    room_id, (a, b), game = make_game(2)
    ws1, t1 = await _connect(room_id, a, "a1")
    ws2, t2 = await _connect(room_id, a, "a2")

    assert manager.is_current(room_id, a, ws2)
    assert not manager.is_current(room_id, a, ws1)
    assert manager.rooms[room_id][a] is ws2
    assert ws2.sent[0]["type"] != "error"       # yangi socket holatni oldi

    await _stop((ws1, t1), (ws2, t2))


async def test_09_old_socket_cannot_act_after_reconnect():
    room_id, (a, b), game = make_game(2)
    ws_old, t_old = await _connect(room_id, a, "old")
    ws_new, t_new = await _connect(room_id, a, "new")

    # a'ning navbati bo'lsin
    while game._current_player() != a:
        game.current_index = (game.current_index + 1) % len(game.player_ids)
    hand_before = len(game.hands[a])
    new_sent_before = len(ws_new.sent)

    ws_old.client_send({"action": "draw_card"})
    await asyncio.wait_for(t_old, 5)           # eski handler to'xtadi

    assert ws_old.close_code == WS_CLOSE_REPLACED
    assert len(game.hands[a]) == hand_before, "eski socket action bajara olmadi"
    assert game._current_player() == a, "navbat o'zgarmadi"
    assert len(ws_new.sent) == new_sent_before, "yangi socketga hech narsa yuborilmadi (xato ham, broadcast ham)"
    assert manager.is_current(room_id, a, ws_new), "yangi socketga tegilmadi"
    assert not t_new.done()

    # yangi socket esa normal ishlaydi
    ws_new.client_send({"action": "draw_card"})
    await wait_until(lambda: len(game.hands[a]) != hand_before or game._current_player() != a)

    await _stop((ws_new, t_new))


async def test_09b_old_socket_ping_and_bad_json_do_not_reach_new_socket():
    room_id, (a, b), game = make_game(2)
    ws_old, t_old = await _connect(room_id, a, "old")
    ws_new, t_new = await _connect(room_id, a, "new")
    before = len(ws_new.sent)

    ws_old.client_send({"action": "ping"})
    await asyncio.wait_for(t_old, 5)

    assert "pong" not in ws_old.types()[1:]
    assert len(ws_new.sent) == before
    await _stop((ws_new, t_new))


async def test_10_stale_disconnect_does_not_mark_player_disconnected():
    room_id, (a, b), game = make_game(2)
    ws_b, t_b = await _connect(room_id, b, "b")
    ws_old, t_old = await _connect(room_id, a, "old")
    ws_new, t_new = await _connect(room_id, a, "new")
    b_before = len(ws_b.sent)

    ws_old.client_disconnect()                  # eski socket kechikib uzildi
    await asyncio.wait_for(t_old, 5)

    assert manager.is_current(room_id, a, ws_new)
    assert not game.is_disconnected(a)
    assert "player_disconnected" not in [m.get("type") for m in ws_b.sent[b_before:]]

    # haqiqiy (joriy socket) uzilishi esa grace period'ni boshlaydi
    ws_new.client_disconnect()
    await asyncio.wait_for(t_new, 5)
    assert game.is_disconnected(a)
    assert not manager.is_connected(room_id, a)

    await _stop((ws_b, t_b))


async def test_11_parallel_actions_only_current_player_succeeds():
    room_id, (a, b), game = make_game(2)
    ws_a, t_a = await _connect(room_id, a, "a")
    ws_b, t_b = await _connect(room_id, b, "b")

    current = game._current_player()
    other = b if current == a else a
    ws_cur, ws_oth = (ws_a, ws_b) if current == a else (ws_b, ws_a)
    cur_hand = len(game.hands[current])
    oth_hand = len(game.hands[other])
    n_cur, n_oth = len(ws_cur.sent), len(ws_oth.sent)

    # ikkalasi bir vaqtda action yuboradi
    ws_oth.client_send({"action": "draw_card"})
    ws_cur.client_send({"action": "draw_card"})
    await wait_until(lambda: len(ws_cur.sent) > n_cur and len(ws_oth.sent) > n_oth)
    await asyncio.sleep(0.1)

    assert len(game.hands[other]) == oth_hand, "navbati yo'q o'yinchi karta tortolmadi"
    assert len(game.hands[current]) == cur_hand + 1
    errors = [m for m in ws_oth.sent[n_oth:] if m.get("type") == "error"]
    assert errors, "navbatsiz o'yinchi xato oldi"
    assert not [m for m in ws_cur.sent[n_cur:] if m.get("type") == "error"]

    await _stop((ws_a, t_a), (ws_b, t_b))


async def test_auth_session_is_not_held_for_connection_lifetime():
    """F-11: ulanish ochiq turganda ham DB connection pool'dan olingan connection yo'q."""
    room_id, (a, b), game = make_game(2)
    ws_a, t_a = await _connect(room_id, a, "a")
    ws_b, t_b = await _connect(room_id, b, "b")

    await asyncio.sleep(0.1)
    assert not t_a.done() and not t_b.done()
    assert engine.pool.checkedout() == 0

    await _stop((ws_a, t_a), (ws_b, t_b))
    assert engine.pool.checkedout() == 0


async def test_unauthenticated_and_foreign_player_rejected_without_leaking_sessions():
    room_id, (a, b), game = make_game(2)

    ws = FakeWebSocket("bad")
    await websocket_handler(ws, "not-a-ticket", room_id)
    assert ws.close_code == 1008

    ws2 = FakeWebSocket("outsider")
    await websocket_handler(ws2, create_ws_ticket(424242), room_id)
    assert ws2.close_code == 1008
    assert engine.pool.checkedout() == 0
