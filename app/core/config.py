from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    TELEGRAM_API_ID: Optional[int] = Field(default=None)
    TELEGRAM_API_HASH: Optional[str] = Field(default=None)
    HTTP_PROXY: Optional[str] = None
    SOCKS_PROXY: Optional[str] = None
    DATABASE_URL: str = "sqlite+aiosqlite:///./app.db"
    SESSIONS_DIR: str = "./sessions"
    LOG_LEVEL: str = "INFO"
    # Rate limits
    RATE_LIMIT_MAX: int = 1
    RATE_LIMIT_WINDOW: int = 3  # seconds
    QUOTA_PER_ACCOUNT_MAX: int = 35
    QUOTA_PER_ACCOUNT_WINDOW: int = 24 * 3600  # 24h
    # Auth
    ADMIN_USERNAME: Optional[str] = None
    ADMIN_PASSWORD: Optional[str] = None
    API_KEY: Optional[str] = None
    SECRET_KEY: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

settings = Settings()
