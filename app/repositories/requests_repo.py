# app/repositories/requests_repo.py
from typing import Dict, Any, List
from app.core.db import get_db

async def find_by_id(request_id: str) -> dict | None:
    return await get_db().requests.find_one({"id": request_id})

async def insert(doc: dict):
    await get_db().requests.insert_one(doc)

async def update_by_id(request_id: str, ops: Dict[str,Any]):
    await get_db().requests.update_one({"id": request_id}, ops)

async def delete_to_trash(doc: dict, actor: dict, ttl_days: int):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    trash_doc = {
        "id": doc["id"], "request_doc": doc, "deleted_at": now,
        "deleted_by_id": actor["id"], "deleted_by_name": actor["full_name"],
        "expireAt": now + timedelta(days=ttl_days),
    }
    db = get_db()
    await db.requests_trash.insert_one(trash_doc)
    await db.requests.delete_one({"id": doc["id"]})

async def list_paginated(filt: Dict[str,Any], sort_field: str, sort_dir: int, skip: int, limit: int) -> List[dict]:
    cur = get_db().requests.find(filt).sort(sort_field, sort_dir).skip(skip).limit(limit)
    return await cur.to_list(length=limit)

async def count(filt: Dict[str,Any]) -> int:
    return await get_db().requests.count_documents(filt)
