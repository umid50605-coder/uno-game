"""
admin_panel/routers/rooms.py — Xonalar: faol (waiting/playing) xonalarni
ko'rish, kerak bo'lsa qo'lda o'chirish.

Eslatma: Room.join_code bazada ochiq matn sifatida emas, xesh
(masalan SHA-256) ko'rinishida saqlanadi (room_security.py hardening
bosqichida shunday qilingan) — shuning uchun admin panel ham join
kodning o'zini ko'rsata olmaydi va ko'rsatmaydi ham (baribir
qaytarib bo'lmaydi). Faqat xona ochiq/yopiqligi (is_public) ko'rsatiladi.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from admin_panel import audit, config
from admin_panel.admin_db import get_admin_db
from admin_panel.deps import AdminIdentity, get_client_ip, require_admin, verify_csrf
from admin_panel.game_db import Room, RoomStatus, get_game_db

router = APIRouter(prefix="/rooms", tags=["rooms"])
templates = Jinja2Templates(directory=str(config.ADMIN_PANEL_DIR / "templates"))

_STATUS_FILTERS = {
    "active": [RoomStatus.WAITING, RoomStatus.PLAYING],
    "waiting": [RoomStatus.WAITING],
    "playing": [RoomStatus.PLAYING],
    "finished": [RoomStatus.FINISHED],
    "all": [RoomStatus.WAITING, RoomStatus.PLAYING, RoomStatus.FINISHED],
}


@router.get("", response_class=HTMLResponse)
def list_rooms(
    request: Request,
    status_filter: str = "active",
    admin: AdminIdentity = Depends(require_admin),
    db: Session = Depends(get_game_db),
):
    if status_filter not in _STATUS_FILTERS:
        status_filter = "active"

    rooms = db.scalars(
        select(Room)
        .where(Room.status.in_(_STATUS_FILTERS[status_filter]))
        .options(
            selectinload(Room.players),
            selectinload(Room.host),
        )
        .order_by(Room.created_at.desc())
        .limit(200)
    ).all()

    return templates.TemplateResponse(
        request,
        "rooms_list.html",
        {
            "admin": admin,
            "rooms": rooms,
            "status_filter": status_filter,
        },
    )


@router.post("/{room_id}/delete")
def delete_room(
    request: Request,
    room_id: int,
    admin: AdminIdentity = Depends(verify_csrf),
    db: Session = Depends(get_game_db),
    admin_db: Session = Depends(get_admin_db),
):
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Xona topilmadi")

    room_code = room.code
    room_status = room.status.value
    player_count = len(room.players)

    # Room.players relationship'ida cascade="all, delete-orphan" o'rnatilgan,
    # shuning uchun xonani o'chirish shu xonadagi barcha RoomPlayer
    # qatorlarini ham avtomatik o'chiradi. Foydalanuvchi (User) qatorlariga
    # tegilmaydi.
    db.delete(room)
    db.commit()

    audit.log_action(
        admin_db,
        admin_username=admin.username,
        ip_address=get_client_ip(request),
        action="delete_room",
        target=f"room:{room_id} ({room_code})",
        detail=f"status={room_status}, player_count={player_count}",
    )

    return RedirectResponse(url="/rooms", status_code=status.HTTP_303_SEE_OTHER)
