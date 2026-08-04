FROM python:3.11-slim

WORKDIR /app

# Backend requirements
COPY backend/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Loyiha fayllari
COPY . .

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "10000"]