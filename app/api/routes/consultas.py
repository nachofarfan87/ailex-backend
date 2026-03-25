"""
AILEX -- Endpoints de consultas juridicas guardadas.

POST   /api/consultas               -- guardar consulta + resultado del pipeline
GET    /api/consultas               -- listar consultas del usuario
GET    /api/consultas/{id}          -- obtener consulta completa (con resultado)
PATCH  /api/consultas/{id}/notas    -- actualizar notas del usuario
PATCH  /api/consultas/{id}/expediente -- vincular/desvincular expediente
DELETE /api/consultas/{id}          -- eliminar consulta
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import Consulta, User
from app.services import consulta_service

router = APIRouter(prefix="/api/consultas", tags=["Consultas"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConsultaSaveRequest(BaseModel):
    """
    Payload para guardar o actualizar una consulta juridica.

    El campo `resultado` debe contener el dict devuelto por el endpoint
    POST /api/legal-query (PipelineResult serializado).

    Si se provee `consulta_id`, se actualiza la consulta existente (upsert).
    Si no, se crea nueva — pero con dedup guard por (conversation_id, query)
    para evitar duplicados cuando legal_query ya auto-guardo.
    """
    consulta_id:   Optional[str]        = Field(default=None, description="ID de consulta existente para upsert")
    query:         str                  = Field(..., min_length=1)
    resultado:     Dict[str, Any]       = Field(default_factory=dict)
    titulo:        str                  = Field(default="", max_length=300)
    jurisdiction:  str                  = Field(default="jujuy", max_length=100)
    forum:         str                  = Field(default="", max_length=100)
    document_mode: str                  = Field(default="", max_length=50)
    facts:         Dict[str, Any]       = Field(default_factory=dict)
    notas:         str                  = Field(default="")
    expediente_id: Optional[str]        = Field(default=None)
    conversation_id: Optional[str]      = Field(default=None)


class NotasUpdate(BaseModel):
    notas: str = Field(default="")


class ExpedienteAssign(BaseModel):
    """Pasar expediente_id=null para desvincular."""
    expediente_id: Optional[str] = None


class ConsultaSummaryOut(BaseModel):
    id:            str
    user_id:       Optional[str] = None
    expediente_id: Optional[str] = None
    conversation_id: Optional[str] = None
    titulo:        str
    query:         str
    jurisdiction:  str
    forum:         str
    document_mode: str
    confidence:    Optional[float] = None
    notas:         str
    created_at:    Optional[str]  = None

    model_config = {"from_attributes": True}


class ConsultaDetailOut(ConsultaSummaryOut):
    resultado:          Dict[str, Any] = Field(default_factory=dict)
    generated_document: str            = ""
    warnings:           list           = Field(default_factory=list)
    facts:              Dict[str, Any] = Field(default_factory=dict)


class ConsultaListResponse(BaseModel):
    items: list[ConsultaSummaryOut]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_summary(c: Consulta) -> ConsultaSummaryOut:
    return ConsultaSummaryOut(
        id=c.id,
        user_id=c.user_id,
        expediente_id=c.expediente_id,
        conversation_id=c.conversation_id,
        titulo=c.titulo or "",
        query=c.query,
        jurisdiction=c.jurisdiction or "",
        forum=c.forum or "",
        document_mode=c.document_mode or "",
        confidence=c.confidence,
        notas=c.notas or "",
        created_at=c.created_at.isoformat() if c.created_at else None,
    )


def _to_detail(c: Consulta) -> ConsultaDetailOut:
    import json

    def _safe_json(raw: str | None, fallback: Any) -> Any:
        try:
            return json.loads(raw or "")
        except (ValueError, TypeError):
            return fallback

    return ConsultaDetailOut(
        id=c.id,
        user_id=c.user_id,
        expediente_id=c.expediente_id,
        conversation_id=c.conversation_id,
        titulo=c.titulo or "",
        query=c.query,
        jurisdiction=c.jurisdiction or "",
        forum=c.forum or "",
        document_mode=c.document_mode or "",
        confidence=c.confidence,
        notas=c.notas or "",
        created_at=c.created_at.isoformat() if c.created_at else None,
        resultado=_safe_json(c.resultado_json, {}),
        generated_document=c.generated_document or "",
        warnings=_safe_json(c.warnings_json, []),
        facts=_safe_json(c.facts_json, {}),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ConsultaDetailOut,
    summary="Guardar o actualizar consulta juridica (upsert)",
)
def save_consulta(
    payload: ConsultaSaveRequest,
    response: Response,
    db:      Session = Depends(get_db),
    user:    User    = Depends(get_current_user),
) -> ConsultaDetailOut:
    """
    Persiste o actualiza una consulta y su resultado en la base de datos.

    Logica de upsert:
    - Si se provee consulta_id → actualiza la consulta existente.
    - Si ya existe una consulta con el mismo (conversation_id, query)
      → actualiza en lugar de crear duplicado.
    - En cualquier otro caso → crea nueva.

    Retorna 201 si se creo nueva, 200 si se actualizo existente.
    """
    c, created = consulta_service.upsert_consulta(
        db=db,
        user_id=user.id,
        query=payload.query,
        resultado=payload.resultado,
        titulo=payload.titulo,
        jurisdiction=payload.jurisdiction,
        forum=payload.forum,
        document_mode=payload.document_mode,
        facts=payload.facts,
        notas=payload.notas,
        expediente_id=payload.expediente_id,
        conversation_id=payload.conversation_id,
        consulta_id=payload.consulta_id,
    )
    if created:
        response.status_code = status.HTTP_201_CREATED
    else:
        response.status_code = status.HTTP_200_OK
    return _to_detail(c)


@router.get(
    "",
    response_model=ConsultaListResponse,
    summary="Listar consultas del usuario",
)
def list_consultas(
    expediente_id: Optional[str] = Query(default=None, description="Filtrar por expediente"),
    skip:          int            = Query(default=0,  ge=0),
    limit:         int            = Query(default=50, ge=1, le=200),
    db:            Session        = Depends(get_db),
    user:          User           = Depends(get_current_user),
) -> ConsultaListResponse:
    items = consulta_service.get_consultas(
        db, user.id, expediente_id=expediente_id, skip=skip, limit=limit
    )
    return ConsultaListResponse(items=[_to_summary(c) for c in items], total=len(items))


@router.get(
    "/{consulta_id}",
    response_model=ConsultaDetailOut,
    summary="Obtener consulta completa",
)
def get_consulta(
    consulta_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
) -> ConsultaDetailOut:
    """Devuelve la consulta con el resultado completo del pipeline."""
    c = consulta_service.get_consulta(db, consulta_id, user.id)
    return _to_detail(c)


@router.patch(
    "/{consulta_id}/notas",
    response_model=ConsultaSummaryOut,
    summary="Actualizar notas de la consulta",
)
def update_notas(
    consulta_id: str,
    payload:     NotasUpdate,
    db:          Session = Depends(get_db),
    user:        User    = Depends(get_current_user),
) -> ConsultaSummaryOut:
    c = consulta_service.update_notas(db, consulta_id, user.id, payload.notas)
    return _to_summary(c)


@router.patch(
    "/{consulta_id}/expediente",
    response_model=ConsultaSummaryOut,
    summary="Vincular o desvincular expediente",
)
def assign_expediente(
    consulta_id: str,
    payload:     ExpedienteAssign,
    db:          Session = Depends(get_db),
    user:        User    = Depends(get_current_user),
) -> ConsultaSummaryOut:
    """
    Asocia la consulta a un expediente.

    Enviar `expediente_id: null` para desvincularla de cualquier expediente.
    """
    c = consulta_service.assign_expediente(db, consulta_id, user.id, payload.expediente_id)
    return _to_summary(c)


@router.delete(
    "/{consulta_id}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar consulta",
)
def delete_consulta(
    consulta_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
) -> dict:
    """Elimina permanentemente la consulta y su resultado guardado."""
    consulta_service.delete_consulta(db, consulta_id, user.id)
    return {"detail": "Consulta eliminada.", "id": consulta_id}
