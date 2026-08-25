FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r backend/requirements.txt
ENV PYTHONPATH=/app:/app/backend
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port $PORT"]