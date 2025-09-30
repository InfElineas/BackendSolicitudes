# app/core/app_config_service.py
import time
from typing import Optional
from app.core.db import get_db
from app.core.app_config_schema import AppConfig, Department, RequestOptions

_CACHE = {"config": None, "ts": 0.0}
_TTL = 30  # segundos

async def get_app_config(force: bool = False) -> AppConfig:
    now = time.time()
    if not force and _CACHE["config"] and (now - _CACHE["ts"] < _TTL):
        return _CACHE["config"]

    db = get_db()
    raw = await db.app_config.find_one({"_id": "app_config"}) or {}
    cfg = AppConfig(**raw)
    _CACHE["config"] = cfg
    _CACHE["ts"] = now
    return cfg

async def upsert_app_config(cfg: AppConfig) -> AppConfig:
    db = get_db()
    await db.app_config.update_one({"_id": "app_config"}, {"$set": cfg.dict(by_alias=True)}, upsert=True)
    # invalidar caché
    _CACHE["config"] = None
    return cfg

# helpers de actualización parcial
async def set_departments(depts: list[Department]) -> AppConfig:
    cfg = await get_app_config(force=True)
    cfg.departments = depts
    return await upsert_app_config(cfg)

async def set_request_options(opts: RequestOptions) -> AppConfig:
    cfg = await get_app_config(force=True)
    cfg.request_options = opts
    return await upsert_app_config(cfg)
