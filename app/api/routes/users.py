# app/api/routes/users.py
from fastapi import APIRouter, HTTPException, Depends
from app.api.deps import require_role
from app.core.db import get_db
from app.core.security import hash_password
from app.api.deps import require_role, get_current_user

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

@router.patch("/me")
async def update_my_profile(payload: dict, current=Depends(get_current_user)):
    """
    Permite al usuario autenticado actualizar su nombre y/o contraseña.
    No requiere rol admin.
    """
    db = get_db()

    # compatible con current dict o Pydantic model
    user_id = current.get("id") if isinstance(current, dict) else getattr(current, "id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="User identification missing")

    # solo permitimos estos campos desde perfil
    allowed = {}
    if "full_name" in payload and payload["full_name"] is not None:
        allowed["full_name"] = payload["full_name"]

    if "password" in payload and payload["password"]:
        allowed["password_hash"] = hash_password(payload["password"])

    if not allowed:
        # nada que actualizar
        # Devolver el usuario actual (sin password_hash)
        user = await db.users.find_one({"id": user_id})
        if user:
            user.pop("password_hash", None)
        return user

    allowed["updated_at"] = datetime.utcnow()

    await db.users.update_one({"id": user_id}, {"$set": allowed})
    updated = await db.users.find_one({"id": user_id})
    if updated:
        updated.pop("password_hash", None)
    return updated


from datetime import datetime

@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    payload: dict,
    current=Depends(require_role(["admin"]))
):
    db = get_db()

    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(404, "Usuario no encontrado")

    # No permitir cambiar username a uno existente
    if "username" in payload and payload["username"] != user["username"]:
        if await db.users.find_one({"username": payload["username"]}):
            raise HTTPException(400, "Username ya existe")

    update_data = {k: v for k, v in payload.items() if k not in ["id", "password"]}

    # Si viene password, actualizar hash
    if "password" in payload and payload["password"]:
        update_data["password_hash"] = hash_password(payload["password"])

    update_data["updated_at"] = datetime.utcnow()

    await db.users.update_one(
        {"id": user_id},
        {"$set": update_data}
    )

    updated = await db.users.find_one({"id": user_id})
    return updated


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



