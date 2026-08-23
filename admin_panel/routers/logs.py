"""
admin_panel/routers/logs.py — Disconnect/forfeit jurnali: ko'rish,
bitta yozuvni o'chirish, ommaviy o'chirish (foydalanuvchi bo'yicha yoki
muayyan kundan eskirganlarini tozalash).

DisconnectLog jadvali "faqat qo'shish uchun" jurnal sifatida ishlatiladi
(sliding-window abuse-tracking uchun) — shuning uchun bu yerdagi
o'chirish funksiyalari faqat ADMIN tomonidan qo'lda, ma'lumotlar
bazasini tozalash maqsadida ishlatilishi kerak, avtomatik emas.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from admin_panel import audit, config
from admin_panel.admin_db import get_admin_db
from admin_panel.deps import AdminIdentity, get_client_ip, require_admin, verify_csrf
from admin_panel.game_db import DisconnectLog, User, game_now, get_game_db

router = APIRouter(prefix="/logs", tags=["logs"])
templates = Jinja2Templates(directory=str(config.ADMIN_PANEL_DIR / "templates"))


@router.get("", response_class=HTMLResponse)
def list_logs(
    request: Request,
    telegram_id: str = "",
    page: int = 1,
    admin: AdminIdentity = Depends(require_admin),
    db: Session = Depends(get_game_db),
):
    page = max(page, 1)
    query = select(DisconnectLog)
    count_query = select(func.count()).select_from(DisconnectLog)

    telegram_id = telegram_id.strip()
    filtered_tg_id: int | None = None
    if telegram_id:
        if not telegram_id.lstrip("-").isdigit():
            raise HTTPException(status_code=400, detail="telegram_id butun son bo'lishi kerak")
        filtered_tg_id = int(telegram_id)
        query = query.where(DisconnectLog.telegram_id == filtered_tg_id)
        count_query = count_query.where(DisconnectLog.telegram_id == filtered_tg_id)

    total = db.scalar(count_query) or 0
    offset = (page - 1) * config.PAGE_SIZE
    logs = db.scalars(
        query.order_by(DisconnectLog.occurred_at.desc()).offset(offset).limit(config.PAGE_SIZE)
    ).all()

    # Har bir log yozuvi uchun foydalanuvchi ismini ko'rsatish uchun,
    # sahifadagi barcha telegram_id'larni bitta so'rov bilan olamiz (N+1 emas).
    tg_ids = {log.telegram_id for log in logs}
    users_by_tg_id: dict[int, User] = {}
    if tg_ids:
        found_users = db.scalars(select(User).where(User.telegram_id.in_(tg_ids))).all()
        users_by_tg_id = {u.telegram_id: u for u in found_users}

    has_next = offset + config.PAGE_SIZE < total
    has_prev = page > 1

    return templates.TemplateResponse(
        request,
        "logs_list.html",
        {
            "admin": admin,
            "logs": logs,
            "users_by_tg_id": users_by_tg_id,
            "telegram_id": telegram_id,
            "page": page,
            "has_next": has_next,
            "has_prev": has_prev,
            "total": total,
        },
    )


@router.post("/{log_id}/delete")
def delete_log(
    request: Request,
    log_id: int,
    admin: AdminIdentity = Depends(verify_csrf),
    db: Session = Depends(get_game_db),
    admin_db: Session = Depends(get_admin_db),
):
    log = db.get(DisconnectLog, log_id)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log topilmadi")

    detail = f"telegram_id={log.telegram_id}, occurred_at={log.occurred_at.isoformat()}"
    db.delete(log)
    db.commit()

    audit.log_action(
        admin_db,
        admin_username=admin.username,
        ip_address=get_client_ip(request),
        action="delete_log",
        target=f"disconnect_log:{log_id}",
        detail=detail,
    )
    return RedirectResponse(url="/logs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/delete-bulk")
def delete_logs_bulk(
    request: Request,
    mode: str = Form(...),  # "by_user" | "older_than_days"
    telegram_id: str = Form(""),
    older_than_days: str = Form(""),
    admin: AdminIdentity = Depends(verify_csrf),
    db: Session = Depends(get_game_db),
    admin_db: Session = Depends(get_admin_db),
):
    if mode == "by_user":
        telegram_id = telegram_id.strip()
        if not telegram_id.lstrip("-").isdigit():
            raise HTTPException(status_code=400, detail="telegram_id butun son bo'lishi kerak")
        tg_id = int(telegram_id)
        deleted_count = (
            db.query(DisconnectLog)
            .filter(DisconnectLog.telegram_id == tg_id)
            .delete(synchronize_session=False)
        )
        detail = f"telegram_id={tg_id}"
    elif mode == "older_than_days":
        older_than_days = older_than_days.strip()
        if not older_than_days.isdigit() or int(older_than_days) < 1:
            raise HTTPException(
                status_code=400, detail="Kunlar soni musbat butun son bo'lishi kerak"
            )
        days = int(older_than_days)
        cutoff = game_now() - timedelta(days=days)
        deleted_count = (
            db.query(DisconnectLog)
            .filter(DisconnectLog.occurred_at < cutoff)
            .delete(synchronize_session=False)
        )
        detail = f"older_than_days={days} (cutoff={cutoff.isoformat()})"
    else:
        raise HTTPException(status_code=400, detail="Noto'g'ri rejim")

    db.commit()

    audit.log_action(
        admin_db,
        admin_username=admin.username,
        ip_address=get_client_ip(request),
        action="delete_logs_bulk",
        target=f"disconnect_logs (mode={mode})",
        detail=f"{detail}; deleted_count={deleted_count}",
    )
    return RedirectResponse(url="/logs", status_code=status.HTTP_303_SEE_OTHER)
