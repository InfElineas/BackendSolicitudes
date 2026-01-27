# app/api/routes/metrics.py

from fastapi import APIRouter, Query, Depends
from typing import Optional
from datetime import datetime
from app.api.deps import get_current_user
from app.services.metrics_service import (
    summary, summary_alias,
    productividad_por_tecnico,
    tasa_reapertura
)

router = APIRouter()

# ==========================
#     ENDPOINTS EXISTENTES
# ==========================

@router.get("/reports/summary")
async def reports_summary(
    period: str = Query("monthly", regex="^(daily|weekly|monthly|all)$"),
    extended: bool | int | str = Query(False, description="true|1 para KPIs extendidos"),
    _user=Depends(get_current_user),
):
    ext = str(extended).lower() in {"true", "1", "yes", "y"}
    return await summary(period, extended=ext)

@router.get("/analytics/dashboard")
async def analytics_dashboard(
    period: str = Query("day", regex="^(day|week|month)$"),
    extended: bool | int | str = Query(False, description="true|1 para KPIs extendidos"),
    _user=Depends(get_current_user),
):
    ext = str(extended).lower() in {"true", "1", "yes", "y"}
    return await summary_alias(period, extended=ext)

# ==========================
#     NUEVOS ENDPOINTS
# ==========================

@router.get("/reports/productividad")
async def kpi_productividad(
    start: datetime = Query(..., description="Fecha de inicio (ISO)"),
    end: datetime = Query(..., description="Fecha de fin (ISO)"),
    _user=Depends(get_current_user),
):
    return await productividad_por_tecnico(start_date=start, end_date=end)

@router.get("/reports/reaperturas")
async def kpi_reaperturas(
    start: datetime = Query(..., description="Fecha de inicio (ISO)"),
    end: datetime = Query(..., description="Fecha de fin (ISO)"),
    _user=Depends(get_current_user),
):
    return {"ratio": await tasa_reapertura(start_date=start, end_date=end)}
