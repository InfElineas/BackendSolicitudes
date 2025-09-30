# app/core/db.py
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings
import certifi

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def get_client() -> AsyncIOMotorClient:
    """
    Crea un único cliente Motor con TLS y CA bundle de certifi.
    Compatible con mongodb+srv (Atlas) y mongodb:// local.
    """
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.mongo_url,
            tls=True,                      # fuerza TLS; en local no molesta, en Atlas es requerido
            tlsCAFile=certifi.where(),     # CA bundle correcto en Windows/macOS/Linux
            serverSelectionTimeoutMS=20000 # mismo timeout que muestra tu traza
        )
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        _db = get_client()[settings.db_name]
    return _db


async def close_db() -> None:
    """
    Cierra el cliente global. Usado por app/main.py en shutdown.
    """
    global _client, _db
    if _client:
        _client.close()
    _client = None
    _db = None
