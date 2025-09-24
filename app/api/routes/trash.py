# app/api/routes/trash.py
from fastapi import APIRouter, HTTPException, Query, Depends
from app.api.deps import require_role
from app.core.db import get_db
from app.core.config import settings
from app.repositories import requests_repo as repo

router = APIRouter()

@router.delete("/{request_id}")
async def soft_delete(request_id: str, current=Depends(require_role(["admin"]))):
    doc = await repo.find_by_id(request_id)
    if not doc: raise HTTPException(404, "Request not found")
    await repo.delete_to_trash(doc, actor=current, ttl_days=settings.trash_ttl_days)
    return {"ok": True}

@router.get("/trash")
async def list_trash(current=Depends(require_role(["admin"])),
                     page: int = Query(1, ge=1),
                     page_size: int = Query(10, ge=1, le=settings.max_page_size),
                     q: str | None = Query(None)):
    db = get_db()
    filt = {}
    if q: filt["$text"]={"$search": q}
    total = await db.requests_trash.count_documents(filt)
    total_pages = max((total + page_size - 1)//page_size, 1); page = min(page,total_pages)
    cur = db.requests_trash.find(filt).sort("deleted_at",-1).skip((page-1)*page_size).limit(page_size)
    docs = await cur.to_list(length=page_size)
    def m(d):
        r = d.get("request_doc",{})
        return {
            "id": d["id"],
            "title": r.get("title","—"),
            "department": r.get("department","—"),
            "requester_name": r.get("requester_name","—"),
            "deleted_at": d.get("deleted_at"),
            "deleted_by_name": d.get("deleted_by_name","—"),
            "expires_at": d.get("expireAt"),
        }
    items = [m(d) for d in docs]
    return {"items": items, "page": page, "page_size": page_size, "total": total,
            "total_pages": total_pages, "has_prev": page>1, "has_next": page<total_pages}

@router.post("/{request_id}/restore")
async def restore(request_id: str, current=Depends(require_role(["admin"]))):
    db = get_db()
    tr = await db.requests_trash.find_one({"id": request_id})
    if not tr: raise HTTPException(404, "No está en papelera")
    if await db.requests.find_one({"id": request_id}):
        raise HTTPException(409, "Ya existe una solicitud con ese id")
    doc = tr["request_doc"]; doc["updated_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    await db.requests.insert_one(doc); await db.requests_trash.delete_one({"id": request_id})
    return doc

@router.delete("/trash/{request_id}")
async def purge(request_id: str, current=Depends(require_role(["admin"]))):
    res = await get_db().requests_trash.delete_one({"id": request_id})
    if res.deleted_count == 0: raise HTTPException(404, "No está en papelera")
    return {"ok": True}
