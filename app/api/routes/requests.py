# app/api/routes/requests.py
from fastapi import APIRouter, HTTPException, Query, Depends
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from app.api.deps import get_current_user, require_role
from app.core.db import get_db
from app.core.config import settings
from app.services.request_service import ensure_transition, normalize, assign as svc_assign, classify as svc_classify
from app.utils.mongo_helpers import fix_mongo_id

router = APIRouter()

@router.post("")
async def create_request(payload: dict, current=Depends(get_current_user)):
    db = get_db()
    data = {k: v for k, v in (payload or {}).items() if v is not None}
    data.setdefault("requested_at", datetime.now(timezone.utc))

    new_req = {
        "id": __import__("uuid").uuid4().hex,
        "title": data["title"],
        "description": data["description"],
        "priority": data["priority"],
        "type": data["type"],
        "channel": data.get("channel", "Sistema"),
        "requester_id": current["id"],
        "requester_name": current["full_name"],
        "department": current["department"],
        "requested_at": data["requested_at"],
        "status": "Pendiente",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "state_history": [{
            "from_status": None,
            "to_status": "Pendiente",
            "at": datetime.now(timezone.utc),
            "by_user_id": current["id"],
            "by_user_name": current["full_name"]
        }],
        "reabierto_count": 0
    }

    if current["role"] == "admin":
        for k in ("level", "estimated_hours", "estimated_due"):
            if k in data:
                new_req[k] = data[k]
        if data.get("assigned_to"):
            u = await db.users.find_one({"id": data["assigned_to"]})
            if not u:
                raise HTTPException(400, "Usuario asignado no existe")
            new_req["assigned_to"] = u["id"]
            new_req["assigned_to_name"] = u["full_name"]

    await db.requests.insert_one(new_req)

    await db.ticket_status_events.insert_one({
        "id": __import__("uuid").uuid4().hex,
        "ticket_id": new_req["id"],
        "estado": "Pendiente",
        "changed_by": current["id"],
        "changed_at": datetime.now(timezone.utc)
    })

    return fix_mongo_id(new_req)  # 👈 aquí convertimos bien el _id si existe

@router.get("")
async def get_requests(
    current=Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=settings.max_page_size),
    status: Optional[str] = None, department: Optional[str] = None, q: Optional[str] = None,
    sort: Optional[str] = Query("-created_at"), request_type: Optional[str] = Query(None, alias="type"),
    level: Optional[int] = Query(None, ge=1, le=3), assigned_to: Optional[str] = None,
    channel: Optional[str] = None, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
):
    db = get_db()
    filt: Dict[str,Any] = {}
    if current["role"]=="employee": filt["requester_id"]=current["id"]
    if status: filt["status"]=status
    if department: filt["department"]=department
    if request_type: filt["type"]=request_type
    if level: filt["level"]=level
    if assigned_to: filt["assigned_to"]=assigned_to
    if channel: filt["channel"]=channel
    if date_from or date_to:
        dr={}
        if date_from: dr["$gte"]=date_from
        if date_to: dr["$lte"]=date_to
        filt["requested_at"]=dr
    if q: filt["$text"]={"$search": q}

    sort_field, sort_dir = ("created_at",-1)
    if sort:
        if sort.startswith("-"): sort_field, sort_dir = (sort[1:], -1)
        else: sort_field, sort_dir = (sort, 1)
    if sort_field not in {"created_at","status","department","requested_at","priority","level"}:
        sort_field="created_at"

    total = await db.requests.count_documents(filt)
    total_pages = max((total + page_size - 1)//page_size, 1)
    page = min(page, total_pages)
    items = await db.requests.find(filt).sort(sort_field, sort_dir).skip((page-1)*page_size).limit(page_size).to_list(page_size)
    items = [normalize(d) for d in items]
    return {
        "items": items, "page": page, "page_size": page_size, "total": total,
        "total_pages": total_pages, "has_prev": page>1, "has_next": page<total_pages
    }


@router.post("/{request_id}/classify")
async def classify(request_id: str, payload: dict, current=Depends(require_role(["admin"]))):
    return await svc_classify(request_id, int(payload["level"]), payload["priority"], current)

@router.post("/{request_id}/assign")
async def assign(request_id: str, payload: dict, current=Depends(require_role(["admin"]))):
    db = get_db()
    target_id = payload.get("assigned_to") or current["id"]
    target = await db.users.find_one({"id": target_id})
    if not target: raise HTTPException(400, "Usuario destino no encontrado")
    return await svc_assign(request_id, target, payload.get("estimated_hours"), payload.get("estimated_due"), current)


@router.post("/{request_id}/transition")
async def transition(request_id: str, payload: dict, current=Depends(require_role(["support","admin"]))):
    db = get_db()
    doc = await db.requests.find_one({"id": request_id})
    if not doc: raise HTTPException(404, "Request not found")
    now = datetime.now(timezone.utc)
    to_status = payload["to_status"]
    ensure_transition(doc["status"], to_status)

    # reglas
    if to_status=="Rechazada":
        comment = (payload.get("comment") or "").strip()
        if not comment: raise HTTPException(422, "Debe indicar el motivo del rechazo.")
    if to_status=="En revisión":
        allowed = {doc.get("assigned_to"), doc.get("requester_id")}
        if current["id"] not in allowed and current.get("role")!="admin":
            raise HTTPException(403, "Solo el asignado o quien asignó pueden enviar a revisión.")
        if not (payload.get("evidence_link") or "").strip():
            raise HTTPException(422, "Debe adjuntar evidencia (enlace).")

    set_ops = {"status": to_status, "updated_at": now}
    if to_status in {"Finalizada","Rechazada"}: set_ops["completion_date"]=now
    if to_status=="Rechazada": set_ops["rejection_reason"]=payload.get("comment","").strip()
    if to_status=="En revisión":
        set_ops["review_evidence"]={"type":"link","url":payload.get("evidence_link").strip(),"by":current["id"],"at":now}

    ev = {"from_status": doc["status"], "to_status": to_status, "by_user_id": current["id"], "by_user_name": current["full_name"], "at": now}
    ops = {"$set": set_ops, "$push": {"state_history": ev}}
    if doc["status"]=="Finalizada" and to_status in {"Pendiente","En progreso","En revisión"}:
        ops.setdefault("$inc", {})["reabierto_count"]=1

    await db.requests.update_one({"id": request_id}, ops)
    await db.ticket_status_events.insert_one({"id":__import__("uuid").uuid4().hex,"ticket_id":request_id,"estado":to_status,"changed_by":current["id"],"changed_at":now})
    return normalize(await db.requests.find_one({"id": request_id}))

@router.post("/{request_id}/feedback")
async def feedback(request_id: str, payload: dict, current=Depends(require_role(["employee","admin","support"]))):
    db = get_db()
    doc = await db.requests.find_one({"id": request_id})
    if not doc: raise HTTPException(404, "Request not found")
    if current.get("role")!="admin" and doc["requester_id"]!=current["id"]:
        raise HTTPException(403, "Solo el solicitante puede enviar feedback")
    if doc["status"]!="Finalizada": raise HTTPException(400, "La solicitud no está finalizada")
    if doc.get("feedback") is not None: raise HTTPException(400, "El feedback ya fue registrado")
    fb = {"rating": payload["rating"], "comment": payload.get("comment"), "by_user_id": current["id"], "by_user_name": current["full_name"], "at": datetime.now(timezone.utc)}
    await db.requests.update_one({"id": request_id}, {"$set":{"feedback": fb}})
    return normalize(await db.requests.find_one({"id": request_id}))
