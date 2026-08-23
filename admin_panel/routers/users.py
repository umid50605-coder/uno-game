"""
admin_panel/routers/users.py — Foydalanuvchilar: ro'yxat, qidiruv,
tafsilotlar, qo'lda unlock, blacklist holatini almashtirish va
ruxsat berilgan maydonlarni tahrirlash.

Xavfsizlik: tahrirlash faqat quyida aniq ro'yxatlangan (whitelist)
maydonlar bilan cheklangan. Hech qanday "erkin maydon nomi + qiymat"
turidagi umumiy edit yo'q — bu noto'g'ri/yot maydonni yozib
yuborishning yoki SQL in'ektsiya("column name") turidagi xatoning
oldini oladi. Barcha so'rovlar SQLAlchemy ORM orqali, parametrlashtirilgan
holda bajariladi — xom (raw) SQL umuman ishlatilmaydi.

Butun sonlar bo'yicha himoya: foydalanuvchidan keladigan har qanday
son (path/query/form) DB ustuniga yetib borishidan oldin ustun
kengligiga mos chegarada tekshiriladi (id — 32-bit, telegram_id —
64-bit deb qabul qilingan). Bundan tashqari, DB darajasida kutilmagan
xato (masalan taxmin qilingan ustun kengligi noto'g'ri bo'lib chiqsa)
try/except bilan tutib olinadi va 500 o'rniga tushunarli xabar
qaytariladi — bu ikkinchi, zaxira himoya qatlami.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from admin_panel import audit, config
from admin_panel.admin_db import get_admin_db
from admin_panel.deps import AdminIdentity, get_client_ip, require_admin, verify_csrf
from admin_panel.game_db import DisconnectLog, User, game_now, get_game_db

router = APIRouter(prefix="/users", tags=["users"])
templates = Jinja2Templates(directory=str(config.ADMIN_PANEL_DIR / "templates"))

# --- Butun son chegaralari ---------------------------------------------
# User.id     -> standart Integer PK deb qabul qilinadi (32-bit).
# User.telegram_id -> BigInteger deb qabul qilinadi (32-bitdan katta
#                      bo'lishi mumkin bo'lgan haqiqiy Telegram ID'lar uchun).
#
# DIQQAT: agar sizning game_db.py'dagi haqiqiy ustun turlari bundan
# farq qilsa (masalan ikkalasi ham BigInteger, yoki id ham BigInteger),
# quyidagi MAX_ID_INT / MIN_ID_INT qiymatlarini shunga moslab o'zgartiring.
# Har qanday holatda ham pastdagi try/except qatlami DB xatosini
# 500 sifatida "yorib chiqishiga" yo'l qo'ymaydi.
MAX_ID_INT = 2_147_483_647
MIN_ID_INT = -2_147_483_648
MAX_TG_INT = 9_223_372_036_854_775_807
MIN_TG_INT = -9_223_372_036_854_775_808

# Sahifalash uchun oqilona yuqori chegara — juda katta `page` qiymati
# ham OFFSET orqali DB'ga uzatilib, xuddi shunday overflow xatosini
# keltirib chiqarishi mumkin edi.
MAX_PAGE = 1_000_000


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foydalanuvchi topilmadi")
    return user


def _safe_commit(db: Session) -> None:
    """db.commit() ni DBAPIError'dan himoyalangan holda bajaradi.

    Har qanday kutilmagan DB xatosi (ulanish uzilishi, chegaradan
    tashqari qiymat va h.k.) 500 bilan "yalang'och" chiqib ketmasligi,
    sessiya esa keyingi so'rovlar uchun buzilgan holatda qolmasligi
    uchun rollback qilinadi.
    """
    try:
        db.commit()
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ma'lumotlar bazasiga yozishda xatolik yuz berdi",
        )


@router.get("", response_class=HTMLResponse)
def list_users(
    request: Request,
    q: str = "",
    page: int = Query(1, ge=1, le=MAX_PAGE),
    admin: AdminIdentity = Depends(require_admin),
    db: Session = Depends(get_game_db),
):
    query = select(User)
    count_query = select(func.count()).select_from(User)

    q = q.strip()
    if q:
        like = f"%{q}%"
        # Ro'yxatga boshidanoq kengroq ColumnElement[bool] turi beriladi —
        # aks holda Pylance uni ilike() natijasidan (BinaryExpression[bool])
        # kelib chiqib torroq tur deb taxmin qiladi, keyinroq == solishtiruvi
        # (ColumnElement[bool]) qo'shilganda "tur mos kelmaydi" deb
        # ogohlantiradi. Bu sof tur-tekshiruv masalasi, runtime'ga ta'siri yo'q.
        conditions: list[ColumnElement[bool]] = [
            User.username.ilike(like),
            User.first_name.ilike(like),
            User.last_name.ilike(like),
        ]
        # Faqat butun songa o'xshasa telegram_id/id bo'yicha ham qidiramiz.
        # Har bir ustun o'zining haqiqiy kengligiga mos chegarada
        # tekshiriladi — shu bilan ikkalasiga bitta umumiy chegara
        # qo'yilganda yuzaga keladigan overflow oldini oladi.
        stripped = q.lstrip("-")
        if stripped.isdigit() and len(stripped) <= 19:
            try:
                n = int(q)
            except ValueError:
                n = None
            if n is not None:
                if MIN_TG_INT <= n <= MAX_TG_INT:
                    conditions.append(User.telegram_id == n)
                if MIN_ID_INT <= n <= MAX_ID_INT:
                    conditions.append(User.id == n)
        query = query.where(or_(*conditions))
        count_query = count_query.where(or_(*conditions))

    offset = (page - 1) * config.PAGE_SIZE
    try:
        total = db.scalar(count_query) or 0
        users = db.scalars(
            query.order_by(User.id.desc()).offset(offset).limit(config.PAGE_SIZE)
        ).all()
    except DBAPIError:
        # Zaxira himoya qatlami: yuqoridagi chegaralar noto'g'ri taxminga
        # asoslangan bo'lsa ham, foydalanuvchi 500 xatosi o'rniga
        # bo'sh natija va tushunarli xabar ko'radi.
        db.rollback()
        total = 0
        users = []
        return templates.TemplateResponse(
            request,
            "users_list.html",
            {
                "admin": admin,
                "users": users,
                "q": q,
                "page": page,
                "has_next": False,
                "has_prev": page > 1,
                "total": total,
                "now": game_now(),
                "error": "Qidiruv so'rovi noto'g'ri formatda — boshqa qiymat kiriting.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    has_next = offset + config.PAGE_SIZE < total
    has_prev = page > 1

    return templates.TemplateResponse(
        request,
        "users_list.html",
        {
            "admin": admin,
            "users": users,
            "q": q,
            "page": page,
            "has_next": has_next,
            "has_prev": has_prev,
            "total": total,
            "now": game_now(),
        },
    )


@router.get("/{user_id}", response_class=HTMLResponse)
def user_detail(
    request: Request,
    user_id: int = Path(..., gt=0, le=MAX_ID_INT),
    admin: AdminIdentity = Depends(require_admin),
    db: Session = Depends(get_game_db),
):
    user = _get_user_or_404(db, user_id)
    recent_disconnects = db.scalars(
        select(DisconnectLog)
        .where(DisconnectLog.telegram_id == user.telegram_id)
        .order_by(DisconnectLog.occurred_at.desc())
        .limit(10)
    ).all()
    return templates.TemplateResponse(
        request,
        "user_detail.html",
        {
            "admin": admin,
            "user": user,
            "recent_disconnects": recent_disconnects,
            "now": game_now(),
        },
    )


@router.post("/{user_id}/unlock")
def unlock_user(
    request: Request,
    user_id: int = Path(..., gt=0, le=MAX_ID_INT),
    admin: AdminIdentity = Depends(verify_csrf),
    db: Session = Depends(get_game_db),
    admin_db: Session = Depends(get_admin_db),
):
    user = _get_user_or_404(db, user_id)
    was_locked = user.locked_until is not None and user.locked_until > game_now()
    user.locked_until = None
    _safe_commit(db)

    audit.log_action(
        admin_db,
        admin_username=admin.username,
        ip_address=get_client_ip(request),
        action="unlock_user",
        target=f"user:{user.id} (tg:{user.telegram_id})",
        detail=f"was_locked={was_locked}",
    )
    return RedirectResponse(url=f"/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/toggle-blacklist")
def toggle_blacklist(
    request: Request,
    user_id: int = Path(..., gt=0, le=MAX_ID_INT),
    admin: AdminIdentity = Depends(verify_csrf),
    db: Session = Depends(get_game_db),
    admin_db: Session = Depends(get_admin_db),
):
    user = _get_user_or_404(db, user_id)
    user.is_blacklisted = not user.is_blacklisted
    new_state = user.is_blacklisted
    _safe_commit(db)

    audit.log_action(
        admin_db,
        admin_username=admin.username,
        ip_address=get_client_ip(request),
        action="toggle_blacklist",
        target=f"user:{user.id} (tg:{user.telegram_id})",
        detail=f"is_blacklisted={new_state}",
    )
    return RedirectResponse(url=f"/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)


@dataclass(frozen=True)
class _EditResult:
    ok: bool
    error: str | None = None


def _parse_non_negative_int(raw: str, field_label: str) -> int:
    raw = raw.strip()
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"'{field_label}' butun son bo'lishi kerak")
    if value < 0:
        raise ValueError(f"'{field_label}' manfiy bo'lishi mumkin emas")
    if value > 1_000_000_000:
        raise ValueError(f"'{field_label}' qiymati juda katta")
    return value


def _parse_optional_datetime_local(raw: str, field_label: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        # HTML <input type="datetime-local"> "YYYY-MM-DDTHH:MM" formatida yuboradi,
        # vaqt mintaqasiz. Loyihaning qolgan qismi bilan bir xillik uchun UTC deb qabul qilinadi.
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"'{field_label}' sana/vaqt formati noto'g'ri")
    # Loyihaning konvensiyasiga ko'ra (game_db.game_now() izohiga qarang)
    # DB'dan kelgan sana-vaqtlar doim tzinfo'siz (naive) UTC hisoblanadi —
    # shu bilan izchil bo'lishi uchun bu yerda ham tzinfo biriktirilmaydi,
    # aksincha (kamdan-kam holatda brauzer offset yuborsa) UTC'ga
    # aylantirilib, so'ng tzinfo olib tashlanadi.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@router.post("/{user_id}/edit")
def edit_user(
    request: Request,
    user_id: int = Path(..., gt=0, le=MAX_ID_INT),
    rating: str = Form(...),
    games_played: str = Form(...),
    wins: str = Form(...),
    forfeit_wins: str = Form(...),
    times_forfeited: str = Form(...),
    locked_until: str = Form(""),
    admin: AdminIdentity = Depends(verify_csrf),
    db: Session = Depends(get_game_db),
    admin_db: Session = Depends(get_admin_db),
):
    user = _get_user_or_404(db, user_id)

    try:
        new_rating = _parse_non_negative_int(rating, "Reyting")
        new_games_played = _parse_non_negative_int(games_played, "O'ynalgan o'yinlar")
        new_wins = _parse_non_negative_int(wins, "G'alabalar")
        new_forfeit_wins = _parse_non_negative_int(forfeit_wins, "Forfeit orqali g'alabalar")
        new_times_forfeited = _parse_non_negative_int(times_forfeited, "Necha marta forfeit qilgan")
        new_locked_until = _parse_optional_datetime_local(locked_until, "Lock muddati")
    except ValueError as exc:
        recent_disconnects = db.scalars(
            select(DisconnectLog)
            .where(DisconnectLog.telegram_id == user.telegram_id)
            .order_by(DisconnectLog.occurred_at.desc())
            .limit(10)
        ).all()
        return templates.TemplateResponse(
            request,
            "user_detail.html",
            {
                "admin": admin,
                "user": user,
                "recent_disconnects": recent_disconnects,
                "now": game_now(),
                "error": str(exc),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    changes = []
    for field, old, new in [
        ("rating", user.rating, new_rating),
        ("games_played", user.games_played, new_games_played),
        ("wins", user.wins, new_wins),
        ("forfeit_wins", user.forfeit_wins, new_forfeit_wins),
        ("times_forfeited", user.times_forfeited, new_times_forfeited),
        ("locked_until", user.locked_until, new_locked_until),
    ]:
        if old != new:
            changes.append(f"{field}: {old!r} -> {new!r}")

    user.rating = new_rating
    user.games_played = new_games_played
    user.wins = new_wins
    user.forfeit_wins = new_forfeit_wins
    user.times_forfeited = new_times_forfeited
    user.locked_until = new_locked_until
    _safe_commit(db)

    if changes:
        audit.log_action(
            admin_db,
            admin_username=admin.username,
            ip_address=get_client_ip(request),
            action="edit_user",
            target=f"user:{user.id} (tg:{user.telegram_id})",
            detail="; ".join(changes),
        )

    return RedirectResponse(url=f"/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)