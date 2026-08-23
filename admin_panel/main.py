"""
admin_panel/main.py — Admin panel uchun mustaqil FastAPI ilovasi.

Bu ilova botning asosiy backend'idan (backend/main.py) BUTUNLAY ALOHIDA
jarayon sifatida, alohida portda ishga tushiriladi:

    cd uno-game
    uvicorn admin_panel.main:app --host 127.0.0.1 --port 8001

Botning o'z fayllariga (backend/, bot/, frontend/) hech qanday tegilmagan
va tegilmaydi ham — admin_panel faqat backend/'dagi modellarni "o'qish"
uchun import qiladi (game_db.py'ga qarang).

Ishga tushirishdan oldin: admin_panel/create_admin.py skriptini bir marta
ishga tushiring — u sizdan login/parol so'raydi va admin_panel/.env
faylini avtomatik yaratadi.
"""

from __future__ import annotations

import ipaddress

from fastapi import FastAPI, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from admin_panel import config
from admin_panel.deps import NotAuthenticated, get_client_ip
from admin_panel.routers import auth, logs, rooms, stats, users

app = FastAPI(title="UNO Admin Panel", docs_url=None, redoc_url=None, openapi_url=None)

app.mount("/static", StaticFiles(directory=str(config.ADMIN_PANEL_DIR / "static")), name="static")

app.include_router(auth.router)
app.include_router(stats.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(logs.router)


def _ip_allowed(ip: str) -> bool:
    if not config.ADMIN_ALLOWED_IPS:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for allowed in config.ADMIN_ALLOWED_IPS:
        try:
            if "/" in allowed:
                if addr in ipaddress.ip_network(allowed, strict=False):
                    return True
            elif addr == ipaddress.ip_address(allowed):
                return True
        except ValueError:
            continue
    return False


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # 1) Ixtiyoriy IP-ro'yxat cheklovi (ADMIN_ALLOWED_IPS bo'sh bo'lsa — o'chirilgan)
    client_ip = get_client_ip(request)
    if not _ip_allowed(client_ip):
        return PlainTextResponse("Forbidden", status_code=status.HTTP_403_FORBIDDEN)

    response = await call_next(request)

    # 2) Xavfsizlik headerlari — har bir javobga qo'shiladi
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; frame-ancestors 'none'"
    )
    if config.ADMIN_COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

    return response


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
