"""
admin_panel/admin_db.py — Admin panelning O'ZIGA TEGISHLI bazasi.

Bu o'yin bazasi (uno.db) bilan HECH QANDAY aloqasi yo'q, butunlay
alohida fayl (admin_panel/admin.db). Shu yerda faqat ikkita narsa
saqlanadi:

  1. AdminLoginAttempt — login urinishlari (brute-force himoyasi uchun)
  2. AdminAuditLog     — admin har safar biror ma'lumotni o'zgartirsa yoki
                          o'chirsa, shu yerga yoziladi (kim, qachon, nima
                          qilgani) — bu "firibgarlardan himoya" talabining
                          bir qismi: agar kimdir admin sessiyasini o'g'irlab
                          olsa ham, nima qilingani doim iz qoldiradi.

Bu fayl o'zining jadvallarini birinchi ishga tushganda avtomatik yaratadi
(Base.metadata.create_all) — bu FAQAT shu alohida admin.db faylga tegishli,
o'yin bazasiga hech qanday ta'sir qilmaydi.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, String, Boolean, create_engine, event, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from admin_panel import config

ADMIN_DB_PATH = config.ADMIN_PANEL_DIR / "admin.db"
ADMIN_DATABASE_URL = f"sqlite:///{ADMIN_DB_PATH}"

admin_engine = create_engine(
    ADMIN_DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 15}
)


@event.listens_for(admin_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


AdminSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=admin_engine)


class AdminBase(DeclarativeBase):
    pass


class AdminLoginAttempt(AdminBase):
    __tablename__ = "admin_login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ip_address: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class AdminAuditLog(AdminBase):
    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_username: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


AdminBase.metadata.create_all(bind=admin_engine)


def get_admin_db() -> Generator[Session, None, None]:
    db = AdminSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Login rate-limiting (brute-force himoyasi)
# ---------------------------------------------------------------------------


def is_ip_rate_limited(db: Session, ip_address: str) -> bool:
    """So'nggi LOGIN_RATE_LIMIT_WINDOW_MINUTES daqiqada shu IP'dan
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS martadan ko'p muvaffaqiyatsiz urinish
    bo'lgan bo'lsa — True qaytaradi (login vaqtincha bloklanadi)."""
    window_start = datetime.now(timezone.utc) - timedelta(
        minutes=config.LOGIN_RATE_LIMIT_WINDOW_MINUTES
    )
    failed_count = db.scalar(
        select(func.count())
        .select_from(AdminLoginAttempt)
        .where(
            AdminLoginAttempt.ip_address == ip_address,
            AdminLoginAttempt.success.is_(False),
            AdminLoginAttempt.attempted_at >= window_start,
        )
    )
    return (failed_count or 0) >= config.LOGIN_RATE_LIMIT_MAX_ATTEMPTS


def record_login_attempt(db: Session, ip_address: str, success: bool) -> None:
    db.add(AdminLoginAttempt(ip_address=ip_address, success=success))
    db.commit()
    if success:
        # Muvaffaqiyatli kirishdan so'ng shu IP uchun eski muvaffaqiyatsiz
        # urinishlar hisoblagichini tozalaymiz — foydalanuvchi to'g'ri parolni
        # kiritganidan keyin ham bloklanib qolmasligi uchun.
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=config.LOGIN_RATE_LIMIT_WINDOW_MINUTES
        )
        db.query(AdminLoginAttempt).filter(
            AdminLoginAttempt.ip_address == ip_address,
            AdminLoginAttempt.success.is_(False),
            AdminLoginAttempt.attempted_at >= window_start,
        ).delete(synchronize_session=False)
        db.commit()
