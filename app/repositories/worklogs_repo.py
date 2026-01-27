# app/repositories/worklogs_repo.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from app.core.db import get_db

async def create(ticket_id: str, user: dict, hours: float, note: str | None) -> dict:
    doc = {
        "id": __import__("uuid").uuid4().hex,
        "ticket_id": ticket_id,
        "user_id": user["id"],
        "user_name": user["full_name"],
        "hours": float(hours),
        "note": (note or "").strip() or None,
        "fecha": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    }
    await get_db().worklogs.insert_one(doc)
    return doc

async def list_by_ticket(ticket_id: str, limit: int = 200) -> List[dict]:
    cur = get_db().worklogs.find({"ticket_id": ticket_id}).sort("fecha", -1).limit(limit)
    return await cur.to_list(length=limit)

async def list_by_user(user_id: str, date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 500) -> List[dict]:
    filt: Dict[str, Any] = {"user_id": user_id}
    if date_from or date_to:
        r = {}
        if date_from: r["$gte"] = date_from
        if date_to: r["$lte"] = date_to
        filt["fecha"] = r
    cur = get_db().worklogs.find(filt).sort("fecha", -1).limit(limit)
    return await cur.to_list(length=limit)

async def sum_hours_by_ticket(ticket_id: str) -> float:
    agg = [
        {"$match": {"ticket_id": ticket_id}},
        {"$group": {"_id": None, "total": {"$sum": "$hours"}}}
    ]
    res = await get_db().worklogs.aggregate(agg).to_list(1)
    return float(res[0]["total"]) if res else 0.0
