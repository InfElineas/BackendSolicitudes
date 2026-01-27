# app/main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from server import (
    api_router,
    limiter,
    client,
    ensure_core_indexes,
    ensure_trash_indexes,
    ensure_security_indexes,
    migrate_requests_schema,
    ensure_departments_on_startup,
    ensure_app_config_seed,
    init_data,
)

APP_NAME = os.getenv("APP_NAME", "SisAut Backend")
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")

# --- CORS: fusiona .env + defaults completos (no omitimos nada) ---
defaults = {
    # Fronts locales más comunes
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:4321",
    "http://127.0.0.1:4321",
    "http://localhost:8080",
    "http://127.0.0.1:8080",

    # Tu front en producción
    "https://solicitudesxdepartamento.netlify.app",
}
# Une lo que venga del .env (settings.cors_origins) con los defaults
CORS_ORIGINS = sorted(set((settings.cors_origins or []) + list(defaults)))

# Crea la app
app = FastAPI(title=APP_NAME, version=APP_VERSION)

# --- IMPORTANTE: CORS primero ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Luego el resto de middlewares
app.add_middleware(GZipMiddleware, minimum_size=1024)

# SlowAPI: conecta el limiter ya usado en tus endpoints
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Rutas de tu backend (respeta los paths tal como están en server.py)
app.include_router(api_router, prefix="")

# Endpoints de salud (aditivos, opcionales)
@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/ready")
async def ready():
    return {"ready": True}

# Índices y migraciones en startup (idempotente)
@app.on_event("startup")
async def startup():
    await ensure_security_indexes()
    await ensure_trash_indexes()
    await ensure_core_indexes()
    await migrate_requests_schema()
    await ensure_departments_on_startup()
    await ensure_app_config_seed()
    # opcional: solo en dev
    # await init_data()

# Shutdown limpio de la DB
@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        client.close()
    except Exception:
        pass

# Runner local opcional
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", reload=True, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
