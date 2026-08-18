"""
backend/services/self_ping.py

Render'ning free tarifida xizmat 15 daqiqa faoliyatsiz qolsa uxlab qoladi.
Bu background task o'z manziliga (WEBAPP_URL) muntazam so'rov yuborib,
xizmatni doim "uyg'oq" holatda ushlab turadi.

Faqat production'da (RENDER=true environment) ishga tushadi — lokal
development paytida keraksiz tarmoq so'rovlarini oldini olish uchun.
"""
import asyncio
import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

# Render 15 daqiqadan keyin uxlatadi — shuning uchun 10 daqiqada bir marta
# ping yuboramiz, xavfsiz zaxira bilan
PING_INTERVAL_SECONDS = int(os.getenv("SELF_PING_INTERVAL_SECONDS", "600"))


async def self_ping_loop(target_url: str) -> None:
    """
    Belgilangan manzilga muntazam so'rov yuborib turadi.
    Xatolar butun ilovani to'xtatmasligi uchun har doim try/except ichida.
    """
    # Faqat Render muhitida ishga tushirish (lokal ishlab chiqishda kerak emas)
    if os.getenv("RENDER") != "true":
        logger.info(
            "Self-ping o'chirilgan (RENDER muhit o'zgaruvchisi 'true' emas)"
        )
        return

    ping_url = f"{target_url.rstrip('/')}/healthz"

    logger.info(
        "Self-ping ishga tushdi | manzil=%s | interval=%d soniya",
        ping_url,
        PING_INTERVAL_SECONDS,
    )

    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)

            try:
                async with session.get(
                    ping_url,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    logger.info(
                        "Self-ping muvaffaqiyatli | status=%d",
                        response.status,
                    )

            except Exception:
                logger.exception("Self-ping so'rovida xato yuz berdi")