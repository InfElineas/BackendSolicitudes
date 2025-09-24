# app/models/request.py
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Literal
import uuid
from app.models.common import RequestType, RequestChannel, RequestStatus

class StateEvent(BaseModel):
    from_status: Optional[RequestStatus] = None
    to_status: RequestStatus
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    by_user_id: str
    by_user_name: str

class Feedback(BaseModel):
    rating: Literal["up","down"]
    comment: Optional[str] = None
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    by_user_id: str
    by_user_name: str

class RequestInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    priority: Literal["Alta","Media","Baja"]
    type: RequestType = "Soporte"
    channel: RequestChannel = "Sistema"
    level: Optional[int] = None
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
    review_evidence: Optional[Dict[str, Any]] = None
    reabierto_count: int = 0

class RequestCreate(BaseModel):
    title: str
    description: str
    priority: Literal["Alta","Media","Baja"]
    type: RequestType
    channel: RequestChannel = "Sistema"
    requested_at: Optional[datetime] = None
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
    priority: Literal["Alta","Media","Baja"]

class AssignPayload(BaseModel):
    assigned_to: Optional[str] = None
    estimated_hours: Optional[float] = None
    estimated_due: Optional[datetime] = None

class TransitionPayload(BaseModel):
    to_status: RequestStatus
    comment: Optional[str] = None
    evidence_link: Optional[str] = None

class FeedbackPayload(BaseModel):
    rating: Literal["up","down"]
    comment: Optional[str] = None
