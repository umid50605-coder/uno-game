"""
admin_panel/game_db.py — O'yin (bot) bazasiga ulanish.

MUHIM: bu yerda User/Room/DisconnectLog modellari QAYTA YOZILMAYDI.
Ular to'g'ridan-to'g'ri backend/ papkasidan import qilinadi — shunday
qilib admin panel har doim bot ishlatayotgan aynan bitta haqiqiy sxema
bilan ishlaydi va ikkita joyda saqlanadigan modellar bir-biridan
chetlashib qolish (drift) xavfi umuman yo'q.

backend/ ichidagi modullar bir-birini nisbiy nom bilan import qiladi
(masalan `from core.database import Base`, `from models.user import User`),
ya'ni bot backend/main.py orqali ishga tushganda backend/ papkasining
o'zi sys.path'da bo'ladi. Admin panel alohida jarayon sifatida ishga
tushgani uchun xuddi shu holatni sun'iy ravishda ta'minlaymiz: faqat
backend/ manzilini sys.path boshiga qo'shamiz (import vaqtida bir marta).

Admin panel bu bazaning SXEMASINI HECH QACHON o'zgartirmaydi
(Base.metadata.create_all yoki migratsiya bu yerda chaqirilmaydi) —
faqat mavjud jadvallardagi qatorlarni o'qiydi/yozadi.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from sqlalchemy.orm import Session

from admin_panel import config

_backend_path = str(config.BACKEND_DIR)
if _backend_path not in sys.path:
    sys.path.insert(0, _backend_path)

# noqa: E402 — sys.path sozlangandan keyingina import qilish shart
from backend.core.database import SessionLocal, engine  # noqa: E402
from backend.models.disconnect_log import DisconnectLog  # noqa: E402
from backend.models.room import Room, RoomPlayer, RoomStatus, generate_room_code  # noqa: E402
from backend.models.user import User  # noqa: E402

__all__ = [
    "engine",
    "SessionLocal",
    "get_game_db",
    "User",
    "Room",
    "RoomPlayer",
    "RoomStatus",
    "generate_room_code",
    "DisconnectLog",
]


def get_game_db() -> Generator["Session", None, None]:
    """FastAPI dependency: har bir so'rov uchun alohida DB session, oxirida yopiladi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def game_now():
    """`datetime.now()`ni, DB ustunlaridagi qiymatlar bilan bir xil
    formatda qaytaradi.

    Sabab: backend/core/database.py'dagi modellar sana-vaqtni
    `datetime.now(timezone.utc)` (tzinfo BOR) sifatida yozadi, lekin
    SQLite + SQLAlchemy'ning standart DateTime turi buni saqlashda
    tzinfo'ni saqlab qolmaydi — natijada ORM orqali qayta o'qilganda
    har doim tzinfo YO'Q (naive) obyekt qaytadi (bu haqiqiy loyihada
    tekshirib ko'rildi). Agar shu qiymatni to'g'ridan-to'g'ri
    `datetime.now(timezone.utc)` bilan solishtirsangiz, Python
    "can't compare offset-naive and offset-aware datetimes" xatosini
    beradi.

    Shuning uchun admin panelning butun kodida DB'dan kelgan
    sana-vaqtlar bilan Python darajasida solishtirish kerak bo'lgan
    HAR BIR joyda `datetime.now(timezone.utc)` o'rniga shu funksiya
    ishlatiladi — natija ham tzinfo'siz, lekin qiymati UTC bo'yicha
    hisoblanadi, ya'ni DB'dan kelgan qiymatlar bilan izchil taqqoslanadi.
    (SQL so'rovlaridagi filtrlarga bunday emas — u yerda SQLAlchemy
    ikkala tarafni ham bir xil formatga o'zi keltiradi, shuning uchun
    muammo faqat Python darajasidagi to'g'ridan-to'g'ri taqqoslashda.)
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)
