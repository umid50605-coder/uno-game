"""
Stage 12+13+12.1+14+16 — Game + WebSocket route

Stage 14'da qo'shildi:
  - Qayta ulanish: agar o'yinchi grace period ichida qaytib ulansa,
    "player_reconnected" broadcast qilinadi va holat yangilanadi
  - Forfeit qilingan o'yinchi qaytib ulansa — "forfeited" xabari bilan
    yopiladi (frontend lobby/room ekraniga qaytaradi)
  - disconnect_watcher(): har 5 soniyada barcha faol o'yinlarni tekshirib,
    grace period tugagan o'yinchilarni forfeit qiladi va shu voqeada ballarni
    darhol hisoblaydi (apply_forfeit_result / apply_game_result). main.py'da
    _room_cleanup_loop bilan bir xil naqshda ishga tushiriladi:
    asyncio.create_task(game.disconnect_watcher()).

Stage 16'da qo'shildi:
  - Ulanishda xona holati (Room.status) PLAYING ekanligi tekshiriladi —
    aks holda: (a) hali "tayyor" bosilmagan xonaga to'g'ridan-to'g'ri
    ulanib o'yinni erta boshlab yuborish, yoki (b) allaqachon tugagan
    (FINISHED) xonaga qayta ulanib, uni "active_games" ichida topilmagani
    uchun butunlay yangi (arvoh) o'yin sifatida qayta yaratib yuborish —
    ikkalasi ham mumkin bo'lmay qoladi
  - Har qanday noto'g'ri formatdagi ("card_index" butun son emas, top-level
    JSON dict emas va h.k.) xabar endi ulanishni yiqitmaydi — try/except
    orqali "Noto'g'ri so'rov" xatosi bilan rad etiladi, ulanish davom etadi
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from api.deps import get_db
from core.security import decode_session_token
from models.room import Room, RoomStatus
from models.user import User
from services import abuse_service
from services.connection_manager import ConnectionManager
from services.game_engine import GameEngine, GRACE_PERIOD_SECONDS
from services.rating_service import apply_forfeit_result, apply_game_result
from services.room_service import get_room_player_ids, finish_room

logger = logging.getLogger(__name__)

router = APIRouter()
HEARTBEAT_TIMEOUT_SECONDS = 12

manager = ConnectionManager()
active_games: dict[int, GameEngine] = {}


@router.websocket("/ws/rooms/{room_id}")
async def game_websocket(websocket: WebSocket, room_id: int, token: str = Query(...)):
    logger.info("========== NEW WEBSOCKET ==========")
    logger.info(f"room_id={room_id}")
    logger.info(f"token={token}")
    payload = decode_session_token(token)
    if payload is None:
        logger.info("WS: token yaroqsiz")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    telegram_id = int(payload["sub"])

    db_gen = get_db()
    db = next(db_gen)

    try:
        # Stage 16: xona hali PLAYING holatida emasligi (hali WAITING, yoki
        # allaqachon FINISHED) — ulanishni butunlay rad etamiz. Shu bir
        # tekshiruv ikkita muammoni bir yo'la yopadi: (1) "tayyor" bosilmasdan
        # turib to'g'ridan-to'g'ri o'yinni boshlab yuborish, (2) tugagan
        # xonaga qayta ulanib, uni active_games'da topilmagani uchun
        # butunlay yangi ("arvoh") o'yin sifatida qayta yaratib yuborish.
        room_row = db.query(Room).filter(Room.id == room_id).first()
        if room_row is None or room_row.status != RoomStatus.PLAYING:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        room_player_ids = get_room_player_ids(db, room_id)
        if telegram_id not in room_player_ids:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await manager.connect(room_id, telegram_id, websocket)

        if room_id not in active_games:
            users = db.query(User).filter(User.telegram_id.in_(room_player_ids)).all()
            player_names = {u.telegram_id: (u.username or u.first_name) for u in users}
            active_games[room_id] = GameEngine(
                room_id=room_id, player_ids=room_player_ids, player_names=player_names
            )

        game = active_games[room_id]

        try:
            initial_state = game.get_state(telegram_id)

            if initial_state.get("type") == "not_in_game":
                await websocket.send_json({
                    "type": "forfeited",
                    "message": "Siz bu o'yindan chiqarilgansiz (uzoq vaqt uzilib qolgansiz)",
                })
                await websocket.close()
                return

            was_reconnecting = game.is_disconnected(telegram_id)
            if was_reconnecting:
                game.mark_reconnected(telegram_id)

            await websocket.send_json(initial_state)

            if was_reconnecting:
                await manager.broadcast_raw(
                    room_id, {"type": "player_reconnected", "player_id": telegram_id}
                )
                await manager.broadcast_state(room_id, game)

            while True:
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=HEARTBEAT_TIMEOUT_SECONDS
                    )

                    print("RECV FROM CLIENT:", telegram_id, data)
                    if not isinstance(data, dict):
                        continue
                except asyncio.TimeoutError:
                    logger.info(
                        "Player %s: %ss xabar kelmadi, uzilgan deb hisoblanmoqda",
                        telegram_id, HEARTBEAT_TIMEOUT_SECONDS,
                    )
                    try:
                        await websocket.close(code=status.WS_1001_GOING_AWAY)
                    except Exception:
                        pass
                    raise WebSocketDisconnect()

                if not isinstance(data, dict):
                    continue

                action = data.get("action")

                if action == "ping":
                    continue

                try:
                    if action == "play_card":
                        card_index = data.get("card_index")
                        chosen_color = data.get("chosen_color")

                        if not isinstance(card_index, int):
                            result = {"ok": False, "error": "Noto'g'ri so'rov"}
                        elif chosen_color is not None and not isinstance(chosen_color, str):
                            result = {"ok": False, "error": "Noto'g'ri so'rov"}
                        else:
                            result = game.play_card(
                                player_id=telegram_id,
                                card_index=card_index,
                                chosen_color=chosen_color,
                                call_uno=bool(data.get("call_uno", False)),
                            )
                    elif action == "draw_card":
                        result = game.draw_card(player_id=telegram_id)
                    elif action == "call_uno":
                        result = game.call_uno(player_id=telegram_id)
                    elif action == "catch_uno":
                        target_id = data.get("target_id")
                        if not isinstance(target_id, int):
                            result = {"ok": False, "error": "Noto'g'ri so'rov"}
                        else:
                            result = game.catch_uno(catcher_id=telegram_id, target_id=target_id)
                    else:
                        result = {"ok": False, "error": f"Noma'lum action: {action}"}
                except Exception:
                    logger.exception("Player %s'dan noto'g'ri formatdagi xabar: %r", telegram_id, data)
                    result = {"ok": False, "error": "Noto'g'ri so'rov"}
                if result.get("ok"):
                    await manager.broadcast_state(room_id, game)

                    if action == "call_uno":
                        await manager.broadcast_raw(
                            room_id, {"type": "uno_called", "player_id": telegram_id}
                        )
                    elif action == "catch_uno":
                        await manager.broadcast_raw(
                            room_id,
                            {
                                "type": "uno_caught",
                                "catcher_id": telegram_id,
                                "target_id": result.get("caught"),
                                "penalty": result.get("penalty"),
                            },
                        )

                    if game.winner is not None:
                        # game.player_ids ATAYLAB ishlatilyapti (original_player_ids
                        # EMAS) — forfeit qilganlar o'z ballarini disconnect_watcher
                        # orqali allaqachon olib bo'lishgan; bu yerda yana qo'shsak
                        # ikki marta baholangan bo'lardi.
                        apply_game_result(db, game.player_ids, game.winner)
                        finish_room(db, room_id)
                        await manager.broadcast_raw(
                            room_id, {"type": "game_over", "winner": game.winner}
                        )
                        del active_games[room_id]
                else:
                    await manager.send_personal(
                        room_id, telegram_id, {"type": "error", "message": result.get("error")}
                    )

        except WebSocketDisconnect:
            manager.disconnect(room_id, telegram_id, websocket)
            game.mark_disconnected(telegram_id)
            if game.is_disconnected(telegram_id):
                await manager.broadcast_raw(
                    room_id,
                    {
                        "type": "player_disconnected",
                        "player_id": telegram_id,
                        "disconnected_at": game.disconnected_at[telegram_id].isoformat(),
                        "grace_period_seconds": GRACE_PERIOD_SECONDS,
                    },
                )

    finally:
        db_gen.close()


async def disconnect_watcher():
    """Fon vazifasi: har 5 soniyada barcha faol o'yinlarni tekshirib, grace
    period (GameEngine.GRACE_PERIOD_SECONDS) tugagan o'yinchilarni forfeit
    qiladi va ballarni darhol hisoblaydi:

      - Agar forfeit'dan keyin 2+ kishi qolsa: chiquvchi oddiy mag'lubiyat
        kabi ball yo'qotadi, qolganlar RATING_WIN'ni teng bo'lib olishadi
        (apply_forfeit_result).
      - Agar forfeit'dan keyin faqat 1 kishi qolsa: bu — o'yin tugashi,
        oddiy g'alaba kabi baholanadi (apply_game_result), chunki bu
        holatda "bo'lib olish" uchun boshqa hech kim yo'q.

    main.py'da _room_cleanup_loop bilan bir xil naqshda ishga tushiriladi.
    """
    while True:
        await asyncio.sleep(5)
        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                for room_id, game in list(active_games.items()):
                    for player_id in game.get_expired_disconnects():
                        result = game.forfeit_player(player_id)
                        if not result.get("ok"):
                            continue

                        abuse_service.record_forfeit_disconnect(db, player_id)
                        await manager.broadcast_raw(
                            room_id, {"type": "player_forfeited", "player_id": player_id}
                        )

                        if result.get("empty"):
                            finish_room(db, room_id)
                            del active_games[room_id]
                            continue

                        if result.get("winner") is not None:
                            apply_game_result(
                                db, [player_id, result["winner"]], result["winner"], via_forfeit=True
                            )
                            finish_room(db, room_id)
                            await manager.broadcast_raw(
                                room_id, {"type": "game_over", "winner": result["winner"]}
                            )
                            del active_games[room_id]
                        else:
                            apply_forfeit_result(db, player_id, game.player_ids)
                            await manager.broadcast_state(room_id, game)
            finally:
                db_gen.close()
        except Exception:
            logger.exception("disconnect_watcher'da xato yuz berdi")