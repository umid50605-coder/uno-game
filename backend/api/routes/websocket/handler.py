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

DB SESSION (audit F-11): bu fayl hech qanday DB Session ushlab turmaydi.
Autentifikatsiya qisqa muddatli sessiyada bajarilib yopiladi; o'yin
yakunlash kabi DB amallari finish.py ichida o'zining sessiyasini ochadi.

STALE SOCKET (audit F-10): o'yinchi qayta ulanganda manager yangi socketni
eskisi ustiga yozadi, lekin eski socketning message_loop'i ishlashda davom
etishi mumkin. message_loop har bir xabarni qayta ishlashdan OLDIN socket
hanuz joriy ekanini tekshiradi; eskirgan bo'lsa — hech narsa bajarmasdan
yopiladi va yangi/joriy ulanishga tegilmaydi. Bu authorization emas
(token baribir tekshirilgan), balki concurrency/stale-connection himoyasi.
"""

import asyncio
import logging

from fastapi import (
    WebSocket,
    WebSocketDisconnect,
    status,
)

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

# Client har 5 soniyada "ping" yuborishi kutiladi (ws-client.js). Agar
# undan 4 barobar ko'proq vaqt (20s) davomida HECH QANDAY xabar kelmasa,
# bu ulanishni "texnik jihatdan o'lik" deb hisoblaymiz — masalan tarmoq
# transport darajasida ochiq ko'rinsa-yu, lekin client uzoq vaqt hech
# narsa yubormasa (TCP keepalive standart sozlamalari bunday holatni
# juda kech aniqlashi mumkin).
IDLE_TIMEOUT_SECONDS = 20

# Eskirgan (yangi ulanish bilan almashtirilgan) socketni yopishda ishlatiladigan
# application-darajasidagi close code (4000-4999 oralig'i ilovaga ajratilgan).
WS_CLOSE_REPLACED = 4001


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

    Hech qanday DB session ushlab turilmaydi (authenticate_websocket()
    sessiyani o'zi yopib bo'lgan).
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
    # 6. Message loop normal tugagan holat (o'yin yakunlandi yoki
    #    socket eskirgan). manager.disconnect() socket identity'sini
    #    tekshiradi, shuning uchun eskirgan socket yangi/joriy
    #    ulanishni o'chirib yubora olmaydi.
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


async def _reject_if_stale(
    *,
    websocket: WebSocket,
    room_id: int,
    telegram_id: int,
) -> bool:
    """Audit F-10: shu socket hanuz o'yinchining JORIY ulanishimi?

    Joriy bo'lmasa (o'yinchi yangi socket bilan qayta ulangan) — socketni
    yopadi va True qaytaradi: chaqiruvchi hech narsa qayta ishlamasdan
    loop'dan chiqishi kerak. Yangi/joriy socketga TEGILMAYDI (xabar yuborilmaydi,
    manager yozuvi o'zgarmaydi)."""
    if manager.is_current(room_id, telegram_id, websocket):
        return False

    logger.warning(
        "Eskirgan (stale) socket xabari rad etildi room=%s player=%s",
        room_id,
        telegram_id,
    )
    await _safe_close(websocket, WS_CLOSE_REPLACED)
    return True


async def message_loop(
    *,
    websocket: WebSocket,
    room_id: int,
    telegram_id: int,
    game: GameEngine,
) -> None:
    """
    Asosiy WebSocket message loop.

    Vazifalari:

    - Client xabarini qabul qilish
    - Heartbeat timeoutni nazorat qilish
    - Eskirgan (stale) socketni aniqlash va to'xtatish
    - Action dispatch
    - Game state broadcast
    - Action event broadcast
    - Winner aniqlanganda finish_game() chaqirish
    """

    while True:

        # ---------------------------------------------------------
        # 1. Client xabarini kutish (idle timeout + JSON validatsiya bilan)
        # ---------------------------------------------------------
        try:
            data = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=IDLE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # TUZATILDI (MEDIUM — server-side idle enforcement yo'qligi):
            # avval faqat client o'zi heartbeat yubormasa aniqlanardi.
            # Endi server ham mustaqil ravishda uzoq sukut saqlagan
            # ulanishlarni yopadi.
            logger.warning(
                "WS idle timeout (%ss) room=%s player=%s",
                IDLE_TIMEOUT_SECONDS,
                room_id,
                telegram_id,
            )
            await _safe_close(websocket, status.WS_1000_NORMAL_CLOSURE)
            raise WebSocketDisconnect(code=status.WS_1000_NORMAL_CLOSURE)
        except ValueError:
            # Eskirgan socketning noto'g'ri JSON'iga javob JORIY socketga
            # (manager player_id bo'yicha topadi) ketib qolmasligi kerak.
            if await _reject_if_stale(
                websocket=websocket,
                room_id=room_id,
                telegram_id=telegram_id,
            ):
                return
            # TUZATILDI (MEDIUM — noto'g'ri JSON butun ulanishni yiqitardi):
            # avval JSON dekodlash xatosi shu funksiyaning ichida
            # tutilmasdi va websocket_handler'ning umumiy
            # except Exception blokiga tushib, ulanishni oddiy disconnect
            # sifatida yopib yuborardi (player_disconnected broadcast
            # qilib, grace period boshlab). Endi faqat shu bitta noto'g'ri
            # xabar rad etiladi, ulanish davom etadi.
            await manager.send_personal(
                room_id,
                telegram_id,
                {
                    "type": "error",
                    "message": "Xabar formati noto'g'ri (JSON emas)",
                },
            )
            continue

        # ---------------------------------------------------------
        # 1.5 Eskirgan (stale) socket tekshiruvi — ping'dan ham OLDIN:
        #     eskirgan socket pong ham, action ham ola olmaydi.
        # ---------------------------------------------------------
        if await _reject_if_stale(
            websocket=websocket,
            room_id=room_id,
            telegram_id=telegram_id,
        ):
            return

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
                room_id=room_id,
                game=game,
                winner=game.winner,
            )

            # `game.finished` ham tekshiriladi: finish disconnect_watcher
            # (qayta yakunlash) tomonidan allaqachon bajarilgan bo'lishi
            # mumkin — u holda bu loop'ning davom etishi ma'nosiz.
            # Agar finish muvaffaqiyatsiz bo'lsa (game.finished False),
            # watcher uni keyingi siklda qayta uradi.
            if finished or game.finished:
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