"""
backend/core/database.py
core/database.py — SQLAlchemy engine, session factory, va Base klassi.

O'ZGARISH: SQLite'dan Supabase PostgreSQL'ga o'tildi. Endi DATABASE_URL
har doim .env fayl (yoki hosting platformasidagi environment variable)
orqali o'qiladi — hardcoded local fayl yo'q, shuning uchun server qayerda
va qanday ishga tushirilishidan qat'iy nazar bitta doimiy tashqi bazaga
ulanadi.

SQLite-specific narsalar (WAL pragma, check_same_thread, timeout) olib
tashlandi — PostgreSQL bunga muhtoj emas, chunki u haqiqiy concurrent
yozishni serverning o'zida boshqaradi.
"""

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL topilmadi. .env fayliga (yoki hosting platformasi "
        "environment variables bo'limiga) DATABASE_URL=postgresql://... "
        "qatorini qo'shing."
    )

# pool_pre_ping=True: uzoq vaqt ishlatilmagan (masalan Supabase vaqtincha
# uxlab qolgan/tarmoq uzilgan) ulanishlarni avtomatik yangilaydi — aks
# holda "server closed the connection unexpectedly" kabi xatolar chiqishi
# mumkin.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """Har bir so'rov uchun alohida DB session beradi va oxirida yopadi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()