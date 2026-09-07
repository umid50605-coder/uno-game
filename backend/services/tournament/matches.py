import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.room import RoomStatus
from models.tournament import TournamentMatch, TournamentStatus, TournamentRoundStatus

logger = logging.getLogger(__name__)


def _maybe_advance_after_match(db: Session, match: TournamentMatch) -> None:
    """LOCK ICHIDA chaqirilishi shart. Rounddagi barcha matchlar tugadi mi, tekshiradi."""
    from services.tournament.lifecycle import advance_round, finish_tournament

    round_obj = match.round
    db.refresh(round_obj)

    if not all(m.status == RoomStatus.FINISHED for m in round_obj.matches):
        return

    round_obj.status = TournamentRoundStatus.FINISHED
    round_obj.finished_at = datetime.now(timezone.utc)

    tournament = round_obj.tournament
    winners = [m.winner_telegram_id for m in round_obj.matches if m.winner_telegram_id]

    if len(winners) == 0:
        tournament.status = TournamentStatus.CANCELLED
        db.commit()
        logger.warning(
            "Tournament %s CANCELLED: round %s da hech qanday g'olib chiqmadi",
            tournament.id,
            round_obj.round_number,
        )
        return

    db.commit()

    if len(winners) == 1:
        finish_tournament(db, tournament.id, winners[0])
    else:
        advance_round(db, tournament.id, winners)


def handle_tournament_match_finished(db: Session, room_id: int, winner_telegram_id: int) -> None:
    """Turnir xonasi (haqiqiy g'olib bilan) yakunlanganda chaqiriladi."""
    match = db.query(TournamentMatch).filter(TournamentMatch.room_id == room_id).first()
    if match is None:
        return

    tournament_id = match.round.tournament_id
    from services.tournament.locks import _get_tournament_lock

    with _get_tournament_lock(tournament_id):
        db.refresh(match)
        if match.status == RoomStatus.FINISHED:
            return

        match.winner_telegram_id = winner_telegram_id
        match.status = RoomStatus.FINISHED
        match.finished_at = datetime.now(timezone.utc)
        db.flush()
        _maybe_advance_after_match(db, match)


def handle_tournament_match_abandoned(db: Session, room_id: int) -> None:
    """Turnir xonasi g'olibsiz yakunlanganda chaqiriladi."""
    match = db.query(TournamentMatch).filter(TournamentMatch.room_id == room_id).first()
    if match is None:
        return

    tournament_id = match.round.tournament_id
    from services.tournament.locks import _get_tournament_lock

    with _get_tournament_lock(tournament_id):
        db.refresh(match)
        if match.status == RoomStatus.FINISHED:
            return

        match.winner_telegram_id = None
        match.status = RoomStatus.FINISHED
        match.finished_at = datetime.now(timezone.utc)
        db.flush()

        logger.warning("Tournament match room=%s g'olibsiz yakunlandi (abandoned)", room_id)

        _maybe_advance_after_match(db, match)
