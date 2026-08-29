"""
backend/models/schemas.py
"""
from pydantic import BaseModel
from typing import Optional

class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool | None = None
    photo_url: str | None = None


class AuthRequest(BaseModel):
    initData: str


class AuthResponse(BaseModel):
    ok: bool
    token: str
    user: TelegramUser


class UserOut(BaseModel):
    id: int
    telegram_id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool
    photo_url: str | None = None
    games_played: int
    wins: int
    forfeit_wins: int  # Tuzatildi: forfelt_wins -> forfeit_wins
    times_forfeited: int
    rating: int

    model_config = {"from_attributes": True}


class LeaderboardEntry(BaseModel):
    rank: int
    telegram_id: int
    first_name: str
    username: str | None = None
    games_played: int
    wins: int
    forfeit_wins: int
    times_forfeited: int
    rating: int

    model_config = {"from_attributes": True}


class LeaderboardOut(BaseModel):
    top: list[LeaderboardEntry]
    me: LeaderboardEntry | None = None  # hali o'yin o'ynamagan bo'lsa — None


class RoomPlayerOut(BaseModel):
    user_id: int
    telegram_id: int
    first_name: str
    is_ready: bool


class RoomOut(BaseModel):
    id: int
    code: str
    status: str
    max_players: int
    players: list[RoomPlayerOut]
    is_public: bool
    join_code: str | None = None

class CreateRoomRequest(BaseModel):
    is_public: bool = True
    join_code: str | None = None


class JoinRoomRequest(BaseModel):
    join_code: str | None = None

class ReadyRequest(BaseModel):
    ready: bool = True


class LeaveRoomResponse(BaseModel):
    deleted: bool
    room: RoomOut | None = None

# Turnir sxemalari (davomi — file oxiriga qo'shiladi)

class TournamentCreateRequest(BaseModel):
    pass  # hech qanday qo'shimcha ma'lumot kerak emas


class TournamentJoinRequest(BaseModel):
    invite_token: str


class TournamentReadyRequest(BaseModel):
    ready: bool = True


class TournamentPlayerOut(BaseModel):
    telegram_id: int
    status: str
    ready: bool
    joined_at: str | None = None
    eliminated_at: str | None = None
    eliminated_round: int | None = None
    final_position: int | None = None


class TournamentMatchOut(BaseModel):
    id: int
    round_id: int
    room_id: int
    status: str
    winner_telegram_id: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    player_telegram_ids: list[int] = []

class TournamentRoundOut(BaseModel):
    id: int
    round_number: int
    status: str
    created_at: str | None = None
    finished_at: str | None = None
    matches: list[TournamentMatchOut] = []


class TournamentOut(BaseModel):
    id: int
    creator_telegram_id: int
    status: str
    registration_started_at: str | None = None
    registration_expires_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    current_round: int
    participant_count: int
    winner_telegram_id: int | None = None
    reward_points: int
    created_at: str | None = None
    players: list[TournamentPlayerOut] = []
    rounds: list[TournamentRoundOut] = []


class TournamentCreateOut(TournamentOut):
    """create_tournament() javobi uchun — FAQAT shu bir martalik javobda
    invite_token ko'rinadi. Boshqa hech qanday endpoint (GET /tournaments/{id}
    kabi) bu maydonni qaytarmaydi — token qayta tiklanmaydi (faqat DB'da
    hash saqlanadi)."""
    invite_token: str