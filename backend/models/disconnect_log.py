"""
backend/models/disconnect_log.py 
Stage 14 — uzilish jurnali (abuse tracking).
Faqat FORFEIT'ga olib kelgan uzilishlar shu yerga yoziladi (oddiy, faqat
qo'shish uchun jurnal). Sliding-window sanoq uchun ishlatiladi — soat
boshida reset bo'ladigan oddiy hisoblagich EMAS.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class DisconnectLog(Base):
    __tablename__ = "disconnect_logs"
    __table_args__ = (
        # Sliding-window so'rovi har doim "shu telegram_id + oxirgi N daqiqa"
        # shaklida bo'ladi — shuning uchun ikkita alohida indeks o'rniga
        # bitta composite indeks samaraliroq.
        Index("ix_disconnect_logs_telegram_id_occurred_at", "telegram_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )