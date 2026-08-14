from threading import RLock

from services.game_engine import GameEngine


class GameManager:
    """
    Barcha faol o'yinlarni boshqaradi.
    Thread-safe ishlaydi.
    """

    def __init__(self) -> None:
        self._games: dict[int, GameEngine] = {}
        self._lock = RLock()

    def exists(self, room_id: int) -> bool:
        with self._lock:
            return room_id in self._games

    def get(self, room_id: int) -> GameEngine | None:
        with self._lock:
            return self._games.get(room_id)

    def create(
        self,
        room_id: int,
        player_ids: list[int],
        player_names: dict[int, str],
    ) -> GameEngine:
        with self._lock:
            game = GameEngine(
                room_id=room_id,
                player_ids=player_ids,
                player_names=player_names,
            )
            self._games[room_id] = game
            return game

    def get_or_create(
        self,
        room_id: int,
        player_ids: list[int],
        player_names: dict[int, str],
    ) -> GameEngine:
        with self._lock:
            game = self._games.get(room_id)

            if game is None:
                game = GameEngine(
                    room_id=room_id,
                    player_ids=player_ids,
                    player_names=player_names,
                )
                self._games[room_id] = game

            return game

    def remove(self, room_id: int) -> None:
        with self._lock:
            self._games.pop(room_id, None)

    def rooms(self) -> list[int]:
        with self._lock:
            return list(self._games.keys())

    def items(self):
        with self._lock:
            return list(self._games.items())

    def clear(self) -> None:
        with self._lock:
            self._games.clear()

    def __contains__(self, room_id: int) -> bool:
        return self.exists(room_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._games)
