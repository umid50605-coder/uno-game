"""
backend/api/routes/game.py

UNO Game WebSocket Router

Bu fayl faqat WebSocket endpoint'larini ro'yxatdan o'tkazadi.
Barcha biznes logika websocket paketiga ajratilgan.
"""

from fastapi import APIRouter, Query, WebSocket

from api.routes.websocket.handler import websocket_handler


router = APIRouter()


@router.websocket("/ws/game")
async def game_websocket(
    websocket: WebSocket,
    token: str = Query(...),
    room_id: int = Query(...),
):
    """
    UNO Game WebSocket endpoint.
    """

    await websocket_handler(
        websocket=websocket,
        token=token,
        room_id=room_id,
    )