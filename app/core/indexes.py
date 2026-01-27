# app/core/indexes.py
from datetime import datetime, timedelta, timezone, date
import uuid
from app.core.db import get_db
from app.core.security import hash_password
from app.core.config import settings

OPEN_STATES = ["Pendiente","En progreso","En revisión"]

async def ensure_security_indexes(db):
    await db.failed_logins.create_index("key")
    await db.failed_logins.create_index("expireAt", expireAfterSeconds=0)

async def ensure_core_indexes(db):
    # requests principales
    await db.requests.create_index([("created_at",-1)])
    await db.requests.create_index([("requested_at",-1)])
    await db.requests.create_index([("department",1)])
    await db.requests.create_index([("status",1)])
    await db.requests.create_index([("requester_id",1)])
    await db.requests.create_index([("assigned_to",1)])
    await db.requests.create_index([("type",1)])
    await db.requests.create_index([("level",1)])
    await db.requests.create_index([("channel",1)])
    await db.requests.create_index([("completion_date",-1)])
    await db.requests.create_index([("title","text"),("description","text")])

    # app/core/indexes.py  (dentro de ensure_core_indexes)
    await db.requests.create_index([("feedback.rating", 1)])
    await db.requests.create_index([("assigned_to", 1), ("assigned_to_name", 1)])
    await db.requests.create_index([("estimated_due", 1)])
    await db.ticket_status_events.create_index([("estado", 1)])
    await db.ticket_status_events.create_index([("changed_by", 1), ("changed_at", 1)])
  

    # worklogs y tickets
    await db.ticket_status_events.create_index([("ticket_id",1),("changed_at",1)])
    await db.worklogs.create_index([("ticket_id",1)])
    await db.worklogs.create_index([("user_id",1)])
    await db.worklogs.create_index([("fecha",-1)])

    # users / departments
    await db.users.create_index([("username",1)], unique=True)
    await db.departments.create_index([("name",1)], unique=True)

    # métricas
    await db.ticket_status_events.create_index([("ticket_id",1),("changed_at",1)])
    await db.worklogs.create_index([("ticket_id",1)])
    await db.worklogs.create_index([("user_id",1)])
    await db.worklogs.create_index([("fecha",-1)])
    await db.metrics_snapshots.create_index([("periodo",1),("fecha_inicio",-1)])

async def ensure_trash_indexes(db):
    await db.requests_trash.create_index("id", unique=True)
    await db.requests_trash.create_index("expireAt", expireAfterSeconds=0)
    await db.requests_trash.create_index([("deleted_at",-1)])
    await db.requests_trash.create_index([("request_doc.title","text"),("request_doc.description","text")])

STATUS_SYNONYMS = {
    "Completada":"Finalizada","Completado":"Finalizada","completada":"Finalizada","completado":"Finalizada",
    "En Progreso":"En progreso","En Revisión":"En revisión","Cancelada":"Rechazada","Cancelado":"Rechazada",
}

async def migrate_requests_schema(db):
    await db.requests.update_many({"type":{"$exists":False}}, {"$set":{"type":"Soporte"}})
    await db.requests.update_many({"channel":{"$exists":False}}, {"$set":{"channel":"Sistema"}})
    await db.requests.update_many({"status":{"$exists":False}}, {"$set":{"status":"Pendiente"}})
    for k,v in STATUS_SYNONYMS.items():
        await db.requests.update_many({"status":k}, {"$set":{"status":v}})

async def init_data(db):
    if await db.users.find_one({"role":"admin"}):
        return
    # departments seed (igual que tenías)
    departments_data = [
        {"name":"Administración","description":"Gestión administrativa y coordinación general"},
        {"name":"Contabilidad y Finanzas","description":"Gestión financiera, contabilidad y control económico"},
        {"name":"Comercial","description":"Estrategias y actividades comerciales"},
        {"name":"Inventario","description":"Control y gestión de inventarios"},
        {"name":"Informática","description":"Soporte tecnológico y sistemas de información"},
        {"name":"Facturación","description":"Gestión de facturación y cobros"},
        {"name":"Expedición","description":"Preparación y envío de pedidos"},
        {"name":"Calidad","description":"Control y aseguramiento de calidad"},
        {"name":"Transporte y Distribución","description":"Logística de transporte y entrega de mercancías"},
        {"name":"Mantenimiento","description":"Mantenimiento preventivo y correctivo"},
        {"name":"Punto de Venta","description":"Atención y gestión en el punto de venta"},
        {"name":"Almacén","description":"Gestión de almacenamiento"},
        {"name":"Picker and Packer","description":"Selección y empaquetado"},
        {"name":"Estibadores","description":"Carga y descarga"},
    ]
    now = datetime.now(timezone.utc)
    for d in departments_data:
        await db.departments.insert_one({"id":str(uuid.uuid4()),"name":d["name"],"description":d["description"],"created_at":now})

    users = [
        {"username":"admin","password":"admin123","full_name":"Administrador Sistema","department":"Directivos","position":"Jefe de departamento","role":"admin"},
        {"username":"soporte1","password":"soporte123","full_name":"Juan Pérez","department":"Directivos","position":"Especialista","role":"support"},
        {"username":"soporte2","password":"soporte123","full_name":"María González","department":"Directivos","position":"Especialista","role":"support"},
        {"username":"facturacion1","password":"user123","full_name":"Carlos López","department":"Facturación","position":"Jefe de departamento","role":"employee"},
    ]
    for u in users:
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "username": u["username"], "full_name": u["full_name"],
            "department": u["department"], "position": u["position"], "role": u["role"],
            "created_at": now, "password_hash": hash_password(u["password"])
        })

async def startup_tasks():
    db = get_db()
    await ensure_security_indexes(db)
    await ensure_core_indexes(db)
    await ensure_trash_indexes(db)
    await migrate_requests_schema(db)
    await init_data(db)

