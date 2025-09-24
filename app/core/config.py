# app/core/config.py
import os
from pydantic import BaseSettings, AnyUrl
from typing import List

class Settings(BaseSettings):
    mongo_url: AnyUrl = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name: str = os.environ.get("DB_NAME", "appdb")
    secret_key: str = os.environ.get("SECRET_KEY", "change-me")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    # seguridad login
    login_rate_limit: str = os.environ.get("LOGIN_RATE_LIMIT", "5/minute")
    login_lock_threshold: int = int(os.environ.get("LOGIN_LOCK_THRESHOLD", "8"))
    login_lock_window_min: int = int(os.environ.get("LOGIN_LOCK_WINDOW_MIN", "15"))

    # CORS
    cors_origins: List[str] = [o.strip() for o in os.environ.get("CORS_ORIGINS","").split(",") if o.strip()]

    # Paginación
    max_page_size: int = int(os.environ.get("MAX_PAGE_SIZE", "50"))

    # Papelera
    trash_ttl_days: int = 14

settings = Settings()
