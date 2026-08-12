"""
Stage 13-14 — WebSocket Connection Manager

Stage 14'da qo'shildi:
  - disconnect() endi websocket obyektini ham tekshiradi — agar o'yinchi
    tezroq qayta ulangan bo'lsa-yu, ESKI ulanishning WebSocketDisconnect'i
    keyinroq kelsa, endi u yangi (joriy) ulanishni bekor qilib qo'ymaydi.
  - broadcast_state/broadcast_raw/send_personal endi har bir yuborishni
    try/except bilan o'raydi — bitta o'lik socket butun xona uchun
    broadcast'ni to'xtatib qo'ymasin (disconnect_watcher fon vazifasi uchun
    ham muhim).
"""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.rooms: dict[int, dict[int, WebSocket]] = {}

    async def connect(self, room_id: int, player_id: int, websocket: WebSocket):
        await websocket.accept()
        self.rooms.setdefault(room_id, {})[player_id] = websocket

    def disconnect(self, room_id: int, player_id: int, websocket: WebSocket | None = None):
        room = self.rooms.get(room_id)
        if room is None:
            return
        if websocket is not None and room.get(player_id) is not websocket:
            return  # bu o'yinchi allaqachon YANGI socket bilan qayta ulangan
        room.pop(player_id, None)
        if not room:
            del self.rooms[room_id]

    async def send_personal(self, room_id: int, player_id: int, message: dict):
        ws = self.rooms.get(room_id, {}).get(player_id)
        if ws is not None:
            try:
                await ws.send_json(message)
            except Exception:
                pass

    async def broadcast_state(self, room_id: int, game_engine, exclude: int | None = None):
        room = self.rooms.get(room_id, {})
        dead: list[int] = []
        for player_id, ws in list(room.items()):
            if player_id == exclude:
                continue
            state = game_engine.get_state(player_id)
            try:
                await ws.send_json(state)
            except Exception as e:
                print(f"[WS] SEND ERROR {player_id}: {e}")
                dead.append(player_id)
        for player_id in dead:
            room.pop(player_id, None)

    async def broadcast_raw(self, room_id: int, message: dict):
        room = self.rooms.get(room_id, {})
        dead: list[int] = []
        for player_id, ws in list(room.items()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(player_id)
        for player_id in dead:
            room.pop(player_id, None)

    def is_connected(self, room_id: int, player_id: int) -> bool:
        return player_id in self.rooms.get(room_id, {})
 