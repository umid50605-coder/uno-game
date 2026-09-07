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


def _get_user_or_404(db: Session, telegram_id: int) -> User:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foydalanuvchi topilmadi")
    return user
