FROM python:3.11-slim

WORKDIR /app/backend

COPY backend/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]