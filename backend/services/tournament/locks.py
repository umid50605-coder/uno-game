import threading

_tournament_locks: dict[int, threading.Lock] = {}
_tournament_locks_meta_lock = threading.Lock()


def _get_tournament_lock(tournament_id: int) -> threading.Lock:
    with _tournament_locks_meta_lock:
        lock = _tournament_locks.get(tournament_id)
        if lock is None:
            lock = threading.Lock()
            _tournament_locks[tournament_id] = lock
        return lock
