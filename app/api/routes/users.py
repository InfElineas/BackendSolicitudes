# app/api/routes/users.py
from fastapi import APIRouter, HTTPException, Depends
from app.api.deps import require_role
from app.core.db import get_db
from app.core.security import hash_password

router = APIRouter()

@router.post("")
async def create_user(payload: dict, current=Depends(require_role(["admin"]))):
    db = get_db()
    if await db.users.find_one({"username": payload["username"]}):
        raise HTTPException(400, "Username already registered")
    user = {k:v for k,v in payload.items() if k!="password"}
    user["id"] = user.get("id") or __import__("uuid").uuid4().hex
    user["password_hash"] = hash_password(payload["password"])
    await db.users.insert_one(user)
    return user

@router.get("")
async def list_users(current=Depends(require_role(["admin"]))):
    return await get_db().users.find().to_list(1000)

@router.delete("/{user_id}")
async def delete_user(user_id: str, current=Depends(require_role(["admin"]))):
    db = get_db()
    if user_id == current["id"]:
        raise HTTPException(400, "No puedes eliminarte a ti mismo")
    user = await db.users.find_one({"id": user_id})
    if not user: raise HTTPException(404, "Usuario no encontrado")
    if user.get("role")=="admin" and await db.users.count_documents({"role":"admin"})<=1:
        raise HTTPException(400, "No puedes eliminar al último administrador")
    open_assigned = await db.requests.count_documents({"assigned_to": user_id, "status":{"$in":["Pendiente","En progreso","En revisión"]}})
    if open_assigned>0:
        raise HTTPException(400, "El usuario tiene solicitudes abiertas asignadas")
    await db.users.delete_one({"id": user_id})
    return {"ok": True}
