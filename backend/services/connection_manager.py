"""
backend/services/connection_manager.py
Stage 13-14 — WebSocket Connection Manager

Stage 14'da qo'shildi:
  - disconnect() endi websocket obyektini ham tekshiradi — agar o'yinchi
    tezroq qayta ulangan bo'lsa-yu, ESKI ulanishning WebSocketDisconnect'i
    keyinroq kelsa, endi u yangi (joriy) ulanishni bekor qilib qo'ymaydi.
  - broadcast_state/broadcast_raw/send_personal endi har bir yuborishni
    try/except bilan o'raydi — bitta o'lik socket butun xona uchun
    broadcast'ni to'xtatib qo'ymasin (disconnect_watcher fon vazifasi uchun
    ham muhim).

Tournament qo'shildi:
  - self.tournaments: dict[int, dict[int, WebSocket]] — tournament_id bo'yicha
    kalitlangan, alohida keyspace (rooms bilan aralashmaydi, chunki room_id
    va tournament_id bir xil raqamlar bo'lishi mumkin).
  - MUHIM: bu klassning YAGONA instance'i backend/api/routes/websocket/state.py
    ichida yaratiladi (`manager = ConnectionManager()`). Boshqa hech qayerda
    `ConnectionManager()` chaqirilmasin — aks holda room broadcast va
    tournament broadcast turli xotira maydonlariga bo'linib ketadi.
"""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.rooms: dict[int, dict[int, WebSocket]] = {}
        self.tournaments: dict[int, dict[int, WebSocket]] = {}

    # ---------------- Room (game) connections ----------------

    async def connect(self, room_id: int, player_id: int, websocket: WebSocket):
        await websocket.accept()
        self.rooms.setdefault(room_id, {})[player_id] = websocket

    def disconnect(self, room_id: int, player_id: int, websocket: WebSocket | None = None):
        bucket = self.rooms.get(room_id)
        if bucket is None:
            return
        if websocket is not None and bucket.get(player_id) is not websocket:
            return  # bu o'yinchi allaqachon YANGI socket bilan qayta ulangan
        bucket.pop(player_id, None)
        if not bucket:
            del self.rooms[room_id]

    async def send_personal(self, room_id: int, player_id: int, message: dict):
        bucket = self.rooms.get(room_id)
        if bucket is None:
            return
        ws = bucket.get(player_id)
        if ws is None:
            return
        try:
            await ws.send_json(message)
        except Exception:
            self.disconnect(room_id, player_id, ws)

    async def broadcast_state(self, room_id: int, game_engine, exclude: int | None = None):
        bucket = self.rooms.get(room_id, {})
        dead: list[tuple[int, WebSocket]] = []
        for player_id, ws in list(bucket.items()):
            if player_id == exclude:
                continue
            state = game_engine.get_state(player_id)
            try:
                await ws.send_json(state)
            except Exception:
                dead.append((player_id, ws))
        for player_id, ws in dead:
            self.disconnect(room_id, player_id, ws)

    async def broadcast_raw(self, room_id: int, message: dict):
        bucket = self.rooms.get(room_id, {})
        dead: list[tuple[int, WebSocket]] = []
        for player_id, ws in list(bucket.items()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append((player_id, ws))
        for player_id, ws in dead:
            self.disconnect(room_id, player_id, ws)

    def is_connected(self, room_id: int, player_id: int) -> bool:
        return player_id in self.rooms.get(room_id, {})

    # ---------------- Tournament connections ----------------

    async def connect_tournament(self, tournament_id: int, player_id: int, websocket: WebSocket):
        await websocket.accept()
        self.tournaments.setdefault(tournament_id, {})[player_id] = websocket

    def disconnect_tournament(self, tournament_id: int, player_id: int, websocket: WebSocket | None = None):
        bucket = self.tournaments.get(tournament_id)
        if bucket is None:
            return
        if websocket is not None and bucket.get(player_id) is not websocket:
            return
        bucket.pop(player_id, None)
        if not bucket:
            del self.tournaments[tournament_id]

    async def send_to_tournament(self, tournament_id: int, player_id: int, message: dict):
        bucket = self.tournaments.get(tournament_id)
        if bucket is None:
            return
        ws = bucket.get(player_id)
        if ws is None:
            return
        try:
            await ws.send_json(message)
        except Exception:
            self.disconnect_tournament(tournament_id, player_id, ws)

    async def broadcast_to_tournament(self, tournament_id: int, message: dict):
        bucket = self.tournaments.get(tournament_id, {})
        dead: list[tuple[int, WebSocket]] = []
        for player_id, ws in list(bucket.items()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append((player_id, ws))
        for player_id, ws in dead:
            self.disconnect_tournament(tournament_id, player_id, ws)

    def is_connected_tournament(self, tournament_id: int, player_id: int) -> bool:
        return player_id in self.tournaments.get(tournament_id, {})