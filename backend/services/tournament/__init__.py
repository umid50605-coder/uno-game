"""Tournament business logic package.

This package groups tournament responsibilities by cohesive domain boundaries:
- lifecycle: tournament start/join/cancel/finish flows
- rules: grouping and elimination rules
- matches: match result recording + atomic round/tournament transitions + recovery sweep
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
from .matches import (
    handle_tournament_match_abandoned,
    handle_tournament_match_finished,
    recover_stalled_rounds,
    record_match_result,
)
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
    "record_match_result",
    "recover_stalled_rounds",
    "_group_players",
    "_eliminate_players",
]