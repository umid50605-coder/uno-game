"""Compatibility facade for tournament service.

The public API remains stable while the implementation lives in the
responsibility-oriented modules under `services/tournament/`.
"""

from services.tournament.lifecycle import (
    IDEAL_MATCH_SIZE,
    MIN_TOURNAMENT_PLAYERS,
    REWARD_PER_PARTICIPANT,
    REGISTRATION_SECONDS,
    _cancel_active_matches_for_tournament,
    advance_round,
    cancel_tournament,
    create_round,
    create_tournament,
    finish_tournament,
    get_tournament,
    join_tournament,
    join_tournament_by_token,
    leave_tournament,
    mark_ready,
    start_tournament,
)
from services.tournament.locks import _get_tournament_lock
from services.tournament.matches import (
    handle_tournament_match_abandoned,
    handle_tournament_match_finished,
)
from services.tournament.rules import _eliminate_players, _group_players
from services.tournament.utils import (
    _as_aware_utc,
    _generate_invite_token,
    _hash_token,
    _utc_now,
)

__all__ = [
    "REGISTRATION_SECONDS",
    "MIN_TOURNAMENT_PLAYERS",
    "IDEAL_MATCH_SIZE",
    "REWARD_PER_PARTICIPANT",
    "create_tournament",
    "join_tournament",
    "join_tournament_by_token",
    "leave_tournament",
    "mark_ready",
    "get_tournament",
    "cancel_tournament",
    "start_tournament",
    "create_round",
    "advance_round",
    "finish_tournament",
    "handle_tournament_match_finished",
    "handle_tournament_match_abandoned",
    "_get_tournament_lock",
    "_get_user_or_404",
    "_get_tournament_or_404",
    "_generate_invite_token",
    "_hash_token",
    "_utc_now",
    "_as_aware_utc",
    "_group_players",
    "_eliminate_players",
    "_cancel_active_matches_for_tournament",
]

# Compatibility imports kept for older direct accesses.
from services.tournament.validators import _get_tournament_or_404, _get_user_or_404
