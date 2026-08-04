# 1. Python 3.11 asosiy tasviri (image)
FROM python:3.11-slim

# 2. Ishchi papkani belgilash
WORKDIR /app

# 3. Kutubxonalar ro'yxatini nusxalash
COPY requirements.txt .

# 4. Barcha Python kutubxonalarni o'rnatish
RUN pip install --no-cache-dir -r requirements.txt

# 5. Butun loyihani nusxalash
COPY . .

# 6. Uvicorn orqali ishga tushirish
CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT