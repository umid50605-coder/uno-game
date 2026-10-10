FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r backend/requirements.txt
ENV PYTHONPATH=/app:/app/backend
# DIQQAT: `--workers 1` ATAYLAB aniq yozilgan. O'yin holati (GameManager),
# WebSocket ulanishlari (ConnectionManager) va tournament lock'lari
# process-local — bir nechta worker/instance bilan o'yinlar bo'linib ketadi.
# `--workers` berilmasa uvicorn $WEB_CONCURRENCY qiymatini oladi; shuning
# uchun bu yerda uni qat'iy 1 ga o'rnatamiz.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1"]