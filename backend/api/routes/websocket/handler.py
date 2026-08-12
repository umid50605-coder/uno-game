"""
WebSocket handler.

backend/api/routes/websocket/handler.py fayli

Vazifalari:
- Ulanish lifecycle'ini boshqarish (orchestration)
- Reconnect / boshlang'ich holatni yuborish uchun initial_state.py'ni chaqirish
- Heartbeat va message loop
- Action dispatch uchun actions.py'ni chaqirish
- Uzilish uchun disconnect.py'ni chaqirish

Bu fayl boshqa modullarning ICHKI logikasini qayta yozmaydi — faqat
"qaysi funksiyani qachon chaqirish kerak"ni hal qiladi.
"""

import asyncio
import logging

from fastapi import (
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import Session

from services.game_engine import GameEngine

from .actions import handle_action
from .disconnect import disconnect_player
from .finish import finish_game
from .game_factory import get_or_create_game
from .initial_state import send_initial_state
from .state import (
    HEARTBEAT_TIMEOUT_SECONDS,
    manager,
)
from .validation import (
    get_room_data,
    validate_user,
)

logger = logging.getLogger(__name__)


async def _safe_close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:
        pass


async def websocket_handler(
    websocket: WebSocket,
    token: str,
    room_id: int,
    db: Session,
) -> None:
    """
    Bitta WebSocket ulanishining butun umrini boshqaradi.
    """

    telegram_id = await validate_user(token)

    if telegram_id is None:
        await _safe_close(websocket, status.WS_1008_POLICY_VIOLATION)
        return

    try:
        room, player_ids = get_room_data(db, room_id, telegram_id)
    except Exception:
        logger.exception(
            "Xona ma'lumotini olishda xato room=%s telegram_id=%s",
            room_id,
            telegram_id,
        )
        await _safe_close(websocket, status.WS_1011_INTERNAL_ERROR)
        return

    if room is None or player_ids is None:
        await _safe_close(
            websocket,
            status.WS_1008_POLICY_VIOLATION,
        )
        return

    try:
        game = await get_or_create_game(
            db=db,
            room_id=room_id,
            player_ids=player_ids,
        )
    except Exception:
        logger.exception(
            "GameEngine yaratishda xato room=%s",
            room_id,
        )
        await _safe_close(websocket, status.WS_1011_INTERNAL_ERROR)
        return

    try:
        await manager.connect(room_id, telegram_id, websocket)
    except WebSocketDisconnect:
        logger.info(
            "Player %s ulanish jarayonida uzildi room=%s",
            telegram_id,
            room_id,
        )
        return
    except Exception:
        logger.exception(
            "WebSocket ulanishda xato player=%s room=%s",
            telegram_id,
            room_id,
        )
        # GameEngine allaqachon yaratilgan bo'lishi mumkin — bu o'yinchini
        # "uzilgan" deb belgilaymiz, shunda disconnect_watcher.py uni
        # o'z vaqtida to'g'ri tozalaydi.
        try:
            game.mark_disconnected(telegram_id)
        except Exception:
            pass
        return

    # MUHIM: pastdagi try blokida hech qanday "return" ISHLATILMAYDI.
    # Sababi: try/except/else'da "else" faqat try bloki ISTISNOSIZ VA
    # ERTA "return"SIZ oxirigacha yetganda ishga tushadi — agar try
    # ichida return bo'lsa, else o'tkazib yuboriladi. Shu bois "forfeit
    # qilingan o'yinchi" holati ham if/else orqali, alohida return'siz
    # ifodalangan — shunda manager.disconnect() HAR DOIM aniq BITTA
    # marta (ikki marta emas, nol marta emas) chaqiriladi:
    #   - WebSocketDisconnect / kutilmagan xato -> disconnect_player()
    #     (bu funksiya manager.disconnect()ni o'zi ham bajaradi)
    #   - boshqa har qanday holat (forfeit qilingan YOKI o'yin
    #     muvaffaqiyatli yakunlangan) -> else -> manager.disconnect()
    try:
        can_continue = await send_initial_state(
            websocket=websocket,
            room_id=room_id,
            telegram_id=telegram_id,
            game=game,
        )

        if can_continue:
            await message_loop(
                websocket=websocket,
                db=db,
                room_id=room_id,
                telegram_id=telegram_id,
                game=game,
            )

    except WebSocketDisconnect:
        logger.info(
            "Player %s disconnected from room %s",
            telegram_id,
            room_id,
        )
        await disconnect_player(
            room_id=room_id,
            telegram_id=telegram_id,
            websocket=websocket,
            game=game,
        )

    except Exception:
        logger.exception(
            "Unexpected websocket error room=%s player=%s",
            room_id,
            telegram_id,
        )
        await disconnect_player(
            room_id=room_id,
            telegram_id=telegram_id,
            websocket=websocket,
            game=game,
        )

    else:
        # Bu yerga ikki holatda kelinadi: (1) o'yinchi forfeit qilingan
        # edi (initial_state.py websocket'ni allaqachon yopgan), yoki
        # (2) message_loop xatosiz tugadi (o'yin g'alaba bilan
        # yakunlandi). Ikkalasi ham "disconnect" emas — shuning uchun
        # disconnect_player() emas, faqat ulanishni manager'dan
        # tozalovchi qism chaqiriladi.
        try:
            manager.disconnect(room_id, telegram_id, websocket)
        except Exception:
            logger.exception(
                "manager.disconnect xatosi room=%s player=%s",
                room_id,
                telegram_id,
            )


async def message_loop(
    *,
    websocket: WebSocket,
    db: Session,
    room_id: int,
    telegram_id: int,
    game: GameEngine,
) -> None:
    """
    Asosiy WebSocket message loop: xabar qabul qilish, heartbeat,
    action dispatch, state broadcast, g'alabani tekshirish.
    """

    while True:

        try:
            data = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=HEARTBEAT_TIMEOUT_SECONDS,
            )

        except asyncio.TimeoutError:
            logger.info(
                "Heartbeat timeout room=%s player=%s",
                room_id,
                telegram_id,
            )
            await _safe_close(websocket, status.WS_1001_GOING_AWAY)
            raise WebSocketDisconnect()

        if not isinstance(data, dict):
            continue

        action = data.get("action")

        if not isinstance(action, str):
            await manager.send_personal(
                room_id,
                telegram_id,
                {
                    "type": "error",
                    "message": "Action noto'g'ri formatda",
                },
            )
            continue

        # heartbeat
        if action == "ping":
            continue

        result = await handle_action(
            game=game,
            telegram_id=telegram_id,
            data=data,
        )

        if not result.get("ok"):
            await manager.send_personal(
                room_id,
                telegram_id,
                {
                    "type": "error",
                    "message": result.get("error"),
                },
            )
            continue

        # O'yin holatini hamma o'yinchiga yuborish
        await manager.broadcast_state(room_id, game)

        # Qo'shimcha eventlar (call_uno / catch_uno)
        await broadcast_action_event(
            room_id=room_id,
            action=action,
            telegram_id=telegram_id,
            result=result,
        )

        # Winner tekshirish
        if game.winner is not None:
            finished = await finish_game(
                db=db,
                room_id=room_id,
                game=game,
                winner=game.winner,
            )

            if finished:
                return


async def broadcast_action_event(
    *,
    room_id: int,
    action: str,
    telegram_id: int,
    result: dict,
) -> None:
    """
    call_uno / catch_uno kabi harakatlar uchun qo'shimcha eventlarni
    broadcast qiladi. Bu yordamchi funksiya handlerni kerak bo'lmagan
    if/elif zanjiridan xoli qilish uchun ajratilgan.
    """

    if action == "call_uno":
        await manager.broadcast_raw(
            room_id,
            {
                "type": "uno_called",
                "player_id": telegram_id,
            },
        )
        return

    if action == "catch_uno":
        await manager.broadcast_raw(
            room_id,
            {
                "type": "uno_caught",
                "catcher_id": telegram_id,
                "target_id": result.get("caught"),
                "penalty": result.get("penalty"),
            },
        )
        