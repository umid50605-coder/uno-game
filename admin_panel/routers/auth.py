"""
admin_panel/routers/auth.py — Kirish va chiqish.

Himoya choralari:
  - Parol PBKDF2-HMAC-SHA256 xeshi bilan solishtiriladi (security.py)
  - Login urinishlari IP bo'yicha rate-limit qilinadi (admin_db.py)
  - Muvaffaqiyatsiz urinishda ham, muvaffaqiyatli urinishda ham javob
    vaqti deyarli bir xil bo'lishi uchun xeshlash har doim bajariladi
    (foydalanuvchi nomi noto'g'ri bo'lsa ham "dummy" xesh bilan solishtiriladi) —
    bu username enumeration/timing hujumining oldini oladi.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from admin_panel import admin_db, config, security
from admin_panel.deps import get_client_ip

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=str(config.ADMIN_PANEL_DIR / "templates"))

# Foydalanuvchi nomi noto'g'ri bo'lganda ham xeshlash vaqti bir xil bo'lishi
# uchun ishlatiladigan "soxta" xesh (haqiqiy parolga mos kelmaydi).
_DUMMY_HASH = security.hash_password(security.generate_secret_key())


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request, "login.html", {"error": error}
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(admin_db.get_admin_db),
):
    ip = get_client_ip(request)

    if admin_db.is_ip_rate_limited(db, ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": (
                    f"Juda ko'p muvaffaqiyatsiz urinish. "
                    f"{config.LOGIN_RATE_LIMIT_WINDOW_MINUTES} daqiqadan so'ng qayta urining."
                )
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    username_ok = security.constant_time_equals(username.strip(), config.ADMIN_USERNAME)
    password_hash_to_check = config.ADMIN_PASSWORD_HASH if username_ok else _DUMMY_HASH
    password_ok = security.verify_password(password, password_hash_to_check)

    success = username_ok and password_ok
    admin_db.record_login_attempt(db, ip, success)

    if not success:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Login yoki parol noto'g'ri."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = security.create_session_token(config.ADMIN_USERNAME)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=security.SESSION_COOKIE_NAME,
        value=token,
        max_age=config.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=config.ADMIN_COOKIE_SECURE,
        samesite="strict",
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(security.SESSION_COOKIE_NAME)
    return response
