# app/api/routes/worklogs.py
from fastapi import APIRouter, HTTPException, Depends, Query, Body
from datetime import datetime
from typing import Optional
from app.api.deps import get_current_user, require_role
from app.core.db import get_db
from app.repositories import worklogs_repo as repo

router = APIRouter()

@router.post("/{ticket_id}/worklogs")
async def add_worklog(
    ticket_id: str,
    payload: dict = Body(...),
    current=Depends(require_role(["support","admin"])),
):
    db = get_db()
    ticket = await db.requests.find_one({"id": ticket_id})
    if not ticket:
        raise HTTPException(404, "Solicitud no encontrada")
    hours = float(payload.get("hours") or 0)
    if hours <= 0:
        raise HTTPException(422, "hours debe ser > 0")
    note = payload.get("note")
    wl = await repo.create(ticket_id=ticket_id, user=current, hours=hours, note=note)

    # opcional: sumar horas al ticket (campo acumulado)
    total = await repo.sum_hours_by_ticket(ticket_id)
    await db.requests.update_one({"id": ticket_id}, {"$set": {"worklog_hours": total}})

    return {"ok": True, "worklog": wl, "worklog_total_hours": total}

@router.get("/{ticket_id}/worklogs")
async def list_worklogs(ticket_id: str, current=Depends(get_current_user)):
    # visibilidad: solicitante, asignado, admin y support
    db = get_db()
    t = await db.requests.find_one({"id": ticket_id})
    if not t:
        raise HTTPException(404, "Solicitud no encontrada")
    if current.get("role") not in ("admin","support") and current["id"] not in (t.get("requester_id"), t.get("assigned_to")):
        raise HTTPException(403, "No autorizado")
    items = await repo.list_by_ticket(ticket_id)
    total_hours = await repo.sum_hours_by_ticket(ticket_id)
    return {"items": items, "total_hours": total_hours}

@router.get("/me/worklogs")
async def my_worklogs(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    current=Depends(require_role(["support","admin"])),
):
    items = await repo.list_by_user(current["id"], date_from, date_to)
    # agrupar por día para reportes rápidos
    by_day = {}
    total = 0.0
    for it in items:
        d = it["fecha"].date().isoformat()
        by_day.setdefault(d, 0.0)
        by_day[d] += float(it["hours"])
        total += float(it["hours"])
    return {"items": items, "sum_by_day": by_day, "total_hours": round(total, 2)}
