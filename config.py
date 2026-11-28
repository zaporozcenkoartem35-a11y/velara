import os
from typing import List, Union, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram Bot
    BOT_TOKEN: str = "SET_YOUR_TOKEN_HERE"
    ADMIN_IDS: Union[int, str, List[int]] = []
    
    # База даних (PostgreSQL через asyncpg або локальний SQLite)
    DATABASE_URL: Optional[str] = None
    DATABASE_PATH: str = "bot_database.sqlite"

    # LLM Provider (OpenAI, OpenRouter, Gemini, Groq, Claude)
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.72
    LLM_MAX_TOKENS: int = 1100
    LLM_TIMEOUT_SECONDS: float = 30.0

    # Ціни в Telegram Stars (XTR)
    PRICE_TAROT_1: int = 35
    PRICE_TAROT_3: int = 90
    PRICE_ARCANA_LOVE: int = 35
    PRICE_COMPAT: int = 25

    # Аліаси для зворотної сумісності (якщо передані зі старими назвами)
    TAROT_PRICE_1: Optional[int] = None
    TAROT_PRICE_3: Optional[int] = None
    ARCANA_LOVE_PRICE: Optional[int] = None
    PRICE_COMPAT_STARS: Optional[int] = None

    # Підтримка та контакти
    SUPPORT_USERNAME: str = "VelaraSupport"

    # WebApp та Сервер
    ENABLE_WEBAPP: bool = False
    DISABLE_IMAGES: bool = False
    PORT: int = 10000

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, int):
            return [v]
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []

    @property
    def clean_support_username(self) -> str:
        return self.SUPPORT_USERNAME.lstrip("@")

    @property
    def tarot_price_1(self) -> int:
        return self.PRICE_TAROT_1 or self.TAROT_PRICE_1 or 35

    @property
    def tarot_price_3(self) -> int:
        return self.PRICE_TAROT_3 or self.TAROT_PRICE_3 or 90

    @property
    def arcana_love_price(self) -> int:
        return self.PRICE_ARCANA_LOVE or self.ARCANA_LOVE_PRICE or 35

    @property
    def compat_price(self) -> int:
        return self.PRICE_COMPAT or self.PRICE_COMPAT_STARS or 25

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
