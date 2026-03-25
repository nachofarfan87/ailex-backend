"""
AILEX — Esquemas base de la API.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class StatusResponse(BaseModel):
    """Respuesta genérica de estado."""
    status: str
    message: str


class PaginatedRequest(BaseModel):
    """Parámetros de paginación."""
    page: int = 1
    per_page: int = 20


class TimestampMixin(BaseModel):
    """Mixin con timestamps."""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
