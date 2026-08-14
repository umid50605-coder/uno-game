"""
WebSocket endpoint (routing layer).

backend/api/routes/websocket/router.py

Vazifalari:
- FastAPI WebSocket route'ini e'lon qilish
- token va room_id parametrlarini olish
- Haqiqiy ishni handler.websocket_handler() ga topshirish

Bu faylda:
- authentication yo'q
- DB session yo'q
- game logic yo'q
- message loop yo'q
- disconnect logic yo'q
"""

from fastapi import APIRouter, Query, WebSocket

from .handler import websocket_handler


router = APIRouter()


@router.websocket("/ws/game")
async def game_websocket(
    websocket: WebSocket,
    token: str = Query(...),
    room_id: int = Query(...),
) -> None:
    """
    UNO o'yini uchun WebSocket endpoint.

    Routing qatlamining vazifasi faqat requestni
    websocket_handler() ga topshirish.
    """

    await websocket_handler(
        websocket=websocket,
        token=token,
        room_id=room_id,
    )