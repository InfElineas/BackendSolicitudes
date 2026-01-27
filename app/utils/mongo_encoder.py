# app/utils/mongo_encoder.py
from bson import ObjectId
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime
import json

def convert_mongo_types(obj):
    """Convierte recursivamente ObjectId -> str y datetime -> ISO8601."""
    if isinstance(obj, list):
        return [convert_mongo_types(o) for o in obj]
    if isinstance(obj, dict):
        return {k: convert_mongo_types(v) for k, v in obj.items()}
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj

class ObjectIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Solo tocar JSON
        content_type = (response.headers.get("content-type") or "").lower()
        if not content_type.startswith("application/json"):
            return response

        try:
            # Leer body actual, normalizar y reconstruir preservando headers
            raw = response.body
            data = json.loads(raw.decode()) if isinstance(raw, (bytes, bytearray)) else raw
            normalized = convert_mongo_types(data)

            headers = dict(response.headers)  # 👈 preserva CORS y demás
            return JSONResponse(
                content=normalized,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
                background=response.background,
            )
        except Exception:
            # Si algo falla, devuelve la respuesta tal cual
            return response
