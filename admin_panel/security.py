"""
admin_panel/security.py — parolni xesh qilish, sessiya cookie'sini
imzolash/tekshirish va CSRF himoyasi.

Eslatma (parol xeshlash haqida): dastlab `passlib[bcrypt]` ishlatish
ko'zda tutilgan edi, lekin sinovda passlib + zamonaviy `bcrypt` paketi
orasida mashhur moslik xatosi borligi aniqlandi (`AttributeError: module
'bcrypt' has no attribute '__about__'`, keyin esa 72-baytlik parol
uzunligi cheklovida yana xato). Bu qo'shimcha tashqi kutubxonaga bog'liq
bo'lgan, versiyaga sezgir muammo. O'rniga standart kutubxonadagi
`hashlib.pbkdf2_hmac` (PBKDF2-HMAC-SHA256, 600 000 iteratsiya — bu Django
va OWASP tavsiya qiladigan yondashuv) ishlatildi: hech qanday tashqi
bog'liqlik yo'q, sinovdan o'tdi va versiyalararo hech qachon buzilmaydi.
"""

from __future__ import annotations

import binascii
import base64
import hashlib
import hmac
import os
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# DIQQAT: bu modul `admin_panel.config`ni ATAYLAB modul darajasida import
# QILMAYDI. Sababi: config.py .env fayli mavjud va to'liq to'ldirilgan
# bo'lishini talab qiladi (fail-fast), lekin create_admin.py aynan shu
# .env faylini YARATISH uchun ushbu moduldagi hash_password/
# generate_secret_key funksiyalarini chaqiradi — ya'ni .env hali yo'q
# paytda. Shuning uchun config'ga bog'liq bo'lgan qism (sessiya
# imzolash) pastda alohida, faqat kerak bo'lganda (lazy) import qiladi;
# parolni xeshlash funksiyalari esa config'ga umuman bog'liq emas.

_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SCHEME = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Parolni xavfsiz xesh qiladi. Natijani ADMIN_PASSWORD_HASH sifatida .env'ga yozing."""
    if not password:
        raise ValueError("Parol bo'sh bo'lishi mumkin emas")
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return (
        f"{_PBKDF2_SCHEME}${_PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """Kiritilgan parolni saqlangan xesh bilan doimiy vaqtda (timing-safe) solishtiradi."""
    try:
        scheme, iterations_s, salt_b64, hash_b64 = stored_hash.split("$")
        if scheme != _PBKDF2_SCHEME:
            return False
        iterations = int(iterations_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError, AttributeError, binascii.Error):
        # Format buzilgan yoki noto'g'ri — parol xato deb hisoblanadi, xato tashlanmaydi
        return False


def generate_secret_key() -> str:
    """create_admin.py uchun: ADMIN_SECRET_KEY'ga mos kriptografik jihatdan mustahkam qator."""
    return secrets.token_urlsafe(48)


# ---------------------------------------------------------------------------
# Sessiya cookie: imzolangan (o'zgartirib bo'lmaydigan) va vaqt bilan cheklangan.
# Cookie ichida foydalanuvchi nomi va shu sessiyaga tegishli CSRF tokeni saqlanadi.
# Serializer faqat birinchi marta kerak bo'lganda (lazy) yaratiladi — sababi
# yuqoridagi izohda.
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "admin_session"

_serializer: URLSafeTimedSerializer | None = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        from admin_panel import config  # lazy import — izohga qarang

        _serializer = URLSafeTimedSerializer(config.ADMIN_SECRET_KEY, salt="admin-session")
    return _serializer


def create_session_token(username: str) -> str:
    csrf_token = secrets.token_urlsafe(32)
    return _get_serializer().dumps({"u": username, "csrf": csrf_token})


def read_session_token(token: str) -> dict | None:
    """Cookie imzosini va muddatini tekshiradi. Muvaffaqiyatsiz bo'lsa None qaytaradi."""
    from admin_panel import config  # lazy import — izohga qarang

    try:
        data = _get_serializer().loads(token, max_age=config.SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or "u" not in data or "csrf" not in data:
        return None
    return data


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")
