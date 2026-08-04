"""
core/database.py — SQLAlchemy engine, session factory, va Base klassi.

Stage 14 uchun tekshirildi: disconnect_watcher() va _room_cleanup_loop()
ikkalasi ham har 5 soniyada mustaqil ravishda DB'ga ulanadigan fon
vazifalari — ular + oddiy so'rovlar orasidagi bir vaqtdagi yozishlarni
mavjud WAL rejimi va busy_timeout allaqachon yetarli darajada qamrab oladi,
shuning uchun bu qism o'zgarishsiz qoldi.

Yagona tuzatish: DB_PATH hisoblab chiqarilgan-u, lekin DATABASE_URL undan
foydalanmay, alohida nisbiy yo'l ("./uno.db") bilan yozilgan edi. Bu xavfli —
serverni backend/ papkasidan boshqa joydan ishga tushirsangiz, "./uno.db"
boshqa faylga ishora qiladi va DB_PATH bilan mos kelmay qoladi. Endi
DATABASE_URL DB_PATH'dan olinadi — qayerdan ishga tushirishingizdan qat'iy
nazar, doim aynan shu bitta faylga ishora qiladi.
"""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(__file__).resolve().parent.parent / "uno.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 15}
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """SQLite: bir nechta o'yinchi bir vaqtda yozganda (masalan ikkalasi
    ham "Tayyorman" tugmasini bossa, yoki disconnect_watcher/_room_cleanup_loop
    fon vazifalari oddiy so'rovlar bilan bir vaqtga to'g'ri kelsa) 'database
    is locked' xatosi chiqmasligi uchun WAL rejimini yoqadi va yozish uchun
    kutish vaqtini uzaytiradi."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Har bir so'rov uchun alohida DB session beradi va oxirida yopadi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()