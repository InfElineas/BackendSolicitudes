# app/api/routes/metrics.py
from fastapi import APIRouter, Query, Depends
from typing import Optional
from app.api.deps import get_current_user
from app.services.metrics_service import summary, summary_alias

router = APIRouter()

@router.get("/reports/summary")
async def reports_summary(
    period: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    extended: bool | int | str = Query(False, description="true|1 para KPIs extendidos"),
    _user=Depends(get_current_user),
):
    ext = str(extended).lower() in {"true","1","yes","y"}
    return await summary(period, extended=ext)

@router.get("/analytics/dashboard")
async def analytics_dashboard(
    period: str = Query("day", regex="^(day|week|month)$"),
    extended: bool | int | str = Query(False, description="true|1 para KPIs extendidos"),
    _user=Depends(get_current_user),
):
    ext = str(extended).lower() in {"true","1","yes","y"}
    return await summary_alias(period, extended=ext)
