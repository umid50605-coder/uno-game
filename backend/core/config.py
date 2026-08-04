import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    BOT_TOKEN: str
    WEBAPP_URL: str
    WEBHOOK_URL: str          # yangi
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24

    def __init__(self) -> None:
        bot_token = os.getenv("BOT_TOKEN")
        webapp_url = os.getenv("WEBAPP_URL")
        jwt_secret = os.getenv("JWT_SECRET")

        if not bot_token:
            raise RuntimeError("BOT_TOKEN muhit o'zgaruvchilarida topilmadi.")
        if not webapp_url:
            raise RuntimeError("WEBAPP_URL muhit o'zgaruvchilarida topilmadi.")
        if not jwt_secret:
            raise RuntimeError("JWT_SECRET muhit o'zgaruvchilarida topilmadi.")

        self.BOT_TOKEN = bot_token
        self.WEBAPP_URL = webapp_url
        self.JWT_SECRET = jwt_secret

        # WEBHOOK_URL ni WEBAPP_URL + '/webhook' qilib olamiz
        self.WEBHOOK_URL = f"{webapp_url.rstrip('/')}/webhook"

    @property
    def frontend_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent / "frontend"


@lru_cache
def get_settings() -> Settings:
    return Settings()