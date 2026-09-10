from sqlalchemy.orm import Session, joinedload

from models.room import Room, RoomPlayer
from models.tournament import Tournament


def _tournament_to_dict(tournament: Tournament) -> dict:
    db = Session.object_session(tournament)

    all_room_ids = [m.room_id for r in tournament.rounds for m in r.matches]

    players_by_room_id: dict[int, list[int]] = {}
    if all_room_ids and db is not None:
        rooms = (
            db.query(Room)
            .options(joinedload(Room.players).joinedload(RoomPlayer.user))
            .filter(Room.id.in_(all_room_ids))
            .all()
        )
        for room in rooms:
            players_by_room_id[room.id] = [p.user.telegram_id for p in room.players]

    return {
        "id": tournament.id,
        "creator_telegram_id": tournament.creator_telegram_id,
        "status": tournament.status.value,
        "registration_started_at": tournament.registration_started_at.isoformat() if tournament.registration_started_at else None,
        "registration_expires_at": tournament.registration_expires_at.isoformat() if tournament.registration_expires_at else None,
        "started_at": tournament.started_at.isoformat() if tournament.started_at else None,
        "finished_at": tournament.finished_at.isoformat() if tournament.finished_at else None,
        "current_round": tournament.current_round,
        "participant_count": tournament.participant_count,
        "winner_telegram_id": tournament.winner_telegram_id,
        "reward_points": tournament.reward_points,
        "created_at": tournament.created_at.isoformat() if tournament.created_at else None,
        "players": [
            {
                "telegram_id": p.telegram_id,
                "status": p.status.value,
                "ready": p.ready,
                "joined_at": p.joined_at.isoformat() if p.joined_at else None,
                "eliminated_at": p.eliminated_at.isoformat() if p.eliminated_at else None,
                "eliminated_round": p.eliminated_round,
                "final_position": p.final_position,
            }
            for p in tournament.players
        ],
        "rounds": [
            {
                "id": r.id,
                "round_number": r.round_number,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "matches": [
                    {
                        "id": m.id,
                        "round_id": m.round_id,
                        "room_id": m.room_id,
                        "status": m.status.value,
                        "winner_telegram_id": m.winner_telegram_id,
                        "started_at": m.started_at.isoformat() if m.started_at else None,
                        "finished_at": m.finished_at.isoformat() if m.finished_at else None,
                        "player_telegram_ids": players_by_room_id.get(m.room_id, []),
                    }
                    for m in r.matches
                ],
            }
            for r in tournament.rounds
        ],
    }