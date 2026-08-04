# core/env.py
import os
import jwt
from datetime import datetime, timedelta

# JWT sozlamalari
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-here")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 30

def create_jwt_token(data: dict) -> str:
    """JWT token yaratish"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRATION_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str) -> dict:
    """JWT tokenni dekod qilish"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token muddati tugagan")
    except jwt.InvalidTokenError:
        raise ValueError("Token yaroqsiz")