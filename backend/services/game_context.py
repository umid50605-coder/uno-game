"""
IXTIYORIY (tasdiqlanmagan) — GameContext.

api/routes/websocket/ ichidagi handler.py/actions.py bitta WebSocket
action davomida odatda bir nechta bog'liqlikni birga uzatadi:
room_id, telegram_id, GameEngine instansi, DB Session, ConnectionManager.
Shularni bitta joyga yig'ish uchun shu klass mo'ljallangan.

Bu klass SOF DATA HOLDER — hech qanday logika, hech qanday I/O
bajarmaydi, hech narsani commit/broadcast qilmaydi. Shu sababli u
boshqa hech bir faylni "duplicate" qila olmaydi; faqat handler.py
buni qabul qilishga tayyor bo'lsagina foydali.

TASDIQLANMAGAN: handler.py 8-avgustda yozilgan, lekin uning hozirgi
kontenti bu suhbatda yo'q — shuning uchun bu klass haqiqatan zarurligini
tasdiqlab bo'lmaydi. Agar handler.py hozir shu 5 ta qiymatni
alohida-alohida parametr sifatida uzatib muammosiz ishlayotgan bo'lsa,
bu faylni ishlatmasangiz ham bo'ladi — shunchaki bo'sh qoldiring.
handler.py'ni yuborsangiz, kerak-keraksizligini aniq aytib beraman.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from services.connection_manager import ConnectionManager
from services.game_engine import GameEngine


@dataclass(slots=True)
class GameContext:
    room_id: int
    telegram_id: int
    game: GameEngine
    db: Session
    manager: ConnectionManager