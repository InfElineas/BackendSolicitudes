# app/api/routes/departments.py
from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from app.core.db import get_db

router = APIRouter()

@router.get("")
async def get_departments(current=Depends(get_current_user)):
    return await get_db().departments.find().to_list(1000)
