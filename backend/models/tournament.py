"""
backend/models/tournament.py
"""
import enum
from datetime import datetime, timezone, timedelta

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from models.room import RoomStatus


class TournamentStatus(str, enum.Enum):
    REGISTRATION = "registration"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class TournamentPlayerStatus(str, enum.Enum):
    ACTIVE = "active"
    ELIMINATED = "eliminated"
    WINNER = "winner"


class TournamentRoundStatus(str, enum.Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    creator_telegram_id: Mapped[int] = mapped_column(
        ForeignKey("users.telegram_id"), nullable=False
    )
    invite_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[TournamentStatus] = mapped_column(
        Enum(TournamentStatus), default=TournamentStatus.REGISTRATION, nullable=False
    )
    registration_started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    registration_expires_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc) + timedelta(seconds=60)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    participant_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    winner_telegram_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.telegram_id"), nullable=True
    )
    reward_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    players: Mapped[list["TournamentPlayer"]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )
    rounds: Mapped[list["TournamentRound"]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"
    __table_args__ = (
        UniqueConstraint("tournament_id", "telegram_id", name="uq_tournament_player"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"), nullable=False)
    status: Mapped[TournamentPlayerStatus] = mapped_column(
        Enum(TournamentPlayerStatus), default=TournamentPlayerStatus.ACTIVE, nullable=False
    )
    ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    eliminated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    eliminated_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tournament: Mapped["Tournament"] = relationship(back_populates="players")


class TournamentRound(Base):
    __tablename__ = "tournament_rounds"
    __table_args__ = (
        UniqueConstraint("tournament_id", "round_number", name="uq_tournament_round"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TournamentRoundStatus] = mapped_column(
        Enum(TournamentRoundStatus), default=TournamentRoundStatus.WAITING, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tournament: Mapped["Tournament"] = relationship(back_populates="rounds")
    matches: Mapped[list["TournamentMatch"]] = relationship(
        back_populates="round", cascade="all, delete-orphan"
    )


class TournamentMatch(Base):
    __tablename__ = "tournament_matches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("tournament_rounds.id"), nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    status: Mapped[RoomStatus] = mapped_column(
        Enum(RoomStatus), default=RoomStatus.WAITING, nullable=False
    )
    winner_telegram_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.telegram_id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    round: Mapped["TournamentRound"] = relationship(back_populates="matches")