from fastapi import (
    FastAPI, APIRouter, HTTPException, Depends,
    Body, Form, Query, Request as FastAPIRequest
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, uuid
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime, timezone, timedelta, date
import jwt
from passlib.context import CryptContext
from collections import defaultdict

# Rate limiting (SlowAPI)
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---- MongoDB connection ----
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# ---- Security & JWT ----
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# ---- Security params from ENV ----
LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "5/minute")
LOGIN_LOCK_THRESHOLD = int(os.environ.get("LOGIN_LOCK_THRESHOLD", "8"))
LOGIN_LOCK_WINDOW_MIN = int(os.environ.get("LOGIN_LOCK_WINDOW_MIN", "15"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# ---- App ----
app = FastAPI(title="Sistema de Gestión de Solicitudes de Automatización")
api_router = APIRouter(prefix="/api")

# ---- SlowAPI limiter ----
limiter = Limiter(key_func=get_remote_address, enabled=True)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================
#            Models
# ============================
RequestType = Literal["Soporte", "Mejora", "Desarrollo", "Capacitación"]
RequestChannel = Literal["WhatsApp", "Correo", "Sistema"]
RequestStatus = Literal["Pendiente", "En progreso", "En revisión", "Finalizada", "Rechazada"]

OPEN_STATES = ["Pendiente", "En progreso", "En revisión"]

class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    full_name: str
    department: str
    position: str  # "Jefe de departamento" | "Especialista"
    role: str      # "admin" | "support" | "employee"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    department: str
    position: str
    role: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class Department(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StateEvent(BaseModel):
    from_status: Optional[RequestStatus] = None
    to_status: RequestStatus
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    by_user_id: str
    by_user_name: str

class Feedback(BaseModel):
    rating: Literal["up", "down"]
    comment: Optional[str] = None
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    by_user_id: str
    by_user_name: str

class Request(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    priority: Literal["Alta", "Media", "Baja"]
    # Defaults seguros para datos antiguos
    type: RequestType = "Soporte"
    channel: RequestChannel = "Sistema"
    level: Optional[int] = None            # 1|2|3
    status: RequestStatus = "Pendiente"
    requester_id: str
    requester_name: str
    department: str
    assigned_to: Optional[str] = None
    assigned_to_name: Optional[str] = None
    estimated_hours: Optional[float] = None
    estimated_due: Optional[datetime] = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completion_date: Optional[datetime] = None
    state_history: List[StateEvent] = Field(default_factory=list)
    feedback: Optional[Feedback] = None
    rejection_reason: Optional[str] = None
    review_evidence: Optional[Dict[str, Any]] = None  # {"type":"link","url":"...", "by":"user_id","at":datetime}
    reabierto_count: int = 0

class RequestCreate(BaseModel):
    title: str
    description: str
    priority: Literal["Alta", "Media", "Baja"]
    type: RequestType
    channel: RequestChannel = "Sistema"
    requested_at: Optional[datetime] = None
        # campos opcionales (solo aplicarán si el usuario tiene permiso)
    level: Optional[int] = Field(default=None, ge=1, le=3)
    assigned_to: Optional[str] = None
    estimated_hours: Optional[float] = None
    estimated_due: Optional[datetime] = None

class RequestUpdate(BaseModel):
    status: Optional[RequestStatus] = None
    assigned_to: Optional[str] = None
    estimated_hours: Optional[float] = None
    estimated_due: Optional[datetime] = None

class ClassifyPayload(BaseModel):
    level: int = Field(ge=1, le=3)
    priority: Literal["Alta", "Media", "Baja"]

class AssignPayload(BaseModel):
    assigned_to: Optional[str] = None
    estimated_hours: Optional[float] = None
    estimated_due: Optional[datetime] = None

class TransitionPayload(BaseModel):
    to_status: RequestStatus
    comment: Optional[str] = None            # requerido si to_status == "Rechazada"
    evidence_link: Optional[str] = None      # requerido si to_status == "En revisión"

class FeedbackPayload(BaseModel):
    rating: Literal["up", "down"]
    comment: Optional[str] = None

class WorklogCreate(BaseModel):
    horas: float = Field(gt=0)
    nota: Optional[str] = None

class PaginatedRequests(BaseModel):
    items: List[Request]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool

# ============================
#       Helper functions
# ============================
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    user = await db.users.find_one({"username": username})
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return User(**user)

def require_role(required_roles: List[str]):
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in required_roles:
            raise HTTPException(status_code=403, detail="Not authorized")
        return current_user
    return role_checker

ALLOWED_TRANSITIONS: Dict[RequestStatus, set] = {
    "Pendiente": {"En progreso", "Rechazada"},
    "En progreso": {"En revisión"},
    "En revisión": {"Finalizada", "En progreso"},
    "Finalizada": set(),
    "Rechazada": set(),
}

def ensure_transition(old: RequestStatus, new: RequestStatus):
    if new not in ALLOWED_TRANSITIONS[old]:
        raise HTTPException(status_code=400, detail=f"Transición no permitida: {old} → {new}")

# --- Normalización de docs (para datos heredados) ---
VALID_STATUSES = {"Pendiente", "En progreso", "En revisión", "Finalizada", "Rechazada"}
STATUS_SYNONYMS = {
    "Completada": "Finalizada",
    "Completado": "Finalizada",
    "completada": "Finalizada",
    "completado": "Finalizada",
    "En Progreso": "En progreso",
    "En Revisión": "En revisión",
    "Cancelada": "Rechazada",
    "Cancelado": "Rechazada",
}

def _normalize_request_doc(d: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(d)
    out.setdefault("type", "Soporte")
    out.setdefault("channel", "Sistema")
    out.setdefault("status", "Pendiente")
    st = out.get("status")
    if isinstance(st, str) and st in STATUS_SYNONYMS:
        out["status"] = STATUS_SYNONYMS[st]
    if out.get("status") not in VALID_STATUSES:
        out["status"] = "Pendiente"
    return out

def _to_request(doc: Dict[str, Any]) -> Request:
    return Request(**_normalize_request_doc(doc))

# === Anti-brute force with Mongo TTL ===
async def ensure_security_indexes():
    try:
        await db.failed_logins.create_index("key")
        await db.failed_logins.create_index("expireAt", expireAfterSeconds=0)
    except Exception:
        pass

# ---- Core indexes ----
TRASH_TTL_DAYS = 14

async def ensure_trash_indexes():
    try:
        await db.requests_trash.create_index("id", unique=True)
        await db.requests_trash.create_index("expireAt", expireAfterSeconds=0)
        await db.requests_trash.create_index([("deleted_at", -1)])
        await db.requests_trash.create_index([("request_doc.title", "text"), ("request_doc.description", "text")])
    except Exception:
        pass

async def ensure_core_indexes():
    try:
        # requests
        await db.requests.create_index([("created_at", -1)])
        await db.requests.create_index([("requested_at", -1)])
        await db.requests.create_index([("department", 1)])
        await db.requests.create_index([("status", 1)])
        await db.requests.create_index([("requester_id", 1)])
        await db.requests.create_index([("assigned_to", 1)])
        await db.requests.create_index([("type", 1)])
        await db.requests.create_index([("level", 1)])
        await db.requests.create_index([("channel", 1)])
        await db.requests.create_index([("completion_date", -1)])
        await db.requests.create_index([("title", "text"), ("description", "text")])

        # users / departments
        await db.users.create_index([("username", 1)], unique=True)
        await db.departments.create_index([("name", 1)], unique=True)

        # métricas
        await db.ticket_status_events.create_index([("ticket_id", 1), ("changed_at", 1)])
        await db.worklogs.create_index([("ticket_id", 1)])
        await db.worklogs.create_index([("user_id", 1)])
        await db.worklogs.create_index([("fecha", -1)])
        await db.metrics_snapshots.create_index([("periodo", 1), ("fecha_inicio", -1)])
    except Exception:
        pass

# ---- Migración de datos existentes ----
async def migrate_requests_schema():
    # Defaults faltantes
    await db.requests.update_many({"type": {"$exists": False}}, {"$set": {"type": "Soporte"}})
    await db.requests.update_many({"channel": {"$exists": False}}, {"$set": {"channel": "Sistema"}})
    await db.requests.update_many({"status": {"$exists": False}}, {"$set": {"status": "Pendiente"}})
    # Estados obsoletos → válidos
    for k, v in STATUS_SYNONYMS.items():
        await db.requests.update_many({"status": k}, {"$set": {"status": v}})

async def record_failed_login(username: str, ip: str, window_min: int):
    now = datetime.utcnow()
    await db.failed_logins.insert_one({
        "key": f"{username}|{ip}",
        "createdAt": now,
        "expireAt": now + timedelta(minutes=window_min),
    })

async def is_locked(username: str, ip: str, threshold: int, window_min: int) -> bool:
    since = datetime.utcnow() - timedelta(minutes=window_min)
    key = f"{username}|{ip}"
    count = await db.failed_logins.count_documents({"key": key, "createdAt": {"$gte": since}})
    return count >= threshold

# ============================
#      Seed sample data
# ============================
async def init_data():
    existing_user = await db.users.find_one({"role": "admin"})
    if existing_user:
        return

    # Departments
    departments_data = [
    {"name": "Administración", "description": "Gestión administrativa y coordinación general"},
    {"name": "Contabilidad y Finanzas", "description": "Gestión financiera, contabilidad y control económico"},
    {"name": "Comercial", "description": "Estrategias y actividades comerciales"},
    {"name": "Inventario", "description": "Control y gestión de inventarios"},
    {"name": "Informática", "description": "Soporte tecnológico y sistemas de información"},
    {"name": "Facturación", "description": "Gestión de facturación y cobros"},
    {"name": "Expedición", "description": "Preparación y envío de pedidos"},
    {"name": "Calidad", "description": "Control y aseguramiento de calidad"},
    {"name": "Transporte y Distribución", "description": "Logística de transporte y entrega de mercancías"},
    {"name": "Mantenimiento", "description": "Mantenimiento preventivo y correctivo de instalaciones y equipos"},
    {"name": "Punto de Venta", "description": "Atención y gestión en el punto de venta"},
    {"name": "Almacén", "description": "Gestión de almacenamiento y organización de mercancías"},
    {"name": "Picker and Packer", "description": "Selección, empaquetado y preparación de productos"},
    {"name": "Estibadores", "description": "Carga, descarga y manipulación de mercancías"}
]
    for d in departments_data:
        await db.departments.insert_one(Department(**d).dict())

    # Users
    users_data = [
        {"username": "admin", "password": "admin123", "full_name": "Administrador Sistema",
         "department": "Directivos", "position": "Jefe de departamento", "role": "admin"},
        {"username": "soporte1", "password": "soporte123", "full_name": "Juan Pérez",
         "department": "Directivos", "position": "Especialista", "role": "support"},
        {"username": "soporte2", "password": "soporte123", "full_name": "María González",
         "department": "Directivos", "position": "Especialista", "role": "support"},
        {"username": "facturacion1", "password": "user123", "full_name": "Carlos López",
         "department": "Facturación", "position": "Jefe de departamento", "role": "employee"},
        {"username": "inventario1", "password": "user123", "full_name": "Ana Martínez",
         "department": "Inventario", "position": "Especialista", "role": "employee"},
        {"username": "comercial1", "password": "user123", "full_name": "Pedro Sánchez",
         "department": "Comerciales", "position": "Especialista", "role": "employee"},
        {"username": "rrhh1", "password": "user123", "full_name": "Laura Torres",
         "department": "Recursos Humanos", "position": "Jefe de departamento", "role": "employee"},
    ]
    username_to_doc: Dict[str, dict] = {}
    for u in users_data:
        hashed = get_password_hash(u["password"])
        user_doc = User(**{k: v for k, v in u.items() if k != "password"}).dict()
        user_doc["password_hash"] = hashed
        await db.users.insert_one(user_doc)
        username_to_doc[u["username"]] = user_doc

    admin_id = username_to_doc["admin"]["id"]

    # Requests de ejemplo (con IDs reales)
    sample_reqs = [
        {"title": "Automatizar facturación mensual",
         "description": "Generar facturas recurrentes para contratos mensuales",
         "priority": "Alta", "status": "Pendiente",
         "type": "Desarrollo", "channel": "Sistema", "level": 3,
         "requester_id": username_to_doc["facturacion1"]["id"], "requester_name": "Carlos López", "department": "Facturación"},
        {"title": "Alertas de stock bajo",
         "description": "Notificaciones cuando el inventario esté por debajo del mínimo",
         "priority": "Media", "status": "En progreso",
         "type": "Mejora", "channel": "Sistema", "level": 2,
         "requester_id": username_to_doc["inventario1"]["id"], "requester_name": "Ana Martínez", "department": "Inventario",
         "assigned_to": username_to_doc["soporte1"]["id"], "assigned_to_name": "Juan Pérez"},
        {"title": "Reporte de ventas diarias",
         "description": "Enviar reporte automático diario por email",
         "priority": "Media", "status": "Finalizada",
         "type": "Mejora", "channel": "Correo", "level": 2,
         "requester_id": username_to_doc["comercial1"]["id"], "requester_name": "Pedro Sánchez", "department": "Comerciales",
         "assigned_to": username_to_doc["soporte2"]["id"], "assigned_to_name": "María González",
         "completion_date": datetime.now(timezone.utc) - timedelta(days=5)},
    ]
    for rd in sample_reqs:
        req = Request(**rd)
        req.state_history.append(StateEvent(
            from_status=None, to_status=req.status,
            by_user_id=admin_id, by_user_name="Administrador Sistema"
        ))
        await db.requests.insert_one(req.dict())

# ============================
#          Endpoints
# ============================
@api_router.post("/auth/login", response_model=Token)
@limiter.limit(LOGIN_RATE_LIMIT)
async def login(
    request: FastAPIRequest,
    user_login: Optional[UserLogin] = Body(default=None),
    username: Optional[str] = Form(default=None),
    password: Optional[str] = Form(default=None),
):
    if user_login is None:
        if username and password:
            user_login = UserLogin(username=username, password=password)
        else:
            try:
                raw = await request.json()
                if isinstance(raw, dict) and "username" in raw and "password" in raw:
                    user_login = UserLogin(username=raw["username"], password=raw["password"])
            except Exception:
                pass

    if user_login is None:
        raise HTTPException(status_code=422, detail="username/password required")

    ip = get_remote_address(request)
    if await is_locked(user_login.username, ip, LOGIN_LOCK_THRESHOLD, LOGIN_LOCK_WINDOW_MIN):
        raise HTTPException(status_code=429, detail="Demasiados intentos fallidos. Inténtalo más tarde.")

    user_doc = await db.users.find_one({"username": user_login.username})
    if not user_doc or not verify_password(user_login.password, user_doc["password_hash"]):
        await record_failed_login(user_login.username, ip, LOGIN_LOCK_WINDOW_MIN)
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": user_doc["username"]})
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.get("/auth/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

# ---- Users ----
@api_router.post("/users", response_model=User)
async def create_user(user: UserCreate, current_user: User = Depends(require_role(["admin"]))):
    existing_user = await db.users.find_one({"username": user.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    user_dict = user.dict()
    password_hash = get_password_hash(user_dict.pop("password"))
    new_user = User(**user_dict)
    user_doc = new_user.dict()
    user_doc["password_hash"] = password_hash
    await db.users.insert_one(user_doc)
    return new_user

@api_router.get("/users", response_model=List[User])
async def get_users(current_user: User = Depends(require_role(["admin"]))):
    users = await db.users.find().to_list(1000)
    return [User(**user) for user in users]

# ---- Departments ----
@api_router.get("/departments", response_model=List[Department])
async def get_departments(current_user: User = Depends(get_current_user)):
    departments = await db.departments.find().to_list(1000)
    return [Department(**dept) for dept in departments]

# ---- Requests ----
@api_router.post("/requests", response_model=Request)
async def create_request(payload: RequestCreate, current_user: User = Depends(get_current_user)):
    data = payload.dict(exclude_unset=True)
    if not data.get("requested_at"):
        data["requested_at"] = datetime.now(timezone.utc)

    # base
    new_request = Request(
        title=data["title"],
        description=data["description"],
        priority=data["priority"],
        type=data["type"],
        channel=data.get("channel", "Sistema"),
        requester_id=current_user.id,
        requester_name=current_user.full_name,
        department=current_user.department,
        requested_at=data["requested_at"],
    )

    # permitir clasificar/asignar en el alta SOLO a admin (mismo permiso que usas para /assign y /classify)
    if current_user.role == "admin":
        if "level" in data and data["level"] is not None:
            new_request.level = data["level"]
        if "estimated_hours" in data:
            new_request.estimated_hours = data["estimated_hours"]
        if "estimated_due" in data:
            new_request.estimated_due = data["estimated_due"]
        if data.get("assigned_to"):
            u = await db.users.find_one({"id": data["assigned_to"]})
            if not u:
                raise HTTPException(status_code=400, detail="Usuario asignado no existe")
            new_request.assigned_to = u["id"]
            new_request.assigned_to_name = u["full_name"]

    new_request.state_history.append(StateEvent(
        from_status=None, to_status=new_request.status,
        by_user_id=current_user.id, by_user_name=current_user.full_name
    ))

    await db.requests.insert_one(new_request.dict())
    return new_request

    data = payload.dict(exclude_unset=True)
    if not data.get("requested_at"):
        data["requested_at"] = datetime.now(timezone.utc)
    new_request = Request(
        **data,
        requester_id=current_user.id,
        requester_name=current_user.full_name,
        department=current_user.department,
    )
    new_request.state_history.append(StateEvent(
        from_status=None, to_status=new_request.status,
        by_user_id=current_user.id, by_user_name=current_user.full_name
    ))
    await db.requests.insert_one(new_request.dict())
    # Registrar evento normalizado
    await db.ticket_status_events.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": new_request.id,
        "estado": new_request.status,
        "changed_by": current_user.id,
        "changed_at": datetime.now(timezone.utc),
    })
    return new_request

@api_router.get("/requests", response_model=PaginatedRequests)
async def get_requests(
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=int(os.environ.get("MAX_PAGE_SIZE", "50"))),
    status: Optional[RequestStatus] = Query(None),
    department: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Texto en título/descripción"),
    sort: Optional[str] = Query("-created_at"),
    request_type: Optional[RequestType] = Query(None, alias="type"),
    level: Optional[int] = Query(None, ge=1, le=3),
    assigned_to: Optional[str] = Query(None),
    channel: Optional[RequestChannel] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    filt: Dict[str, Any] = {}
    if current_user.role == "employee":
        filt["requester_id"] = current_user.id
    if status: filt["status"] = status
    if department: filt["department"] = department
    if request_type: filt["type"] = request_type
    if level: filt["level"] = level
    if assigned_to: filt["assigned_to"] = assigned_to
    if channel: filt["channel"] = channel
    if date_from or date_to:
        dr: Dict[str, Any] = {}
        if date_from: dr["$gte"] = date_from
        if date_to: dr["$lte"] = date_to
        filt["requested_at"] = dr
    if q: filt["$text"] = {"$search": q}

    sort_field = "created_at"; sort_dir = -1
    if sort:
        if sort.startswith("-"):
            sort_field = sort[1:]; sort_dir = -1
        else:
            sort_field = sort; sort_dir = 1
    if sort_field not in {"created_at", "status", "department", "requested_at", "priority", "level"}:
        sort_field = "created_at"

    total = await db.requests.count_documents(filt)
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = min(page, total_pages)

    cursor = (
        db.requests.find(filt)
        .sort(sort_field, sort_dir)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    docs = await cursor.to_list(length=page_size)
    items = [_to_request(d) for d in docs]

    return PaginatedRequests(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )

@api_router.post("/requests/{request_id}/classify", response_model=Request)
async def classify_request(
    request_id: str,
    payload: ClassifyPayload,
    current_user: User = Depends(require_role(["admin"]))
):
    doc = await db.requests.find_one({"id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    update = {
        "level": payload.level,
        "priority": payload.priority,
        "updated_at": datetime.now(timezone.utc),
    }
    await db.requests.update_one({"id": request_id}, {"$set": update})
    doc = await db.requests.find_one({"id": request_id})
    return _to_request(doc)

@api_router.post("/requests/{request_id}/assign", response_model=Request)
async def assign_request(
    request_id: str,
    payload: AssignPayload,
    current_user: User = Depends(require_role(["admin"]))
):
    doc = await db.requests.find_one({"id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    target_user_id = payload.assigned_to or current_user.id
    target_user = await db.users.find_one({"id": target_user_id})
    if not target_user:
        raise HTTPException(status_code=400, detail="Usuario destino no encontrado")

    update = {
        "assigned_to": target_user["id"],
        "assigned_to_name": target_user["full_name"],
        "estimated_hours": payload.estimated_hours,
        "estimated_due": payload.estimated_due,
        "updated_at": datetime.now(timezone.utc),
        # NUEVO: registrar quién asigna
        "assigned_by_id": current_user.id,
        "assigned_by_name": current_user.full_name,
    }
    await db.requests.update_one({"id": request_id}, {"$set": update})
    doc = await db.requests.find_one({"id": request_id})
    return _to_request(doc)

@api_router.post("/requests/{request_id}/unassign", response_model=Request)
async def unassign_request( 
    request_id: str,
    payload: AssignPayload,
    current_user: User = Depends(require_role(["admin"]))
):
    doc = await db.requests.find_one({"id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    target_user_id = payload.assigned_to or current_user.id
    target_user = await db.users.find_one({"id": target_user_id})
    if not target_user:
        raise HTTPException(status_code=400, detail="Usuario destino no encontrado")

    update = {
        "assigned_to": target_user["id"],
        "assigned_to_name": target_user["full_name"],
        "estimated_hours": payload.estimated_hours,
        "estimated_due": payload.estimated_due,
        "updated_at": datetime.now(timezone.utc),
    }
    await db.requests.update_one({"id": request_id}, {"$set": update})
    doc = await db.requests.find_one({"id": request_id})
    return _to_request(doc)

@api_router.post("/requests/{request_id}/transition", response_model=Request)
async def transition_request(
    request_id: str,
    payload: TransitionPayload,
    current_user: User = Depends(require_role(["support", "admin"]))
):
    doc = await db.requests.find_one({"id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    current = _to_request(doc)
    ensure_transition(current.status, payload.to_status)

    now = datetime.now(timezone.utc)

    # === Reglas de negocio ===
    # 1) Rechazar -> requiere comentario
    if payload.to_status == "Rechazada":
        if not payload.comment or not payload.comment.strip():
            raise HTTPException(status_code=422, detail="Debe indicar el motivo del rechazo.")
    # 2) Enviar a revisión -> requiere evidencia y permisos
    if payload.to_status == "En revisión":
        allowed = {doc.get("assigned_to"), doc.get("assigned_by_id")}
        if current_user.id not in allowed and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Solo el asignado o quien asignó pueden enviar a revisión.")
        if not payload.evidence_link or not payload.evidence_link.strip():
            raise HTTPException(status_code=422, detail="Debe adjuntar evidencia (enlace a documento/archivo).")

    set_ops: Dict[str, Any] = {
        "status": payload.to_status,
        "updated_at": now,
    }
    if payload.to_status in {"Finalizada", "Rechazada"}:
        set_ops["completion_date"] = now
    if payload.to_status == "Rechazada":
        set_ops["rejection_reason"] = payload.comment.strip()
    if payload.to_status == "En revisión":
        set_ops["review_evidence"] = {
            "type": "link",
            "url": payload.evidence_link.strip(),
            "by": current_user.id,
            "at": now,
        }

    history_event = StateEvent(
        from_status=current.status,
        to_status=payload.to_status,
        by_user_id=current_user.id,
        by_user_name=current_user.full_name,
    ).dict()

    # retrabajo
    ops: Dict[str, Any] = {"$set": set_ops, "$push": {"state_history": history_event}}
    if current.status == "Finalizada" and payload.to_status in OPEN_STATES:
        ops.setdefault("$inc", {})["reabierto_count"] = 1

    await db.requests.update_one({"id": request_id}, ops)

    await db.ticket_status_events.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": request_id,
        "estado": payload.to_status,
        "changed_by": current_user.id,
        "changed_at": now,
    })

    doc = await db.requests.find_one({"id": request_id})
    return _to_request(doc)

    request_id: str
    payload: TransitionPayload
    current_user: User = Depends(require_role(["support", "admin"]))
    doc = await db.requests.find_one({"id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    current = _to_request(doc)
    ensure_transition(current.status, payload.to_status)

    now = datetime.now(timezone.utc)
    set_ops: Dict[str, Any] = {
        "status": payload.to_status,
        "updated_at": now,
    }
    if payload.to_status in {"Finalizada", "Rechazada"}:
        set_ops["completion_date"] = now

    history_event = StateEvent(
        from_status=current.status,
        to_status=payload.to_status,
        by_user_id=current_user.id,
        by_user_name=current_user.full_name,
    ).dict()

    # retrabajo: si vuelve a un estado abierto desde Finalizada
    inc_ops = {}
    if current.status == "Finalizada" and payload.to_status in OPEN_STATES:
        inc_ops = {"$inc": {"reabierto_count": 1}}

    ops = {"$set": set_ops, "$push": {"state_history": history_event}}
    if inc_ops: ops.update(inc_ops)

    await db.requests.update_one({"id": request_id}, ops)

    # evento normalizado
    await db.ticket_status_events.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": request_id,
        "estado": payload.to_status,
        "changed_by": current_user.id,
        "changed_at": now,
    })

    doc = await db.requests.find_one({"id": request_id})
    return _to_request(doc)

@api_router.post("/requests/{request_id}/feedback", response_model=Request)
async def submit_feedback(
    request_id: str,
    payload: FeedbackPayload,
    current_user: User = Depends(require_role(["employee", "admin", "support"]))
):
    doc = await db.requests.find_one({"id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    req = _to_request(doc)

    if current_user.role != "admin" and req.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el solicitante puede enviar feedback")
    if req.status != "Finalizada":
        raise HTTPException(status_code=400, detail="La solicitud no está finalizada")
    if req.feedback is not None:
        raise HTTPException(status_code=400, detail="El feedback ya fue registrado")

    fb = Feedback(
        rating=payload.rating,
        comment=payload.comment,
        by_user_id=current_user.id,
        by_user_name=current_user.full_name
    ).dict()

    await db.requests.update_one({"id": request_id}, {"$set": {"feedback": fb}})
    doc = await db.requests.find_one({"id": request_id})
    return _to_request(doc)

# ---- Update genérico con trazabilidad (compat) ----
@api_router.put("/requests/{request_id}", response_model=Request)
async def update_request_generic(
    request_id: str,
    request_update: RequestUpdate,
    current_user: User = Depends(require_role(["support", "admin"]))
):
    doc = await db.requests.find_one({"id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    current = _to_request(doc)
    update_data = request_update.dict(exclude_unset=True)
    now = datetime.now(timezone.utc)
    update_data["updated_at"] = now

    ops: Dict[str, Any] = {"$set": update_data}
    if "status" in update_data and update_data["status"] and update_data["status"] != current.status:
        ensure_transition(current.status, update_data["status"])
        if update_data["status"] in {"Finalizada", "Rechazada"}:
            ops["$set"]["completion_date"] = now
        # push history
        ops["$push"] = {"state_history": StateEvent(
            from_status=current.status,
            to_status=update_data["status"],
            by_user_id=current_user.id,
            by_user_name=current_user.full_name
        ).dict()}
        # retrabajo
        if current.status == "Finalizada" and update_data["status"] in OPEN_STATES:
            ops.setdefault("$inc", {})["reabierto_count"] = 1
        # evento normalizado
        await db.ticket_status_events.insert_one({
            "id": str(uuid.uuid4()),
            "ticket_id": request_id,
            "estado": update_data["status"],
            "changed_by": current_user.id,
            "changed_at": now,
        })

    if "assigned_to" in update_data and update_data["assigned_to"]:
        assigned_user = await db.users.find_one({"id": update_data["assigned_to"]})
        if assigned_user:
            ops["$set"]["assigned_to_name"] = assigned_user["full_name"]

    await db.requests.update_one({"id": request_id}, ops)
    doc = await db.requests.find_one({"id": request_id})
    return _to_request(doc)

# ---- Worklogs ----
@api_router.post("/requests/{request_id}/worklogs")
async def add_worklog(
    request_id: str,
    payload: WorklogCreate,
    current_user: User = Depends(require_role(["support", "admin"]))
):
    # valida existencia
    if not await db.requests.find_one({"id": request_id}):
        raise HTTPException(status_code=404, detail="Request not found")

    await db.worklogs.insert_one({
        "id": str(uuid.uuid4()),
        "ticket_id": request_id,
        "user_id": current_user.id,
        "fecha": date.today(),
        "horas": float(payload.horas),
        "nota": payload.nota or "",
        "created_at": datetime.now(timezone.utc),
    })
    return {"ok": True}
from fastapi import status as http_status

# ---- Papelera: eliminar (mover a trash) ----
@api_router.delete("/requests/{request_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_request(
    request_id: str,
    current_user: User = Depends(require_role(["admin"]))
):
    doc = await db.requests.find_one({"id": request_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    now = datetime.now(timezone.utc)
    trash_doc = {
        "id": doc["id"],
        "request_doc": doc,
        "deleted_at": now,
        "deleted_by_id": current_user.id,
        "deleted_by_name": current_user.full_name,
        "expireAt": now + timedelta(days=TRASH_TTL_DAYS),
    }

    # mover: insertar en trash y borrar del main
    await db.requests_trash.insert_one(trash_doc)
    await db.requests.delete_one({"id": request_id})
    return

class TrashItem(BaseModel):
    id: str
    title: str
    department: str
    requester_name: str
    deleted_at: datetime
    deleted_by_name: str
    expires_at: datetime

class PaginatedTrash(BaseModel):
    items: List[TrashItem]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool

@api_router.get("/requests/trash", response_model=PaginatedTrash)
async def list_trash(
    current_user: User = Depends(require_role(["admin"])),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=int(os.environ.get("MAX_PAGE_SIZE", "50"))),
    q: Optional[str] = Query(None),
):
    filt: Dict[str, Any] = {}
    if q:
        filt["$text"] = {"$search": q}

    total = await db.requests_trash.count_documents(filt)
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = min(page, total_pages)

    cursor = (
        db.requests_trash.find(filt)
        .sort("deleted_at", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    docs = await cursor.to_list(length=page_size)

    def _map(d):
        r = d.get("request_doc", {})
        return TrashItem(
            id=d["id"],
            title=r.get("title", "—"),
            department=r.get("department", "—"),
            requester_name=r.get("requester_name", "—"),
            deleted_at=d.get("deleted_at"),
            deleted_by_name=d.get("deleted_by_name", "—"),
            expires_at=d.get("expireAt"),
        )

    items = [_map(d) for d in docs]
    return PaginatedTrash(
        items=items,
        page=page, page_size=page_size,
        total=total, total_pages=total_pages,
        has_prev=page > 1, has_next=page < total_pages
    )

# ---- Restaurar desde papelera ----
@api_router.post("/requests/{request_id}/restore", response_model=Request)
async def restore_request(
    request_id: str,
    current_user: User = Depends(require_role(["admin"]))
):
    tr = await db.requests_trash.find_one({"id": request_id})
    if not tr:
        raise HTTPException(status_code=404, detail="No está en papelera")

    # evitar colisión si alguien creó otra con mismo id (raro, pero defensivo)
    exists = await db.requests.find_one({"id": request_id})
    if exists:
        raise HTTPException(status_code=409, detail="Ya existe una solicitud con ese id")

    doc = tr["request_doc"]
    # opcional: refrescar updated_at
    doc["updated_at"] = datetime.now(timezone.utc)

    await db.requests.insert_one(doc)
    await db.requests_trash.delete_one({"id": request_id})
    return _to_request(doc)

# ---- Eliminar definitivamente de papelera (opcional) ----
@api_router.delete("/requests/trash/{request_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def purge_trash_request(
    request_id: str,
    current_user: User = Depends(require_role(["admin"]))
):
    res = await db.requests_trash.delete_one({"id": request_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="No está en papelera")
    return

@api_router.delete("/users/{user_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_role(["admin"]))
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")

    user_doc = await db.users.find_one({"id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # proteger último admin
    if user_doc.get("role") == "admin":
        admins = await db.users.count_documents({"role": "admin"})
        if admins <= 1:
            raise HTTPException(status_code=400, detail="No puedes eliminar al último administrador")

    # evitar dejar tickets abiertos huérfanos
    open_assigned = await db.requests.count_documents({
        "assigned_to": user_id,
        "status": {"$in": list(OPEN_STATES)}
    })
    if open_assigned > 0:
        raise HTTPException(status_code=400, detail="El usuario tiene solicitudes abiertas asignadas")

    # si llega aquí, eliminar
    await db.users.delete_one({"id": user_id})
    return


# ---- Reportes / Analytics helpers ----
def _range_for_period(period: Literal["daily", "weekly", "monthly"], ref: Optional[datetime] = None):
    now = ref or datetime.now(timezone.utc)
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start = (now - timedelta(days=(now.isoweekday() - 1))).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now

def _resolve_range(period: Optional[str], date_from: Optional[datetime], date_to: Optional[datetime]):
    if date_from and date_to:
        return date_from, date_to
    if period in ("day","daily"):
        return _range_for_period("daily")
    if period in ("week","weekly"):
        return _range_for_period("weekly")
    return _range_for_period("monthly")

async def _summary_payload(period: Literal["daily", "weekly", "monthly"]):
    start, end = _range_for_period(period)

    # --- KPIs del periodo ---
    new_count = await db.requests.count_documents({"requested_at": {"$gte": start, "$lte": end}})
    finished_q = {"status": "Finalizada", "completion_date": {"$gte": start, "$lte": end}}
    finished_count = await db.requests.count_documents(finished_q)
    pending_now = await db.requests.count_documents({"status": {"$in": OPEN_STATES}})

    finals = await db.requests.find(finished_q).to_list(2000)
    avg_hours = 0.0
    if finals:
        total_hours = sum([(r["completion_date"] - r["created_at"]).total_seconds() / 3600 for r in finals])
        avg_hours = round(total_hours / len(finals), 1)

    # --- Totales globales ---
    total_requests = await db.requests.count_documents({})
    assigned_total = await db.requests.count_documents({"assigned_to": {"$ne": None}})
    unassigned_total = await db.requests.count_documents({"$or": [{"assigned_to": None}, {"assigned_to": {"$exists": False}}]})
    last24 = end - timedelta(hours=24)
    new_last_24h = await db.requests.count_documents({"requested_at": {"$gte": last24, "$lte": end}})

    # --- Productividad por técnico ---
    assigned = await db.requests.aggregate([
        {"$match": {"assigned_to": {"$ne": None}}},
        {"$group": {"_id": "$assigned_to", "assigned_total": {"$sum": 1}}}
    ]).to_list(1000)

    pending = await db.requests.aggregate([
        {"$match": {"assigned_to": {"$ne": None}, "status": {"$in": OPEN_STATES}}},
        {"$group": {"_id": "$assigned_to", "pending_now": {"$sum": 1}}}
    ]).to_list(1000)

    attended = await db.requests.aggregate([
        {"$match": {"assigned_to": {"$ne": None}, "status": "Finalizada", "completion_date": {"$gte": start, "$lte": end}}},
        {"$group": {"_id": "$assigned_to", "attended_period": {"$sum": 1}}}
    ]).to_list(1000)

    by_id: Dict[str, Dict[str, Any]] = {}
    for coll, key in [(assigned,"assigned_total"), (pending,"pending_now"), (attended,"attended_period")]:
        for r in coll:
            k = r["_id"]
            if not k: 
                continue
            by_id.setdefault(k, {"user_id": k, "assigned_total": 0, "pending_now": 0, "attended_period": 0})
            by_id[k][key] = r.get(key, 0)

    ids = list(by_id.keys())
    users = await db.users.find({"id": {"$in": ids}}).to_list(1000)
    name_map = {u["id"]: u.get("full_name") for u in users}
    productivity = []
    for k, row in by_id.items():
        row["name"] = name_map.get(k, k)
        productivity.append(row)
    productivity.sort(key=lambda r: (-r["attended_period"], r["name"]))

    return {
        "period": period,
        "from": start,
        "to": end,
        "new": new_count,
        "finished": finished_count,
        "pending_now": pending_now,
        "avg_cycle_hours": avg_hours,
        "totals": {
            "total_requests": total_requests,
            "assigned_total": assigned_total,
            "unassigned_total": unassigned_total,
            "new_last_24h": new_last_24h,
        },
        "productivity_by_tech": productivity,
    }

# ---- Métricas (nuevas) ----
@api_router.get("/metrics/kpis")
async def metrics_kpis(
    period: Optional[str] = Query("day"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    current_user: User = Depends(require_role(["support", "admin"]))
):
    start, end = _resolve_range(period, date_from, date_to)

    recibidos = await db.requests.count_documents({"requested_at": {"$gte": start, "$lte": end}})
    resueltos = await db.requests.count_documents({"completion_date": {"$gte": start, "$lte": end}})
    backlog = await db.requests.count_documents({"status": {"$in": OPEN_STATES}})

    cerrados = await db.requests.aggregate([
        {"$match": {"completion_date": {"$gte": start, "$lte": end}}},
        {"$project": {"ttr_h": {"$divide": [{"$subtract": ["$completion_date", "$created_at"]}, 1000 * 60 * 60]}}},
        {"$group": {"_id": None, "avg_ttr": {"$avg": "$ttr_h"}}}
    ]).to_list(1)
    ttr_promedio = round(cerrados[0]["avg_ttr"], 1) if cerrados else 0.0

    return {
        "from": start, "to": end,
        "recibidos": recibidos,
        "resueltos": resueltos,
        "backlog": backlog,
        "ttr_promedio": ttr_promedio,
        "activos": backlog,
    }

@api_router.get("/metrics/distribution")
async def metrics_distribution(
    group_by: Literal["type", "level", "department"] = Query("type"),
    period: Optional[str] = Query("month"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    current_user: User = Depends(require_role(["support", "admin"]))
):
    start, end = _resolve_range(period, date_from, date_to)
    field = {"type": "$type", "level": "$level", "department": "$department"}[group_by]
    rows = await db.requests.aggregate([
        {"$match": {"requested_at": {"$gte": start, "$lte": end}}},
        {"$group": {"_id": field, "total": {"$sum": 1}}},
        {"$sort": {"total": -1}}
    ]).to_list(1000)
    return {"from": start, "to": end, "group_by": group_by, "rows": rows}

@api_router.get("/metrics/technicians")
async def metrics_technicians(
    period: Optional[str] = Query("week"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    current_user: User = Depends(require_role(["support", "admin"]))
):
    start, end = _resolve_range(period, date_from, date_to)

    resueltos = await db.requests.aggregate([
        {"$match": {"assigned_to": {"$ne": None}, "completion_date": {"$gte": start, "$lte": end}}},
        {"$group": {"_id": "$assigned_to", "resueltos": {"$sum": 1}}},
    ]).to_list(1000)

    pendientes = await db.requests.aggregate([
        {"$match": {"assigned_to": {"$ne": None}, "status": {"$in": OPEN_STATES}}},
        {"$group": {"_id": "$assigned_to", "pendientes": {"$sum": 1}}},
    ]).to_list(1000)

    asignadas = await db.requests.aggregate([
        {"$match": {"assigned_to": {"$ne": None}}},
        {"$group": {"_id": "$assigned_to", "asignadas": {"$sum": 1}}},
    ]).to_list(1000)

    horas = await db.worklogs.aggregate([
        {"$match": {"fecha": {"$gte": start.date(), "$lte": end.date()}}},
        {"$group": {"_id": "$user_id", "horas": {"$sum": "$horas"}}},
    ]).to_list(1000)

    merge: Dict[str, Dict[str, Any]] = {}
    for coll, key in [(resueltos,"resueltos"), (pendientes,"pendientes"), (asignadas,"asignadas"), (horas,"horas")]:
        for r in coll:
            uid = r["_id"]
            if not uid: 
                continue
            merge.setdefault(uid, {"user_id": uid, "resueltos": 0, "pendientes": 0, "asignadas": 0, "horas": 0.0})
            merge[uid][key] = r.get(key, 0)

    users = await db.users.find({"id": {"$in": list(merge.keys())}}).to_list(1000)
    name_map = {u["id"]: u["full_name"] for u in users}
    rows = []
    for uid, row in merge.items():
        row["name"] = name_map.get(uid, uid)
        rows.append(row)
    rows.sort(key=lambda x: (-x["resueltos"], -x["horas"], x["name"]))

    return {"from": start, "to": end, "rows": rows}

@api_router.get("/metrics/rework")
async def metrics_rework(
    period: Optional[str] = Query("month"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    current_user: User = Depends(require_role(["support", "admin"]))
):
    start, end = _resolve_range(period, date_from, date_to)
    base = await db.requests.aggregate([
        {"$match": {"requested_at": {"$gte": start, "$lte": end}}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "con_retrabajo": {"$sum": {"$cond": [{"$gt": ["$reabierto_count", 0]}, 1, 0]}},
        }},
        {"$project": {"_id": 0, "total": 1, "con_retrabajo": 1,
                      "pct": {"$cond": [{"$gt": ["$total", 0]},
                                        {"$multiply": [{"$divide": ["$con_retrabajo", "$total"]}, 100]},
                                        0]}}}
    ]).to_list(1)
    return base[0] if base else {"total": 0, "con_retrabajo": 0, "pct": 0}

@api_router.get("/metrics/time-by-state")
async def metrics_time_by_state(
    period: Optional[str] = Query("week"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    current_user: User = Depends(require_role(["support", "admin"]))
):
    start, end = _resolve_range(period, date_from, date_to)

    # Eventos hasta 'end'
    ticket_ids = await db.ticket_status_events.distinct("ticket_id", {"changed_at": {"$lte": end}})
    events = await db.ticket_status_events.find({"ticket_id": {"$in": ticket_ids}})\
        .sort([("ticket_id", 1), ("changed_at", 1)]).to_list(200000)

    state_time = defaultdict(float)
    last: Dict[str, tuple[str, datetime]] = {}
    for ev in events:
        tid = ev["ticket_id"]
        st = ev["estado"]
        t = ev["changed_at"]
        if tid in last:
            prev_state, prev_t = last[tid]
            delta_h = (t - prev_t).total_seconds() / 3600
            if delta_h > 0:
                state_time[prev_state] += delta_h
        last[tid] = (st, t)

    # último tramo hasta end
    for tid, (st, last_t) in last.items():
        delta_h = (end - last_t).total_seconds() / 3600
        if delta_h > 0:
            state_time[st] += delta_h

    totals = {k: round(v, 1) for k, v in state_time.items()}
    return {"from": start, "to": end, "hours_by_state": totals}

@api_router.get("/metrics/backlog-trend")
async def backlog_trend(
    days: int = Query(30, ge=1, le=90),
    current_user: User = Depends(require_role(["support", "admin"]))
):
    # Aproximación robusta: backlog acumulado = nuevos acumulados - cerrados acumulados
    tznow = datetime.now(timezone.utc)
    end_day = tznow.replace(hour=0, minute=0, second=0, microsecond=0)
    start_day = end_day - timedelta(days=days - 1)

    rows = []
    acc_new = 0
    acc_closed = 0
    for i in range(days):
        d0 = start_day + timedelta(days=i)
        d1 = d0 + timedelta(days=1)

        new_d = await db.requests.count_documents({"requested_at": {"$gte": d0, "$lt": d1}})
        closed_d = await db.requests.count_documents({"completion_date": {"$gte": d0, "$lt": d1}})

        acc_new += new_d
        acc_closed += closed_d
        backlog = max(acc_new - acc_closed, 0)

        rows.append({"date": d0, "new": new_d, "closed": closed_d, "backlog": backlog})

    return {"from": start_day, "to": end_day, "rows": rows}

# ---- Reportes resumidos (compat con tu frontend actual) ----
@api_router.get("/reports/summary")
async def reports_summary(
    period: Literal["daily", "weekly", "monthly"] = Query("daily"),
    current_user: User = Depends(require_role(["support", "admin"]))
):
    return await _summary_payload(period)

@api_router.get("/analytics/dashboard")
async def analytics_dashboard(
    period: Literal["day", "week", "month"] = Query("month"),
    current_user: User = Depends(require_role(["support", "admin"]))
):
    map_period = {"day": "daily", "week": "weekly", "month": "monthly"}[period]
    return await _summary_payload(map_period)

# ============================
#        App lifecycle
# ============================
@app.on_event("startup")
async def startup_event():
    await ensure_security_indexes()
    await ensure_core_indexes()
    await ensure_trash_indexes()
    await migrate_requests_schema()  # corrige datos existentes
    await init_data()

app.include_router(api_router)

# ---- CORS (robusto para dev) ----
allow_origins_list = list(filter(None, [
    *(o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()),
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:5173", "http://127.0.0.1:5173",
]))
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=allow_origins_list or ["http://localhost:3000"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["*"],
    max_age=600,
)

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
