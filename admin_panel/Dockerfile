FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r admin_panel/requirements.txt
CMD ["sh", "-c", "uvicorn admin_panel.main:app --host 0.0.0.0 --port $PORT"]