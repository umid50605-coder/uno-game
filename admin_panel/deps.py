"""
admin_panel/deps.py — FastAPI dependency'lari: autentifikatsiya, CSRF
tekshiruvi va mijoz IP manzilini aniqlash.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Form, HTTPException, Request, status

from admin_panel import config, security


class NotAuthenticated(Exception):
    """require_admin sessiya yo'q/eskirgan deb topganda shu istisno tashlanadi.
    main.py'da bu /login sahifasiga qayta yo'naltirishga aylantiriladi."""


@dataclass(frozen=True)
class AdminIdentity:
    username: str
    csrf_token: str


def get_client_ip(request: Request) -> str:
    """Mijoz IP manzilini qaytaradi. Faqat ADMIN_TRUST_PROXY=True bo'lganda
    X-Forwarded-For headeriga ishoniladi (aks holda bu header osongina
    qalbakilashtirilishi mumkin va IP-ro'yxat/rate-limitni chetlab o'tadi)."""
    if config.ADMIN_TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_admin(request: Request) -> AdminIdentity:
    """Har bir himoyalangan sahifa/amal uchun: sessiya cookie'sini tekshiradi.
    Sessiya yo'q yoki eskirgan bo'lsa — NotAuthenticated tashlanadi (login
    sahifasiga yo'naltiriladi)."""
    token = request.cookies.get(security.SESSION_COOKIE_NAME)
    if not token:
        raise NotAuthenticated()
    data = security.read_session_token(token)
    if data is None:
        raise NotAuthenticated()
    identity = AdminIdentity(username=data["u"], csrf_token=data["csrf"])
    # Shablonlarda (base.html) ko'rsatish uchun request.state'ga ham yozamiz
    request.state.admin = identity
    return identity


def verify_csrf(
    request: Request,
    admin: AdminIdentity = Depends(require_admin),
    csrf_token: str = Form(...),
) -> AdminIdentity:
    """Har bir ma'lumot o'zgartiruvchi/o'chiruvchi POST so'rov shu
    dependency'ni ishlatishi shart. Formadagi yashirin maydon sessiyaga
    bog'langan tokenga mos kelmasa — 403 qaytariladi (CSRF himoyasi).

    Muvaffaqiyatli bo'lsa, `admin` identifikatorining o'zini qaytaradi —
    shu tufayli chaqiruvchi route'lar `Depends(verify_csrf)`ning natijasini
    to'g'ridan-to'g'ri `AdminIdentity` sifatida ishlata oladi (masalan
    audit.log_action'ga admin_username=admin.username berish uchun)."""
    if not security.constant_time_equals(csrf_token, admin.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF tokeni noto'g'ri yoki sessiya eskirgan. Sahifani yangilab qayta urining.",
        )
    return admin
