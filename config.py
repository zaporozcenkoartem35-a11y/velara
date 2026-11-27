import os
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram Bot
    BOT_TOKEN: str = "SET_YOUR_TOKEN_HERE"
    ADMIN_IDS: Union[int, str, List[int]] = []
    DATABASE_PATH: str = "bot_database.sqlite"

    # LLM Provider (OpenAI, OpenRouter, Gemini, Groq, Claude)
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.72
    LLM_TIMEOUT_SECONDS: float = 35.0

    # Prices in Telegram Stars (XTR)
    TAROT_PRICE_1: int = 35
    TAROT_PRICE_3: int = 90
    ARCANA_LOVE_PRICE: int = 35

    # Rate limits
    COMPATIBILITY_DAILY_LIMIT: int = 3

    # Web Server (Render / Koyeb keep-alive & WebApp)
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
