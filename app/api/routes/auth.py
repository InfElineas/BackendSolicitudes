# app/api/routes/auth.py
from fastapi import APIRouter, HTTPException, Body, Form, Request as FastAPIRequest, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.rate_limit import limiter, LOGIN_LIMIT
from app.core.db import get_db
from app.core.config import settings
from app.core.security import verify_password, create_access_token
from app.api.deps import get_current_user
from app.utils.mongo_helpers import fix_mongo_id

router = APIRouter(prefix="/auth")
security = HTTPBearer()

@router.post("/login")
@limiter.limit(LOGIN_LIMIT)
async def login(
    request: FastAPIRequest,
    user_login: dict | None = Body(default=None),
    username: str | None = Form(default=None),
    password: str | None = Form(default=None),
):
    # Payload flexible como hoy
    if user_login is None and username and password:
        user_login = {"username": username, "password": password}
    if user_login is None:
        try:
            raw = await request.json()
            if isinstance(raw, dict) and "username" in raw and "password" in raw:
                user_login = {"username": raw["username"], "password": raw["password"]}
        except Exception:
            pass
    if user_login is None:
        raise HTTPException(422, "username/password required")

    db = get_db()
    user_doc = await db.users.find_one({"username": user_login["username"]})
    if not user_doc or not verify_password(user_login["password"], user_doc["password_hash"]):
        # Anti-brute como lo tenías: registrarlo si deseas (omito por brevedad)
        raise HTTPException(401, "Incorrect username or password")

    token = create_access_token(sub=user_doc["username"])
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    # devuelve el usuario (compat)
    return fix_mongo_id(current_user)

