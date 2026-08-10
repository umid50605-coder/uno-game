"""
WebSocket endpoint (routing layer).

Vazifalari:
- FastAPI WebSocket route'ini e'lon qilish
- So'rov parametrlarini olish (token, room_id)
- DB sessiyasi hayot davrini boshqarish
- Haqiqiy ishni handler.websocket_handler()ga topshirish

Bu fayl atayin "ingichka" qilib qoldirilgan — validatsiya, o'yin holati,
xabar loopi kabi hech qanday logika bu yerda emas.
"""

from fastapi import (
    APIRouter,
    Query,
    WebSocket,
)

from api.deps import get_db

from .handler import websocket_handler

router = APIRouter()


@router.websocket("/ws/game")
async def game_websocket(
    websocket: WebSocket,
    token: str = Query(...),
    room_id: int = Query(...),
) -> None:
    """
    O'yin WebSocket endpoint.
    """

    db_gen = get_db()

    try:
        db = next(db_gen)
        await websocket_handler(websocket, token, room_id, db)
    finally:
        try:
            db_gen.close()
        except Exception:
            pass