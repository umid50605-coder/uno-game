import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    BOT_TOKEN: str
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
        self.WEBAPP_URL = self._require_env("WEBAPP_URL")
        self.JWT_SECRET = self._require_env("JWT_SECRET")
        self.WEBHOOK_SECRET = self._require_env("WEBHOOK_SECRET")

        self.JWT_ALGORITHM = os.getenv(
            "JWT_ALGORITHM",
            "HS256",
        )

        try:
            self.JWT_EXPIRE_MINUTES = int(
                os.getenv("JWT_EXPIRE_MINUTES", "1440")
            )
        except ValueError:
            raise RuntimeError(
                "JWT_EXPIRE_MINUTES son bo'lishi kerak."
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

    @staticmethod
    def _require_env(name: str) -> str:
        value = os.getenv(name)

        if not value:
            raise RuntimeError(
                f"{name} muhit o'zgaruvchilarida topilmadi."
            )

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