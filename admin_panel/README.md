# UNO Admin Panel

Botning `backend/`, `bot/`, `frontend/` fayllariga umuman tegilmagan,
mustaqil ishlaydigan, faqat bitta admin uchun mo'ljallangan web panel.

## O'rnatish

```bash
cd uno-game               # loyihaning tub papkasi (backend/ shu yerda joylashgan)
pip install -r admin_panel/requirements.txt
python3 admin_panel/create_admin.py     # login/parol/maxfiy kalitni o'rnatadi
uvicorn admin_panel.main:app --host 127.0.0.1 --port 8001
```

`admin_panel/` va `backend/` bir xil ota-papkada (`uno-game/`) bo'lishi kerak.
Agar boshqacha joylashgan bo'lsa — `admin_panel/.env`da `BACKEND_DIR`ni
to'liq yo'l bilan ko'rsating.

Brauzerda: `http://127.0.0.1:8001` (yoki serverda joylashtirgan manzilingiz).

## Production'da joylashtirish (masalan Render)

- Botdan **butunlay alohida** service sifatida joylashtiring (start
  command: `uvicorn admin_panel.main:app --host 0.0.0.0 --port $PORT`).
- `admin_panel/.env`dagi qiymatlarni shu service'ning Environment
  Variables bo'limiga qo'shing (`.env` faylining o'zini serverga
  yuklamang — reponi ham git'ga qo'shmang).
- **`ADMIN_COOKIE_SECURE=True` bo'lishi SHART** — bu HTTPS orqali
  ishlayotgan production uchun.
- Ixtiyoriy, lekin tavsiya etiladi: `ADMIN_ALLOWED_IPS`ga faqat o'zingiz
  ishlatadigan IP(lar)ni yozib qo'ying — shunda hech kim, hatto to'g'ri
  parolni bilsa ham, boshqa joydan kira olmaydi.
- Agar Render/Nginx kabi reverse-proxy ortida bo'lsangiz va
  `ADMIN_ALLOWED_IPS`dan foydalanmoqchi bo'lsangiz, `ADMIN_TRUST_PROXY=True`
  qiling (aks holda haqiqiy mijoz IP'i ko'rinmaydi).

## Xavfsizlik choralari (nima va nima uchun)

| Chora | Tavsif |
|---|---|
| Parol xeshi | PBKDF2-HMAC-SHA256, 600 000 iteratsiya (tashqi bog'liqlik yo'q, versiyalararo buzilmaydi) |
| Sessiya cookie | imzolangan (itsdangerous), `httponly`, `secure`, `samesite=strict`, muddatli |
| CSRF | har bir yozuvchi POST forma sessiyaga bog'langan tokenni talab qiladi |
| Login rate-limit | bitta IP'dan 15 daqiqada 5 martadan ortiq muvaffaqiyatsiz urinish — vaqtincha bloklanadi (to'g'ri parol bilan ham) |
| IP-ro'yxat (ixtiyoriy) | `ADMIN_ALLOWED_IPS` to'ldirilsa, faqat shu IP/CIDR'lardan kirish mumkin |
| Whitelist edit | faqat oldindan belgilangan maydonlar tahrirlanadi, erkin/xom SQL yo'q |
| Audit log | har bir o'zgartirish/o'chirish — kim, qachon, qaysi IP'dan, nima qilingani `admin_panel/admin.db`ga yoziladi |
| Xavfsizlik headerlari | `X-Frame-Options`, `X-Content-Type-Options`, CSP, va h.k. har bir javobga qo'shiladi |
| Ikkita alohida baza | `admin_panel/admin.db` (audit/rate-limit) — o'yin bazasi `backend/uno.db`ga hech qanday sxema o'zgarishi kiritilmaydi |

## Fayl tuzilishi

```
admin_panel/
├── main.py           FastAPI ilova, middleware, xavfsizlik headerlari
├── config.py          .env'ni o'qiydi, majburiy qiymatlar yo'q bo'lsa xato beradi
├── security.py         parol xeshlash, sessiya/CSRF
├── game_db.py           backend/'dagi User/Room/DisconnectLog'ni IMPORT qiladi (qayta yozmaydi)
├── admin_db.py            adminning o'z bazasi: audit log + login rate-limit
├── deps.py                 auth/CSRF FastAPI dependency'lari
├── audit.py                  audit yozuvi yordamchisi
├── routers/
│   ├── auth.py                login/logout
│   ├── stats.py                 dashboard (statistika)
│   ├── users.py                  ro'yxat/qidiruv/unlock/blacklist/edit
│   ├── rooms.py                   faol xonalar + o'chirish
│   └── logs.py                     disconnect loglari + o'chirish
├── templates/, static/           HTML/CSS
└── create_admin.py                .env'ni interaktiv yaratish
```

## Qasddan qilingan doiraviy cheklov (scope)

**Foydalanuvchini butunlay o'chirish** funksiyasi ATAYLAB qo'shilmadi.
Sabab: `User` jadvali `Room.host_id` va `RoomPlayer.user_id` orqali
bog'langan (`nullable=False`), ya'ni to'g'ri o'chirish uchun avval qaror
kerak — foydalanuvchi mezbon bo'lgan xonalar nima bo'ladi (o'chiriladimi,
boshqa mezbonga o'tkaziladimi), tarixiy statistika saqlanib qolishi
kerakmi. Buni chala-yarim, taxminiy tarzda qilish ma'lumotlar
yaxlitligini buzishi mumkin edi. Hozircha **blacklist** amaliy jihatdan
xuddi shu vazifani bajaradi (foydalanuvchi bloklanadi). Aniq qoidani
belgilab bersangiz, buni alohida to'ldiraman.
