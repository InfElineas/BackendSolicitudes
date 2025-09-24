# app/api/router.py
from fastapi import APIRouter
from app.api.routes import auth, users, departments, requests, trash, metrics, worklogs

api_router = APIRouter()
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(departments.router, prefix="/departments", tags=["departments"])
api_router.include_router(requests.router, prefix="/requests", tags=["requests"])
api_router.include_router(trash.router, prefix="/requests", tags=["trash"])
api_router.include_router(metrics.router, tags=["metrics"])       # <— asegúrate de incluir
api_router.include_router(worklogs.router, prefix="/requests", tags=["worklogs"])  # <— y este
