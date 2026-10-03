from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6380/0"

    GOOGLE_SIGNIN_ENABLED: bool = False  # off: SRM Workspace blocks outside apps for now
    GOOGLE_CLIENT_ID: str = ""
    COLLEGE_DOMAIN: str = "srmist.edu.in"
    FRONTEND_URL: str = "http://localhost:3000"

    SESSION_COOKIE: str = "sid"
    SESSION_TTL_SECONDS: int = 7 * 24 * 3600
    COOKIE_SECURE: bool = True

    OTP_TTL_SECONDS: int = 600
    OTP_MAX_ATTEMPTS: int = 5

    EMAIL_BACKEND: str = "console"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
