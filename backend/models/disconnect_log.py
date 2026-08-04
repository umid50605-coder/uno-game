"""
Stage 14 — uzilish jurnali (abuse tracking).
Faqat FORFEIT'ga olib kelgan uzilishlar shu yerga yoziladi (oddiy, faqat
qo'shish uchun jurnal). Sliding-window sanoq uchun ishlatiladi — soat
boshida reset bo'ladigan oddiy hisoblagich EMAS.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class DisconnectLog(Base):
    __tablename__ = "disconnect_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )