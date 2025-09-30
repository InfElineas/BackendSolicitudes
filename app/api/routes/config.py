# app/api/routes/config.py
from fastapi import APIRouter, Depends
from app.core.app_config_schema import AppConfig, RequestOptions, Department
from app.core.app_config_service import get_app_config, set_departments, set_request_options, upsert_app_config

router = APIRouter(prefix="/config", tags=["config"])

@router.get("", response_model=AppConfig)
async def read_config():
    return await get_app_config()

@router.put("", response_model=AppConfig)
async def replace_config(cfg: AppConfig):
    return await upsert_app_config(cfg)

@router.put("/departments", response_model=AppConfig)
async def replace_departments(departments: list[Department]):
    return await set_departments(departments)

@router.put("/request-options", response_model=AppConfig)
async def replace_request_options(options: RequestOptions):
    return await set_request_options(options)
