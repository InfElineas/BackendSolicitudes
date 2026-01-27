# app/utils/pagination.py
from pydantic import BaseModel
from typing import List, Any

class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool

def meta(total: int, page: int, page_size: int) -> PageMeta:
    total_pages = max((total + page_size - 1)//page_size, 1)
    page = min(page, total_pages)
    return PageMeta(
        page=page, page_size=page_size, total=total, total_pages=total_pages,
        has_prev=page > 1, has_next=page < total_pages
    )
