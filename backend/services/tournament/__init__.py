"""Tournament business logic package.

This package groups tournament responsibilities by cohesive domain boundaries:
- lifecycle: tournament start/join/cancel/finish flows
- rules: grouping and elimination rules
- matches: round/match progression after game completion
- utils: token/time helpers
- locks: tournament-specific concurrency guard
"""

from .lifecycle import (
    cancel_tournament,
    create_tournament,
    finish_tournament,
    get_tournament,
    join_tournament,
    join_tournament_by_token,
    leave_tournament,
    mark_ready,
    start_tournament,
)
from .matches import handle_tournament_match_abandoned, handle_tournament_match_finished
from .rules import _eliminate_players, _group_players

__all__ = [
    "create_tournament",
    "join_tournament",
    "join_tournament_by_token",
    "leave_tournament",
    "mark_ready",
    "get_tournament",
    "cancel_tournament",
    "start_tournament",
    "finish_tournament",
    "handle_tournament_match_finished",
    "handle_tournament_match_abandoned",
    "_group_players",
    "_eliminate_players",
]
