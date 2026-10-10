from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from models.tournament import Tournament, TournamentMatch, TournamentRound
from models.user import User


def _get_tournament_or_404(db: Session, tournament_id: int) -> Tournament:
    tournament = (
        db.query(Tournament)
        .options(
            joinedload(Tournament.players),
            joinedload(Tournament.rounds).joinedload(TournamentRound.matches).joinedload(TournamentMatch.round),
        )
        .filter(Tournament.id == tournament_id)
        .first()
    )
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turnir topilmadi")
    return tournament


def _get_tournament_for_update(db: Session, tournament_id: int) -> Tournament:
    """Tournament qatorini DB darajasida qulflaydi (SELECT ... FOR UPDATE) va
    yangi holatda qaytaradi.

    Nima uchun kerak (audit F-04/F-08): process-local threading.RLock faqat
    BITTA process ichida himoya qiladi. Status o'tishlari (round tugashi,
    turnir yakunlanishi va reward berish) DB qatori qulflangan holatda
    bajarilsa, bir vaqtning o'zida ikki thread/process bir xil o'tishni
    ikki marta bajara olmaydi — ikkinchisi birinchisi commit qilguncha
    kutadi, so'ng YANGI statusni ko'rib, o'tishni o'tkazib yuboradi.

    MUHIM: bu funksiya faqat tournament_lock (RLock) USHLAB TURILGAN holatda
    chaqirilishi kerak — qulf tartibi har doim 'RLock -> DB qatori'. Shu
    tartib bo'lmasa deadlock xavfi tug'iladi.

    FOR UPDATE alohida oddiy so'rovda bajariladi (joinedload'li so'rovda emas),
    chunki PostgreSQL FOR UPDATE'ni LEFT OUTER JOIN'ning nullable tomoniga
    qo'llashga ruxsat bermaydi."""
    locked = (
        db.query(Tournament)
        .filter(Tournament.id == tournament_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if locked is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turnir topilmadi")
    return _get_tournament_or_404(db, tournament_id)


def _get_user_or_404(db: Session, telegram_id: int) -> User:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foydalanuvchi topilmadi")
    return user