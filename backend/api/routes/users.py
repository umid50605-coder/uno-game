"""
backend/api/routes/users.py 
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_current_user_id, get_db
from models.schemas import LeaderboardEntry, LeaderboardOut, UserOut
from models.user import User

router = APIRouter(prefix="/me", tags=["users"])

# Leaderboard "/me" ostiga emas — alohida (prefikssiz) router sifatida,
# chunki u aynan shu foydalanuvchiga emas, hammaga tegishli ma'lumot.
# main.py'da: app.include_router(users.leaderboard_router)
leaderboard_router = APIRouter(tags=["leaderboard"])

TOP_N = 5  # lobby ekranidagi jadvalda ko'rinadigan yuqori o'rinlar soni


@router.get("", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


def _to_entry(user: User, rank: int) -> LeaderboardEntry:
    return LeaderboardEntry(
        rank=rank,
        telegram_id=user.telegram_id,
        first_name=user.first_name,
        username=user.username,
        games_played=user.games_played,
        wins=user.wins,
        forfeit_wins=user.forfeit_wins,  # YANGI
        times_forfeited=user.times_forfeited,  # YANGI
        rating=user.rating,
    )


@leaderboard_router.get("/leaderboard", response_model=LeaderboardOut)
async def leaderboard(
    db: Session = Depends(get_db),
    telegram_id: int = Depends(get_current_user_id),
) -> LeaderboardOut:
    """Yuqori TOP_N o'rin + so'rovchining haqiqiy o'rni (top ro'yxatda
    bo'lmasa ham — 6, 23, 104... qanday bo'lsa shunday qaytadi).
    Hali birorta o'yin o'ynamagan bo'lsa, `me` — None."""
    ranked = (
        db.query(User)
        .filter(User.games_played > 0)
        .order_by(User.rating.desc(), User.id.asc())
        .all()
    )

    top = [_to_entry(u, i + 1) for i, u in enumerate(ranked[:TOP_N])]

    me = next(
        (_to_entry(u, i + 1) for i, u in enumerate(ranked) if u.telegram_id == telegram_id),
        None,
    )

    return LeaderboardOut(top=top, me=me)