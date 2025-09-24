# app/main.py
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from app.core.rate_limit import limiter, rate_limit_handler
from slowapi.errors import RateLimitExceeded
from app.api.router import api_router
from app.core.indexes import startup_tasks
from app.core.config import settings

app = FastAPI(title="Sistema de Gestión de Solicitudes de Automatización")

# Rate-limit
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# CORS
allow_origins = [*settings.cors_origins, "http://localhost:3000", "http://127.0.0.1:3000",
                 "http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(CORSMiddleware,
    allow_credentials=True, allow_origins=allow_origins or ["http://localhost:3000"],
    allow_methods=["GET","POST","PUT","DELETE","OPTIONS"],
    allow_headers=["Authorization","Content-Type"], expose_headers=["*"], max_age=600
)

# Rutas
app.include_router(api_router, prefix="/api")

# Startup
@app.on_event("startup")
async def on_startup():
    await startup_tasks()

# Shutdown (Motor cierra en core.db)
