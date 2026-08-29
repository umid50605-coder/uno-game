"""
backend/api/routes/config.py — frontendga kerakli public sozlamalar
"""
from fastapi import APIRouter

from core.config import get_settings

router = APIRouter()


@router.get("/config")
async def get_public_config():
    settings = get_settings()
    return {"bot_username": settings.BOT_USERNAME}