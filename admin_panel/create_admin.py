#!/usr/bin/env python3
"""
admin_panel/create_admin.py — admin_panel/.env faylini yaratish uchun
interaktiv skript. Bir marta ishga tushiring:

    cd uno-game
    python3 admin_panel/create_admin.py

Bu sizdan login va parol so'raydi, parolni xavfsiz xeshlaydi (PBKDF2-HMAC-SHA256,
600 000 iteratsiya), tasodifiy maxfiy kalit (SECRET_KEY) generatsiya qiladi va
hammasini admin_panel/.env fayliga yozadi. Parolning o'zi HECH QACHON diskka
yozilmaydi — faqat uning xeshi saqlanadi.

Agar .env fayli allaqachon mavjud bo'lsa, tasdiq so'raladi va eski fayl
`.env.bak` nomiga zaxira sifatida ko'chiriladi.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from admin_panel.security import generate_secret_key, hash_password  # noqa: E402

ENV_PATH = Path(__file__).resolve().parent / ".env"
ENV_EXAMPLE_PATH = Path(__file__).resolve().parent / ".env.example"


def main() -> None:
    print("=== UNO Admin Panel — sozlash ===\n")

    if ENV_PATH.exists():
        answer = input(
            f"'{ENV_PATH.name}' fayli allaqachon mavjud. Uni almashtirishni xohlaysizmi? (ha/yo'q): "
        ).strip().lower()
        if answer not in {"ha", "h", "yes", "y"}:
            print("Bekor qilindi.")
            return
        backup_path = ENV_PATH.with_suffix(".env.bak")
        ENV_PATH.rename(backup_path)
        print(f"Eski fayl '{backup_path.name}' nomiga zaxiralandi.\n")

    username = input("Admin login (masalan: admin): ").strip()
    while not username:
        username = input("Login bo'sh bo'lishi mumkin emas. Qayta kiriting: ").strip()

    while True:
        password = getpass.getpass("Admin paroli (kamida 12 belgi tavsiya etiladi): ")
        if len(password) < 8:
            print("Parol juda qisqa (kamida 8 belgi). Qayta urining.\n")
            continue
        password_confirm = getpass.getpass("Parolni qayta kiriting: ")
        if password != password_confirm:
            print("Parollar mos kelmadi. Qayta urining.\n")
            continue
        break

    password_hash = hash_password(password)
    secret_key = generate_secret_key()

    env_content = f"""# admin_panel/.env — create_admin.py tomonidan avtomatik yaratildi.
# BU FAYLNI HECH QACHON git'ga qo'shmang / oshkor qilmang.

ADMIN_USERNAME={username}
ADMIN_PASSWORD_HASH={password_hash}
ADMIN_SECRET_KEY={secret_key}

# Production'da (HTTPS ostida) True bo'lishi SHART.
# Faqat http://localhost bilan mahalliy sinov uchun False qiling.
ADMIN_COOKIE_SECURE=True

# Agar Nginx/Render kabi reverse-proxy ortida ishlasangiz va haqiqiy
# mijoz IP'ini bilish kerak bo'lsa — True qiling (aks holda False qoldiring).
ADMIN_TRUST_PROXY=False

# Bo'sh qoldirilsa — cheklov yo'q. To'ldirilsa, faqat shu IP/CIDR'lardan
# kirishga ruxsat beriladi. Masalan: ADMIN_ALLOWED_IPS=5.6.7.8,10.0.0.0/24
ADMIN_ALLOWED_IPS=

SESSION_MAX_AGE_SECONDS=43200
LOGIN_RATE_LIMIT_MAX_ATTEMPTS=5
LOGIN_RATE_LIMIT_WINDOW_MINUTES=15
ADMIN_PAGE_SIZE=25

# Agar admin_panel/ va backend/ bir xil ota-papkada bo'lmasa, shu yerga
# backend/ papkasining TO'LIQ yo'lini yozing. Aks holda bo'sh qoldiring.
BACKEND_DIR=
"""

    ENV_PATH.write_text(env_content, encoding="utf-8")
    ENV_PATH.chmod(0o600)  # faqat egasi o'qiy oladi

    print(f"\n✅ Tayyor! '{ENV_PATH}' yaratildi (ruxsatlar 600 ga o'rnatildi).")
    print("\nEndi ishga tushirish uchun:")
    print("    uvicorn admin_panel.main:app --host 127.0.0.1 --port 8001")


if __name__ == "__main__":
    main()
