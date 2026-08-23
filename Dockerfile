FROM python:3.11-slim

WORKDIR /app

# Butun repo'ni nusxalaymiz — admin_panel/game_db.py backend/'dagi
# modellarni o'qish uchun ularga muhtoj, shuning uchun faqat
# admin_panel/'ni emas, hammasini olib qo'yamiz.
COPY . /app

# Ikkala requirements faylini ham o'rnatamiz: backend/'niki (SQLAlchemy
# modellar uchun kerak) va admin_panel/'niki (FastAPI, itsdangerous,
# python-dotenv va h.k. uchun).
RUN pip install --no-cache-dir -r backend/requirements.txt -r admin_panel/requirements.txt

# WORKDIR /app bo'lgani uchun uvicorn "admin_panel.main:app"ni
# /app/admin_panel/main.py sifatida to'g'ri topadi.
CMD ["sh", "-c", "uvicorn admin_panel.main:app --host 0.0.0.0 --port $PORT"]