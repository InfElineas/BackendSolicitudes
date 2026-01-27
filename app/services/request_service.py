# app/services/request_service.py
from datetime import datetime, timezone
from typing import Dict, Any
from app.models.common import ALLOWED_TRANSITIONS, OPEN_STATES
from app.repositories import requests_repo as repo
from fastapi import HTTPException

def ensure_transition(old: str, new: str):
    if new not in ALLOWED_TRANSITIONS[old]:
        raise HTTPException(status_code=400, detail=f"Transición no permitida: {old} → {new}")

STATUS_FIX = {
    "Completada":"Finalizada","Completado":"Finalizada","completada":"Finalizada","completado":"Finalizada",
    "En Progreso":"En progreso","En Revisión":"En revisión","Cancelada":"Rechazada","Cancelado":"Rechazada",
}
VALID = {"Pendiente","En progreso","En revisión","Finalizada","Rechazada"}

def normalize(doc: Dict[str,Any]) -> Dict[str,Any]:
    out = dict(doc)
    out.setdefault("type","Soporte")
    out.setdefault("channel","Sistema")
    out.setdefault("status","Pendiente")
    st = out.get("status")
    if isinstance(st,str) and st in STATUS_FIX: out["status"]=STATUS_FIX[st]
    if out["status"] not in VALID: out["status"]="Pendiente"
    return out

async def classify(request_id: str, level: int, priority: str, actor: dict):
    now = datetime.now(timezone.utc)
    await repo.update_by_id(request_id, {"$set": {"level": level, "priority": priority, "updated_at": now}})
    doc = await repo.find_by_id(request_id)
    return normalize(doc)

async def assign(request_id: str, to_user: dict, estimated_hours, estimated_due, actor: dict):
    now = datetime.now(timezone.utc)
    upd = {
        "assigned_to": to_user["id"], "assigned_to_name": to_user["full_name"],
        "estimated_hours": estimated_hours, "estimated_due": estimated_due,
        "updated_at": now, "requester_id": actor["id"], "requester_name": actor["full_name"],
    }
    await repo.update_by_id(request_id, {"$set": upd})
    doc = await repo.find_by_id(request_id)
    return normalize(doc)
