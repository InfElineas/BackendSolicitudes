# app/core/db.py
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(str(settings.mongo_url))
        _db = _client[settings.db_name]
    return _db

def get_client() -> AsyncIOMotorClient:
    get_db()
    return _client

async def close_db():
    global _client
    if _client:
        _client.close()
