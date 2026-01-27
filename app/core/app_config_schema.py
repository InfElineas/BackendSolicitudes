# app/core/app_config_schema.py (sugerido)
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class Department(BaseModel):
    code: Optional[str] = None
    name: str
    description: Optional[str] = None
    is_active: bool = True

class RequestOptions(BaseModel):
    levels: List[str] = ["baja", "media", "alta", "crítica"]
    classifications: List[str] = ["Incidencia", "Solicitud", "Mejora"]
    categories: List[str] = []  # si usas categorías específicas
    statuses: List[str] = ["Pendiente", "En progreso", "Completada", "Rechazada"]
    sla_hours_by_priority: Dict[str, int] = {"baja": 72, "media": 48, "alta": 24, "crítica": 8}

class AppConfig(BaseModel):
    _id: str = Field(default="app_config", alias="_id")
    departments: List[Department] = []
    request_options: RequestOptions = RequestOptions()
