import logging
from typing import List

from models.tournament import Tournament, TournamentPlayerStatus

logger = logging.getLogger(__name__)


def _group_players(player_ids: List[int]) -> List[List[int]]:
    """n >= 2 bo'lganda taxminiy guruhlash."""
    from services.tournament.lifecycle import IDEAL_MATCH_SIZE

    n = len(player_ids)
    k = (n + IDEAL_MATCH_SIZE - 1) // IDEAL_MATCH_SIZE
    base = n // k
    rem = n % k
    groups = []
    idx = 0
    for i in range(k):
        size = base + (1 if i < rem else 0)
        groups.append(player_ids[idx : idx + size])
        idx += size
    return groups


def _eliminate_players(
    tournament: Tournament,
    telegram_ids: list[int],
    round_number: int,
    reason: str,
) -> None:
    if not telegram_ids:
        return
    from services.tournament.utils import _utc_now

    now = _utc_now()
    id_set = set(telegram_ids)
    for p in tournament.players:
        if p.telegram_id in id_set and p.status == TournamentPlayerStatus.ACTIVE:
            p.status = TournamentPlayerStatus.ELIMINATED
            p.eliminated_round = round_number
            p.eliminated_at = now
    logger.info(
        "Tournament %s: %s sababli eliminatsiya qilindi (round=%s): %s",
        tournament.id,
        reason,
        round_number,
        telegram_ids,
    )