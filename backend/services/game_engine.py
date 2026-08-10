"""
Stage 12/14 — Game Engine
Toza, sinxron UNO o'yin mexanikasi. Bitta xona = bitta GameEngine instansi
(xotirada saqlanadi, DB'ga yozilmaydi).

Stage 14'da qo'shildi:
  - disconnected_at / mark_disconnected / mark_reconnected / is_disconnected /
    get_expired_disconnects — uzilish va grace period kuzatuvi
  - forfeit_player — grace period tugagan o'yinchini o'yindan chiqarib yuboradi
  - get_state endi har bir raqibda "connected" bayrog'ini ham qaytaradi

Reyting (rating_service.py) endi HAR BIR forfeit voqeasida DARHOL hisoblanadi
(o'yin tugashini kutmaydi) — shuning uchun bu klass o'zi ballarni hisoblamaydi,
faqat player_ids'ni to'g'ri holatda saqlaydi (forfeit qilingan zahoti olib
tashlanadi) va chaqiruvchi tomon (routes/game.py) shu ro'yxatdan foydalanadi.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

COLORS = ["red", "yellow", "green", "blue"]
ACTION_VALUES = ["skip", "reverse", "draw2"]
NUMBER_VALUES = [str(n) for n in range(10)]
STACKABLE_VALUES = ("draw2", "wild4")
UNO_PENALTY = 2
GRACE_PERIOD_SECONDS = 30  # uzilgandan keyin qayta ulanish uchun necha soniya kutiladi


@dataclass
class Card:
    color: Optional[str]
    value: str

    def to_dict(self):
        return {"color": self.color, "value": self.value}

    def matches(self, top: "Card", current_color: str) -> bool:
        if self.color is None:
            return True
        if self.color == current_color:
            return True
        if top.color == self.color:
            return True
        if top.value == self.value and self.value not in ("wild", "wild4"):
            return True
        return False


class GameEngineError(Exception):
    pass


@dataclass
class GameEngine:
    room_id: int
    player_ids: list[int]
    player_names: dict[int, str] = field(default_factory=dict)
    hands: dict[int, list[Card]] = field(default_factory=dict)
    draw_pile: list[Card] = field(default_factory=list)
    discard_pile: list[Card] = field(default_factory=list)
    current_index: int = 0
    direction: int = 1
    current_color: str = ""
    winner: Optional[int] = None
    pending_action: Optional[dict] = None
    uno_called: dict[int, bool] = field(default_factory=dict)
    pending_draw: int = 0
    pending_draw_type: Optional[str] = None
    disconnected_at: dict[int, datetime] = field(default_factory=dict)

    def __post_init__(self):
        self.finished = False
        self.draw_pile = self._build_deck()
        random.shuffle(self.draw_pile)
        for pid in self.player_ids:
            self.hands[pid] = [self.draw_pile.pop() for _ in range(7)]
            self.uno_called[pid] = False
        self._flip_first_card()

    # ---------- Setup ----------

    @staticmethod
    def _build_deck() -> list[Card]:
        deck: list[Card] = []
        for color in COLORS:
            deck.append(Card(color, "0"))
            for value in [str(n) for n in range(1, 10)] + ACTION_VALUES:
                deck.append(Card(color, value))
                deck.append(Card(color, value))
        for _ in range(4):
            deck.append(Card(None, "wild"))
            deck.append(Card(None, "wild4"))
        return deck

    def _flip_first_card(self):
        while True:
            card = self.draw_pile.pop()
            if card.value != "wild4":
                self.discard_pile.append(card)
                self.current_color = card.color or random.choice(COLORS)
                break
            self.draw_pile.insert(0, card)
            random.shuffle(self.draw_pile)

    # ---------- Helpers ----------

    def display_name(self, player_id: int) -> str:
        return self.player_names.get(player_id) or f"#{player_id}"

    def _current_player(self) -> int:
        return self.player_ids[self.current_index]

    def _advance_turn(self, steps: int = 1):
        n = len(self.player_ids)
        self.current_index = (self.current_index + self.direction * steps) % n

    def _reshuffle_if_needed(self):
        if not self.draw_pile:
            top = self.discard_pile.pop()
            self.draw_pile = self.discard_pile
            self.discard_pile = [top]
            random.shuffle(self.draw_pile)

    def _draw_n(self, player_id: int, n: int):
        for _ in range(n):
            self._reshuffle_if_needed()
            if self.draw_pile:
                self.hands[player_id].append(self.draw_pile.pop())
        if len(self.hands[player_id]) != 1:
            self.uno_called[player_id] = False

    def _update_uno_flag_after_play(self, player_id: int, called_uno: bool):
        if len(self.hands[player_id]) == 1:
            self.uno_called[player_id] = called_uno
        else:
            self.uno_called[player_id] = False

    # ---------- Public actions ----------

    def play_card(
        self,
        player_id: int,
        card_index: int,
        chosen_color: Optional[str] = None,
        call_uno: bool = False,
    ) -> dict:
        if self.winner is not None or self.finished:
            return {"ok": False, "error": "O'yin allaqachon tugagan"}
        if player_id not in self.player_ids:
            return {"ok": False, "error": "O'yinchi O'yinda emas"}
        if player_id != self._current_player():
            return {"ok": False, "error": "Sizning navbatingiz emas"}

        hand = self.hands[player_id]
        if card_index < 0 or card_index >= len(hand):
            return {"ok": False, "error": "Noto'g'ri karta indeksi"}

        card = hand[card_index]
        top = self.discard_pile[-1]

        if self.pending_draw > 0:
            assert self.pending_draw_type is not None
            if card.value != self.pending_draw_type:
                return {
                    "ok": False,
                    "error": (
                        f"Hozir faqat {self.pending_draw_type.upper()} kartasi bilan "
                        f"javob berish mumkin (yoki torting)"
                    ),
                }
        else:
            if not card.matches(top, self.current_color):
                return {"ok": False, "error": "Bu kartani hozir o'ynab bo'lmaydi"}

        if card.color is None and chosen_color not in COLORS:
            return {"ok": False, "error": "Wild karta uchun rang tanlanishi kerak"}

        hand.pop(card_index)
        self.discard_pile.append(card)
        if card.color is None:
            assert chosen_color is not None
            self.current_color = chosen_color
        else:
            self.current_color = card.color

        if not hand:
            self.winner = player_id
            self.pending_draw = 0
            self.pending_draw_type = None
            return {"ok": True, "winner": player_id}

        self._update_uno_flag_after_play(player_id, call_uno)

        if card.value == "skip":
            self._advance_turn(2)
        elif card.value == "reverse":
            if len(self.player_ids) == 2:
                self._advance_turn(2)
            else:
                self.direction *= -1
                self._advance_turn(1)
        elif card.value in STACKABLE_VALUES:
            add = 2 if card.value == "draw2" else 4
            self.pending_draw += add
            self.pending_draw_type = card.value
            self._advance_turn(1)
        else:
            self._advance_turn(1)

        return {"ok": True}

    def draw_card(self, player_id: int) -> dict:
        if self.winner is not None or self.finished:
            return {"ok": False, "error": "O'yin allaqachon tugagan"}
        if player_id not in self.player_ids:
            return {"ok": False, "error": "O'yinchi O'yinda emas"}
        if player_id != self._current_player():
            return {"ok": False, "error": "Sizning navbatingiz emas"}

        if self.pending_draw > 0:
            n = self.pending_draw
            self._draw_n(player_id, n)
            self.pending_draw = 0
            self.pending_draw_type = None
        else:
            n = 1
            self._draw_n(player_id, n)

        self._advance_turn(1)
        return {"ok": True, "drawn": n}

    def call_uno(self, player_id: int) -> dict:
        if player_id not in self.hands:
            return {"ok": False, "error": "Noma'lum o'yinchi"}
        if len(self.hands[player_id]) != 1:
            return {"ok": False, "error": "Faqat 1 ta karta qolganda 'UNO!' deyish mumkin"}
        self.uno_called[player_id] = True
        return {"ok": True}

    def catch_uno(self, catcher_id: int, target_id: int) -> dict:
        if self.winner is not None or self.finished:
            return {"ok": False, "error": "O'yin allaqachon tugagan"}
        if catcher_id == target_id:
            return {"ok": False, "error": "O'zingizni tuta olmaysiz"}
        if target_id not in self.hands:
            return {"ok": False, "error": "Noma'lum o'yinchi"}
        if len(self.hands[target_id]) != 1:
            return {"ok": False, "error": "Bu o'yinchida aynan 1 ta karta yo'q"}
        if self.uno_called.get(target_id):
            return {"ok": False, "error": "Bu o'yinchi allaqachon 'UNO!' degan"}

        self._draw_n(target_id, UNO_PENALTY)
        return {"ok": True, "caught": target_id, "penalty": UNO_PENALTY}

    # ---------- Disconnect / forfeit (Stage 14) ----------

    def mark_disconnected(self, player_id: int) -> None:
        if self.winner is None and player_id in self.hands:
            self.disconnected_at[player_id] = datetime.now(timezone.utc)

    def mark_reconnected(self, player_id: int) -> None:
        self.disconnected_at.pop(player_id, None)

    def is_disconnected(self, player_id: int) -> bool:
        return player_id in self.disconnected_at

    def get_expired_disconnects(self) -> list[int]:
        """Grace period tugagan, forfeit qilinishi kerak bo'lgan o'yinchilar
        ro'yxatini qaytaradi (o'zi forfeit qilmaydi)."""
        now = datetime.now(timezone.utc)
        return [
            pid for pid, ts in self.disconnected_at.items()
            if (now - ts).total_seconds() >= GRACE_PERIOD_SECONDS
        ]

    def forfeit_player(self, player_id: int) -> dict:
        """Kartalari o'yindan olib tashlanadi (qaytarilmaydi). Aynan uning
        navbati bo'lsa, navbat avtomatik keyingi faol o'yinchiga o'tadi.
        Faqat 1 kishi qolsa, o'sha darhol g'olib deb e'lon qilinadi.

        Chaqiruvchi tomon (routes/game.py) shu funksiya qaytargandan keyin
        self.player_ids'ni o'qib, "kim qoldi" ekanini bilishi mumkin — chunki
        forfeit bo'lgan o'yinchi bu yerda ro'yxatdan allaqachon olib
        tashlangan bo'ladi."""
        if self.winner is not None or player_id not in self.player_ids:
            return {"ok": False}

        idx = self.player_ids.index(player_id)
        was_current = idx == self.current_index

        self.hands.pop(player_id, None)
        self.uno_called.pop(player_id, None)
        self.disconnected_at.pop(player_id, None)
        self.player_ids.remove(player_id)

        if was_current:
            self.pending_draw = 0
            self.pending_draw_type = None

        if not self.player_ids:
            return {"ok": True, "forfeited": player_id, "empty": True}

        if len(self.player_ids) == 1:
            self.winner = self.player_ids[0]
            return {"ok": True, "forfeited": player_id, "winner": self.winner}

        if idx < self.current_index:
            self.current_index -= 1
        self.current_index %= len(self.player_ids)

        return {"ok": True, "forfeited": player_id}

    # ---------- State serialization ----------

    def get_state(self, for_player_id: int) -> dict:
        if for_player_id not in self.hands:
            # Stage 14: forfeit qilingan o'yinchi qaytib ulanishga urinsa
            return {"type": "not_in_game", "room_id": self.room_id}

        return {
            "type": "game_state",
            "room_id": self.room_id,
            "your_hand": [c.to_dict() for c in self.hands[for_player_id]],
            "your_uno_called": self.uno_called.get(for_player_id, False),
            "opponents": [
                {
                    "player_id": pid,
                    "name": self.display_name(pid),
                    "card_count": len(self.hands[pid]),
                    "uno_called": self.uno_called.get(pid, False),
                    "catchable": len(self.hands[pid]) == 1 and not self.uno_called.get(pid, False),
                    "connected": pid not in self.disconnected_at,
                }
                for pid in self.player_ids
                if pid != for_player_id
            ],
            "top_card": self.discard_pile[-1].to_dict(),
            "current_color": self.current_color,
            "current_player": self._current_player(),
            "direction": self.direction,
            "draw_pile_count": len(self.draw_pile),
            "pending_draw": self.pending_draw,
            "pending_draw_type": self.pending_draw_type,
            "winner": self.winner,
        }