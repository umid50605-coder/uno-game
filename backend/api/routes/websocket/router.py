"""
backend/api/routes/websocket/router.py

WebSocket routing layer.
"""

from fastapi import APIRouter, Query, WebSocket

from .handler import websocket_handler

router = APIRouter()


@router.websocket("/ws/rooms/{room_id}")
async def game_websocket(
    websocket: WebSocket,
    room_id: int,
    token: str = Query(...),
) -> None:
    """
    UNO game WebSocket endpoint.
    """

    await websocket_handler(
        websocket=websocket,
        token=token,
        room_id=room_id,
    )