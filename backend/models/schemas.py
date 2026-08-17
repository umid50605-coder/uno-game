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