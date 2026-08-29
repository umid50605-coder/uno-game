"""
backend/api/routes/websocket/router.py

WebSocket routing layer.
"""

from fastapi import APIRouter, Query, WebSocket

from .handler import websocket_handler
from .tournament_ws import tournament_websocket_handler

router = APIRouter()


@router.websocket("/ws/rooms/{room_id}")
async def game_websocket(
    websocket: WebSocket,
    room_id: int,
    token: str = Query(...),
) -> None:
    """UNO game WebSocket endpoint."""
    await websocket_handler(
        websocket=websocket,
        token=token,
        room_id=room_id,
    )


@router.websocket("/ws/tournament/{tournament_id}")
async def tournament_websocket(
    websocket: WebSocket,
    tournament_id: int,
    token: str = Query(...),
) -> None:
    """Tournament lobby/bracket real-time holat kuzatuvi."""
    await tournament_websocket_handler(
        websocket=websocket,
        tournament_id=tournament_id,
        token=token,
    )