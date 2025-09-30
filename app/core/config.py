# app/core/config.py
from typing import List, Union
from pydantic import BaseSettings, validator
import json


class Settings(BaseSettings):
    # === MongoDB ===
    mongo_url: str = "mongodb://localhost:27017"
    db_name: str = "appdb"

    # === Seguridad / JWT ===
    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # === Seguridad login (anti brute-force) ===
    login_rate_limit: str = "5/minute"
    login_lock_threshold: int = 8
    login_lock_window_min: int = 15

    # === CORS ===
    # Acepta JSON (["http://a","https://b"]) o lista separada por comas ("http://a,https://b")
    cors_origins: Union[str, List[str]] = ""

    # === Paginación ===
    max_page_size: int = 50

    # === Papelera ===
    trash_ttl_days: int = 14

    @validator("cors_origins", pre=True)
    def _parse_cors_origins(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                try:
                    data = json.loads(s)
                    if isinstance(data, list):
                        return [str(x).strip() for x in data if str(x).strip()]
                except Exception:
                    # si parece JSON pero está mal formado, caemos al split por comas
                    pass
            return [item.strip() for item in s.split(",") if item.strip()]
        return [str(v).strip()] if str(v).strip() else []

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Mapeo explícito a variables de entorno en mayúsculas
        fields = {
            "mongo_url": {"env": "MONGO_URL"},
            "db_name": {"env": "DB_NAME"},
            "secret_key": {"env": "SECRET_KEY"},
            "algorithm": {"env": "ALGORITHM"},
            "access_token_expire_minutes": {"env": "ACCESS_TOKEN_EXPIRE_MINUTES"},
            "login_rate_limit": {"env": "LOGIN_RATE_LIMIT"},
            "login_lock_threshold": {"env": "LOGIN_LOCK_THRESHOLD"},
            "login_lock_window_min": {"env": "LOGIN_LOCK_WINDOW_MIN"},
            "cors_origins": {"env": "CORS_ORIGINS"},
            "max_page_size": {"env": "MAX_PAGE_SIZE"},
            "trash_ttl_days": {"env": "TRASH_TTL_DAYS"},
        }


# Instancia global usada por server.py y main.py
settings = Settings()
