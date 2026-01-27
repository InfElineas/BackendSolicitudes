# app/models/user.py
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import uuid

class UserOut(BaseModel):
    id: str
    username: str
    full_name: str
    department: str
    position: str
    role: str
    created_at: datetime

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
