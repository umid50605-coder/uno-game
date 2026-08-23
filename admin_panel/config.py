"""
admin_panel/config.py — Admin panel uchun barcha sozlamalar shu yerdan olinadi.

Muhim: bu modul .env faylidan o'qiydi va agar xavfsizlik uchun zarur
bo'lgan qiymatlar (ADMIN_USERNAME, ADMIN_PASSWORD_HASH, ADMIN_SECRET_KEY)
yo'q yoki bo'sh bo'lsa, ilova ishga tushishning o'zidayoq xato berib
to'xtaydi ("fail fast"). Bu qasddan qilingan — noto'g'ri sozlangan admin
panelni "ehtiyotsizdan" ochiq holda ishga tushirib qo'yishning oldini
oladi.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ADMIN_PANEL_DIR = Path(__file__).resolve().parent

# .env fayli admin_panel/ ichida bo'ladi (backend/.env bilan aralashmaydi)
load_dotenv(ADMIN_PANEL_DIR / ".env")


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(
            f"[XATO] admin_panel/.env faylida '{name}' o'rnatilmagan yoki bo'sh.\n"
            f"       Avval quyidagini ishga tushiring:\n"
            f"         python3 admin_panel/create_admin.py\n"
            f"       Bu sizga login/parol hash/maxfiy kalitni avtomatik yaratib beradi."
        )
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        sys.exit(f"[XATO] admin_panel/.env: '{name}' butun son bo'lishi kerak, hozirgi qiymat: {raw!r}")


# ---- Majburiy (bo'lmasa ilova ishlamaydi) ----
ADMIN_USERNAME: str = _require("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH: str = _require("ADMIN_PASSWORD_HASH")
ADMIN_SECRET_KEY: str = _require("ADMIN_SECRET_KEY")

if len(ADMIN_SECRET_KEY) < 32:
    sys.exit(
        "[XATO] ADMIN_SECRET_KEY juda qisqa (kamida 32 belgi bo'lishi kerak).\n"
        "       admin_panel/create_admin.py skriptini qayta ishga tushiring."
    )

# ---- Ixtiyoriy sozlamalar ----

# Bir nechta IP/CIDR, vergul bilan ajratilgan. Bo'sh bo'lsa — cheklov yo'q.
# Masalan: "5.6.7.8,10.0.0.0/24"
_raw_allowed_ips = os.getenv("ADMIN_ALLOWED_IPS", "").strip()
ADMIN_ALLOWED_IPS: list[str] = [
    ip.strip() for ip in _raw_allowed_ips.split(",") if ip.strip()
]

# Production'da doim True bo'lishi kerak (cookie faqat HTTPS orqali yuboriladi).
# Faqat localhost'da http:// bilan sinab ko'rish uchun False qiling.
ADMIN_COOKIE_SECURE: bool = _bool("ADMIN_COOKIE_SECURE", True)

# Agar admin panel Nginx/Render kabi reverse-proxy ortida ishlasa va haqiqiy
# mijoz IP'ini X-Forwarded-For headeridan olish kerak bo'lsa — buni True
# qiling. DIQQAT: agar proxy ortida bo'lmasangiz, buni False holida qoldiring
# — aks holda har kim ushbu headerni qalbakilashtirib, IP-ro'yxatini yoki
# login rate-limitni chetlab o'tishi mumkin.
ADMIN_TRUST_PROXY: bool = _bool("ADMIN_TRUST_PROXY", False)

# Sessiya necha soniyada eskiradi (default: 12 soat)
SESSION_MAX_AGE_SECONDS: int = _int("SESSION_MAX_AGE_SECONDS", 12 * 60 * 60)

# Login urinishlari uchun rate-limit
LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = _int("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 5)
LOGIN_RATE_LIMIT_WINDOW_MINUTES: int = _int("LOGIN_RATE_LIMIT_WINDOW_MINUTES", 15)

# Ro'yxatlarda bir sahifada nechta yozuv ko'rsatilsin
PAGE_SIZE: int = _int("ADMIN_PAGE_SIZE", 25)

# Asosiy bot loyihasining backend/ papkasi qayerda joylashgani.
# Standart holatda admin_panel/ va backend/ bir xil ota-papkada (uno-game/) deb
# hisoblanadi. Agar sizning joylashuvingiz boshqacha bo'lsa, .env'da
# BACKEND_DIR bilan to'liq yo'lni ko'rsating.
_backend_dir_override = os.getenv("BACKEND_DIR", "").strip()
if _backend_dir_override:
    BACKEND_DIR = Path(_backend_dir_override).resolve()
else:
    BACKEND_DIR = (ADMIN_PANEL_DIR.parent / "backend").resolve()

if not (BACKEND_DIR / "core" / "database.py").exists():
    sys.exit(
        f"[XATO] backend/core/database.py topilmadi: {BACKEND_DIR}\n"
        f"       admin_panel/.env faylida BACKEND_DIR to'g'ri yo'lni ko'rsating."
    )
