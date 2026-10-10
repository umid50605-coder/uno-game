"""
backend/api/routes/websocket/state.py
WebSocket global runtime state.

Vazifalari:
- ConnectionManager instance (rooms uchun HAM, tournamentlar uchun HAM —
  bitta instance, chunki ConnectionManager ikkalasini ham o'zida saqlaydi)
- GameManager instance
- Har bir xona uchun alohida "game finish" lock

DIZAYN CHEKLOVI (audit W-14, SINGLE-WORKER FARAZI):
Bu moduldagi hamma narsa (manager, game_manager, finish lock'lar) PROCESS-LOCAL
— ya'ni faqat bitta Python process xotirasida yashaydi. Shuning uchun
ilova FAQAT bitta worker bilan ishga tushirilishi SHART (backend/Dockerfile'da
`--workers 1` aniq ko'rsatilgan, README'ga qarang). Bir nechta worker/instance
ishlatilsa, bir xonaning GameEngine'i faqat bitta workerda bo'ladi va boshqa
worker uni bilmaydi (broadcast'lar yetib bormaydi, o'yin "yo'qoladi").
Ko'p-instance qo'llab-quvvatlash uchun tashqi holat (Redis/DB) va taqsimlangan
lock kerak bo'ladi — bu hozircha ATAYLAB qo'shilmagan.
"""

import asyncio

from services.connection_manager import ConnectionManager
from services.ws_game_manager import GameManager

manager = ConnectionManager()

game_manager = GameManager()

# Audit F-12: avval bitta global `game_finish_lock = asyncio.Lock()` BARCHA
# xonalar uchun umumiy edi — A xonasining (DB bilan sekin) yakunlanishi B va
# C xonalarning yakunlanishini ham kutdirardi. Endi har bir room_id uchun
# alohida lock: bitta xonadagi ikkita finish/forfeit urinishi baribir
# ketma-ket bajariladi (idempotentlik uchun shu kerak), lekin turli xonalar
# bir-birini kutmaydi.
#
# Barcha murojaatlar asyncio event loop thread'idan bo'ladi, shuning uchun
# dict'ga alohida thread-lock kerak emas.
_game_finish_locks: dict[int, asyncio.Lock] = {}


def get_game_finish_lock(room_id: int) -> asyncio.Lock:
    """room_id uchun finish lock'ni qaytaradi (yo'q bo'lsa yaratadi)."""
    lock = _game_finish_locks.get(room_id)
    if lock is None:
        lock = asyncio.Lock()
        _game_finish_locks[room_id] = lock
    return lock


def discard_game_finish_lock(room_id: int) -> None:
    """O'yin yakunlanib xotiradan olib tashlangach lock yozuvini ham tozalaydi
    (aks holda dict har bir o'ynalgan xona uchun abadiy o'sib borardi).
    Lock'ni kutib turgan boshqa coroutine'lar o'z havolasini saqlab qoladi va
    `game.finished` bayrog'ini ko'rib xavfsiz chiqib ketadi."""
    _game_finish_locks.pop(room_id, None)
