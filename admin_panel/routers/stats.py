"""
admin_panel/routers/stats.py — Boshqaruv paneli (dashboard): umumiy
statistika. Bu admin panelning bosh sahifasi ("/").
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from admin_panel import config
from admin_panel.deps import AdminIdentity, require_admin
from admin_panel.game_db import DisconnectLog, Room, RoomStatus, User, game_now, get_game_db

router = APIRouter(tags=["stats"])
templates = Jinja2Templates(directory=str(config.ADMIN_PANEL_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
    db: Session = Depends(get_game_db),
):
    now = game_now()
    day_ago = now - timedelta(hours=24)

    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    blacklisted_count = db.scalar(
        select(func.count()).select_from(User).where(User.is_blacklisted.is_(True))
    ) or 0
    locked_count = db.scalar(
        select(func.count()).select_from(User).where(User.locked_until > now)
    ) or 0

    active_rooms_count = db.scalar(
        select(func.count())
        .select_from(Room)
        .where(Room.status.in_([RoomStatus.WAITING, RoomStatus.PLAYING]))
    ) or 0
    finished_rooms_count = db.scalar(
        select(func.count()).select_from(Room).where(Room.status == RoomStatus.FINISHED)
    ) or 0

    total_disconnects = db.scalar(select(func.count()).select_from(DisconnectLog)) or 0
    disconnects_24h = db.scalar(
        select(func.count()).select_from(DisconnectLog).where(DisconnectLog.occurred_at >= day_ago)
    ) or 0

    avg_rating = db.scalar(select(func.avg(User.rating))) or 0

    top_rated = db.scalars(
        select(User).order_by(User.rating.desc()).limit(5)
    ).all()

    # Ko'p marta forfeit qilganlar — reyting bilan suiiste'mol qilish
    # (masalan qasddan uzilib "yutish") ehtimolini ko'rish uchun foydali.
    top_forfeiters = db.scalars(
        select(User).where(User.times_forfeited > 0).order_by(User.times_forfeited.desc()).limit(5)
    ).all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "admin": admin,
            "total_users": total_users,
            "blacklisted_count": blacklisted_count,
            "locked_count": locked_count,
            "active_rooms_count": active_rooms_count,
            "finished_rooms_count": finished_rooms_count,
            "total_disconnects": total_disconnects,
            "disconnects_24h": disconnects_24h,
            "avg_rating": round(avg_rating, 1),
            "top_rated": top_rated,
            "top_forfeiters": top_forfeiters,
        },
    )
