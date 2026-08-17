"""
WebSocket handler.

backend/api/routes/websocket/handler.py

Vazifalari:

- WebSocket authentication
- GameEngine olish/yaratish
- ConnectionManager'ga ulash
- Initial state yuborish
- Message loop'ni boshqarish
- Disconnect cleanup
- Game finish'ni chaqirish

Bu fayl boshqa modullarning ichki logikasini bajarmaydi.
U faqat WebSocket lifecycle'ini orchestration qiladi.
"""

import logging

from fastapi import (
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import Session

from services.game_engine import GameEngine
from services.ws_auth import authenticate_websocket

from .actions import handle_action
from .disconnect import disconnect_player
from .finish import finish_game
from .initial_state import send_initial_state
from .state import (
    game_manager,
    manager,
)

logger = logging.getLogger(__name__)


async def _safe_close(
    websocket: WebSocket,
    code: int,
) -> None:
    """WebSocket'ni xavfsiz yopadi."""

    try:
        await websocket.close(code=code)
    except Exception:
        pass


async def websocket_handler(
    websocket: WebSocket,
    token: str,
    room_id: int,
) -> None:
    """
    Bitta WebSocket ulanishining to'liq lifecycle'ini boshqaradi.

    DB session authenticate_websocket() tomonidan yaratiladi
    va auth.db_gen orqali lifecycle oxirida yopiladi.
    """

    auth = await authenticate_websocket(
        websocket=websocket,
        room_id=room_id,
        token=token,
    )

    if auth is None:
        return

    telegram_id = auth.telegram_id
    player_ids = auth.room_player_ids
    player_names = auth.player_names
    db = auth.db

    try:
        # ---------------------------------------------------------
        # 1. GameEngine olish yoki yaratish
        # ---------------------------------------------------------
        try:
            game = game_manager.get_or_create(
                room_id=room_id,
                player_ids=player_ids,
                player_names=player_names,
            )

        except Exception:
            logger.exception(
                "GameEngine olish/yaratishda xato "
                "room=%s player=%s",
                room_id,
                telegram_id,
            )

            await _safe_close(
                websocket,
                status.WS_1011_INTERNAL_ERROR,
            )
            return

        # ---------------------------------------------------------
        # 2. WebSocket connectionni manager'ga qo'shish
        # ---------------------------------------------------------
        try:
            await manager.connect(
                room_id,
                telegram_id,
                websocket,
            )

        except WebSocketDisconnect:
            logger.info(
                "Player %s ulanish vaqtida uzildi room=%s",
                telegram_id,
                room_id,
            )
            return

        except Exception:
            logger.exception(
                "WebSocket ulanishida xato "
                "room=%s player=%s",
                room_id,
                telegram_id,
            )
            return

        # ---------------------------------------------------------
        # 3. Initial state + message loop
        # ---------------------------------------------------------
        try:
            can_continue = await send_initial_state(
                websocket=websocket,
                room_id=room_id,
                telegram_id=telegram_id,
                game=game,
            )

            if not can_continue:
                manager.disconnect(
                    room_id,
                    telegram_id,
                    websocket,
                )
                return

            await message_loop(
                websocket=websocket,
                db=db,
                room_id=room_id,
                telegram_id=telegram_id,
                game=game,
            )

        # ---------------------------------------------------------
        # 4. Haqiqiy disconnect
        # ---------------------------------------------------------
        except WebSocketDisconnect:
            logger.info(
                "Player disconnected "
                "room=%s player=%s",
                room_id,
                telegram_id,
            )

            await disconnect_player(
                room_id=room_id,
                telegram_id=telegram_id,
                websocket=websocket,
                game=game,
            )

        # ---------------------------------------------------------
        # 5. Kutilmagan xato
        # ---------------------------------------------------------
        except Exception:
            logger.exception(
                "Unexpected websocket error "
                "room=%s player=%s",
                room_id,
                telegram_id,
            )

            await disconnect_player(
                room_id=room_id,
                telegram_id=telegram_id,
                websocket=websocket,
                game=game,
            )

        # ---------------------------------------------------------
        # 6. Message loop normal tugagan holat
        # ---------------------------------------------------------
        else:
            try:
                manager.disconnect(
                    room_id,
                    telegram_id,
                    websocket,
                )

            except Exception:
                logger.exception(
                    "manager.disconnect xatosi "
                    "room=%s player=%s",
                    room_id,
                    telegram_id,
                )

    finally:
        # authenticate_websocket() yaratgan DB generatorni yopamiz.
        try:
            auth.db_gen.close()

        except Exception:
            logger.exception(
                "DB generatorni yopishda xato "
                "room=%s player=%s",
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
    Asosiy WebSocket message loop.

    Vazifalari:

    - Client xabarini qabul qilish
    - Heartbeat timeoutni nazorat qilish
    - Action dispatch
    - Game state broadcast
    - Action event broadcast
    - Winner aniqlanganda finish_game() chaqirish
    """

    while True:

        # ---------------------------------------------------------
        # 1. Client xabarini kutish
        # ---------------------------------------------------------
        
        data = await websocket.receive_json()
        # ---------------------------------------------------------
        # 2. Xabar formatini tekshirish
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # 3. Heartbeat
        # ---------------------------------------------------------
        if action == "ping":
            await manager.send_personal(
                room_id,
                telegram_id,
                {
                    "type": "pong",
                },
            )
            continue

        # ---------------------------------------------------------
        # 4. Action dispatch
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # 5. Game state broadcast
        # ---------------------------------------------------------
        await manager.broadcast_state(
            room_id,
            game,
        )

        # ---------------------------------------------------------
        # 6. Maxsus action eventlar
        # ---------------------------------------------------------
        await broadcast_action_event(
            room_id=room_id,
            action=action,
            telegram_id=telegram_id,
            result=result,
        )

        # ---------------------------------------------------------
        # 7. Winner tekshirish
        # ---------------------------------------------------------
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
    call_uno / catch_uno kabi maxsus action eventlarini broadcast qiladi.
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