"""
WebSocket global runtime state.

Vazifalari:

- ConnectionManager instance
- GameManager instance
- Game finish lock
- Heartbeat timeout
"""

import asyncio

from services.connection_manager import ConnectionManager
from services.ws_game_manager import GameManager

manager = ConnectionManager()

game_manager = GameManager()

game_finish_lock = asyncio.Lock()

HEARTBEAT_TIMEOUT_SECONDS = 12