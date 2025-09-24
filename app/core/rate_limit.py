# app/core/rate_limit.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, enabled=True)
rate_limit_handler = _rate_limit_exceeded_handler
LOGIN_LIMIT = settings.login_rate_limit
