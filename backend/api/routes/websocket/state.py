"""
WebSocket global runtime state.

Vazifalari:

- ConnectionManager instance
- Active GameEngine registry (room_id -> GameEngine)
- GameEngine yaratish uchun lock
- O'yinni yakunlash uchun lock
- Heartbeat timeout konstantasi
"""

import asyncio

from services.connection_manager import ConnectionManager
from services.game_engine import GameEngine

# Barcha WebSocket ulanishlarini boshqaruvchi yagona instance.
# Boshqa modullar buni faqat shu yerdan import qilsin
# (masalan: `from .state import manager`).
manager: ConnectionManager = ConnectionManager()

# Faol o'yinlar registri.
# Key   -> room_id
# Value -> shu room uchun GameEngine instance
active_games: dict[int, GameEngine] = {}

# GameEngine yaratishda (get_or_create_game / remove_game)
# race condition'dan himoya qiladi.
game_create_lock: asyncio.Lock = asyncio.Lock()

# O'yinni yakunlashda (finish_game / cancel_game)
# race condition'dan himoya qiladi.
game_finish_lock: asyncio.Lock = asyncio.Lock()

# Shuncha soniya ichida klientdan hech narsa kelmasa
# (ping ham), ulanish "jim qolgan" deb hisoblanadi.
HEARTBEAT_TIMEOUT_SECONDS: int = 12