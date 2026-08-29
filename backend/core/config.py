"""
backend/core/config.py
"""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    BOT_TOKEN: str
    BOT_USERNAME: str
    WEBAPP_URL: str
    WEBHOOK_URL: str
    WEBHOOK_SECRET: str

    JWT_SECRET: str
    JWT_ALGORITHM: str
    JWT_EXPIRE_MINUTES: int

    JWT_ISSUER: str
    JWT_AUDIENCE: str

    def __init__(self) -> None:

        self.BOT_TOKEN = self._require_env("BOT_TOKEN")
        self.BOT_USERNAME = self._require_env("BOT_USERNAME").lstrip("@")
        self.WEBAPP_URL = self._require_env("WEBAPP_URL").rstrip("/")
        self.JWT_SECRET = self._require_env("JWT_SECRET")
        self.WEBHOOK_SECRET = self._require_env("WEBHOOK_SECRET")

        self.JWT_ALGORITHM = os.getenv(
            "JWT_ALGORITHM",
            "HS256",
        )

        allowed_algorithms = {"HS256", "HS384", "HS512"}

        if self.JWT_ALGORITHM not in allowed_algorithms:
            raise RuntimeError(
                "JWT_ALGORITHM noto'g'ri."
            )

        try:
            self.JWT_EXPIRE_MINUTES = int(
                os.getenv("JWT_EXPIRE_MINUTES", "1440")
            )
        except ValueError:
            raise RuntimeError(
                "JWT_EXPIRE_MINUTES son bo'lishi kerak."
            )

        if self.JWT_EXPIRE_MINUTES <= 0:
            raise RuntimeError(
                "JWT_EXPIRE_MINUTES musbat son bo'lishi kerak."
            )

        self.JWT_ISSUER = os.getenv(
            "JWT_ISSUER",
            "uno-game",
        )

        self.JWT_AUDIENCE = os.getenv(
            "JWT_AUDIENCE",
            "uno-webapp",
        )

        webhook_url = os.getenv("WEBHOOK_URL")

        if webhook_url:
            self.WEBHOOK_URL = webhook_url.rstrip("/")
        else:
            self.WEBHOOK_URL = (
                f"{self.WEBAPP_URL.rstrip('/')}/webhook"
            )

        if len(self.WEBHOOK_SECRET) < 32:
            raise RuntimeError(
                "WEBHOOK_SECRET kamida 32 belgidan iborat bo'lishi kerak."
            )

        if len(self.JWT_SECRET) < 32:
            raise RuntimeError(
                "JWT_SECRET kamida 32 belgidan iborat bo'lishi kerak."
            )

    @staticmethod
    def _require_env(name: str) -> str:
        value = os.getenv(name)

        if value is None:
            raise RuntimeError(f"{name} muhit o'zgaruvchilarida topilmadi.")

        value = value.strip()

        if not value:
            raise RuntimeError(f"{name} bo'sh bo'lishi mumkin emas.")

        return value

    @property
    def frontend_dir(self) -> Path:
        return (
            Path(__file__).resolve().parent.parent.parent
            / "frontend"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()