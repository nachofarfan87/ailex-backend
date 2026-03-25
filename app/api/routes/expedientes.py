"""
AILEX -- Endpoints de gestion de expedientes.

GET    /api/expedientes              -- listar expedientes del usuario
POST   /api/expedientes              -- crear expediente
GET    /api/expedientes/{id}         -- obtener expediente con detalle
PATCH  /api/expedientes/{id}         -- actualizar campos
DELETE /api/expedientes/{id}         -- archivar (soft-delete)
GET    /api/expedientes/{id}/consultas -- listar consultas del expediente
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import Consulta, Expediente, User
from app.services import expediente_service
from app.services.document_service import DocumentService

_document_service = DocumentService()

router = APIRouter(prefix="/api/expedientes", tags=["Expedientes"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ExpedienteCreate(BaseModel):
    titulo:           str  = Field(..., min_length=1, max_length=500)
    caratula:         str  = Field(default="", max_length=500)
    numero:           str  = Field(default="", max_length=100)
    materia:          str  = Field(default="", max_length=100)
    juzgado:          str  = Field(default="", max_length=200)
    jurisdiccion:     str  = Field(default="jujuy", max_length=100)
    descripcion:      str  = Field(default="")
    notas_estrategia: str  = Field(default="")
    tipo_caso:        str  = Field(default="", max_length=120)
    subtipo_caso:     str  = Field(default="", max_length=120)
    partes_json:      str  = Field(default="[]")
    hechos_relevantes: str = Field(default="")
    pretension_principal: str = Field(default="")
    estado_procesal:  str  = Field(default="", max_length=120)
    riesgos_clave:    str  = Field(default="")
    estrategia_base:  str  = Field(default="")
    proxima_accion_sugerida: str = Field(default="")


class ExpedienteUpdate(BaseModel):
    titulo:           Optional[str] = Field(default=None, max_length=500)
    caratula:         Optional[str] = Field(default=None, max_length=500)
    numero:           Optional[str] = Field(default=None, max_length=100)
    materia:          Optional[str] = Field(default=None, max_length=100)
    juzgado:          Optional[str] = Field(default=None, max_length=200)
    jurisdiccion:     Optional[str] = Field(default=None, max_length=100)
    descripcion:      Optional[str] = None
    notas_estrategia: Optional[str] = None
    tipo_caso:        Optional[str] = Field(default=None, max_length=120)
    subtipo_caso:     Optional[str] = Field(default=None, max_length=120)
    partes_json:      Optional[str] = None
    hechos_relevantes: Optional[str] = None
    pretension_principal: Optional[str] = None
    estado_procesal:  Optional[str] = Field(default=None, max_length=120)
    riesgos_clave:    Optional[str] = None
    estrategia_base:  Optional[str] = None
    proxima_accion_sugerida: Optional[str] = None
    estado:           Optional[str] = Field(
        default=None,
        pattern="^(activo|archivado|cerrado)$",
        description="activo | archivado | cerrado",
    )


class ExpedienteOut(BaseModel):
    id:               str
    user_id:          str
    titulo:           str
    caratula:         str
    numero:           str
    materia:          str
    juzgado:          str
    jurisdiccion:     str
    descripcion:      str
    notas_estrategia: str
    tipo_caso:        str
    subtipo_caso:     str
    partes_json:      str
    hechos_relevantes: str
    pretension_principal: str
    estado_procesal:  str
    riesgos_clave:    str
    estrategia_base:  str
    proxima_accion_sugerida: str
    estado:           str
    consulta_count:   int = 0
    created_at:       Optional[str] = None
    updated_at:       Optional[str] = None

    model_config = {"from_attributes": True}


class ConsultaSummaryOut(BaseModel):
    id:            str
    titulo:        str
    query:         str
    jurisdiction:  str
    forum:         str
    document_mode: str
    confidence:    Optional[float] = None
    notas:         str
    created_at:    Optional[str] = None

    model_config = {"from_attributes": True}


class ExpedienteListResponse(BaseModel):
    items: list[ExpedienteOut]
    total: int


class ConsultaListResponse(BaseModel):
    items: list[ConsultaSummaryOut]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exp_to_out(exp: Expediente) -> ExpedienteOut:
    return ExpedienteOut(
        id=exp.id,
        user_id=exp.user_id,
        titulo=exp.titulo,
        caratula=exp.caratula or "",
        numero=exp.numero or "",
        materia=exp.materia or "",
        juzgado=exp.juzgado or "",
        jurisdiccion=exp.jurisdiccion or "jujuy",
        descripcion=exp.descripcion or "",
        notas_estrategia=exp.notas_estrategia or "",
        tipo_caso=exp.tipo_caso or "",
        subtipo_caso=exp.subtipo_caso or "",
        partes_json=exp.partes_json or "[]",
        hechos_relevantes=exp.hechos_relevantes or "",
        pretension_principal=exp.pretension_principal or "",
        estado_procesal=exp.estado_procesal or "",
        riesgos_clave=exp.riesgos_clave or "",
        estrategia_base=exp.estrategia_base or "",
        proxima_accion_sugerida=exp.proxima_accion_sugerida or "",
        estado=exp.estado or "activo",
        consulta_count=exp.consulta_count(),
        created_at=exp.created_at.isoformat() if exp.created_at else None,
        updated_at=exp.updated_at.isoformat() if exp.updated_at else None,
    )


def _consulta_to_summary(c: Consulta) -> ConsultaSummaryOut:
    return ConsultaSummaryOut(
        id=c.id,
        titulo=c.titulo or "",
        query=c.query,
        jurisdiction=c.jurisdiction or "",
        forum=c.forum or "",
        document_mode=c.document_mode or "",
        confidence=c.confidence,
        notas=c.notas or "",
        created_at=c.created_at.isoformat() if c.created_at else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ExpedienteListResponse,
    summary="Listar expedientes del usuario",
)
def list_expedientes(
    estado:  Optional[str] = Query(default=None, description="Filtrar por estado: activo | archivado | cerrado"),
    skip:    int           = Query(default=0,  ge=0),
    limit:   int           = Query(default=50, ge=1, le=200),
    db:      Session       = Depends(get_db),
    user:    User          = Depends(get_current_user),
) -> ExpedienteListResponse:
    items = expediente_service.get_expedientes(db, user.id, estado=estado, skip=skip, limit=limit)
    return ExpedienteListResponse(items=[_exp_to_out(e) for e in items], total=len(items))


@router.post(
    "",
    response_model=ExpedienteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear expediente",
)
def create_expediente(
    payload: ExpedienteCreate,
    db:      Session = Depends(get_db),
    user:    User    = Depends(get_current_user),
) -> ExpedienteOut:
    exp = expediente_service.create_expediente(
        db=db,
        user_id=user.id,
        **payload.model_dump(),
    )
    return _exp_to_out(exp)


@router.get(
    "/{expediente_id}",
    response_model=ExpedienteOut,
    summary="Obtener expediente por ID",
)
def get_expediente(
    expediente_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
) -> ExpedienteOut:
    exp = expediente_service.get_expediente(db, expediente_id, user.id)
    return _exp_to_out(exp)


@router.patch(
    "/{expediente_id}",
    response_model=ExpedienteOut,
    summary="Actualizar expediente",
)
def update_expediente(
    expediente_id: str,
    payload: ExpedienteUpdate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
) -> ExpedienteOut:
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    exp = expediente_service.update_expediente(db, expediente_id, user.id, **fields)
    return _exp_to_out(exp)


@router.delete(
    "/{expediente_id}",
    status_code=status.HTTP_200_OK,
    summary="Archivar expediente (soft-delete)",
)
def archive_expediente(
    expediente_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
) -> dict:
    expediente_service.archive_expediente(db, expediente_id, user.id)
    return {"detail": "Expediente archivado correctamente.", "id": expediente_id}


@router.get(
    "/{expediente_id}/consultas",
    response_model=ConsultaListResponse,
    summary="Listar consultas de un expediente",
)
def list_consultas_by_expediente(
    expediente_id: str,
    skip:  int     = Query(default=0,  ge=0),
    limit: int     = Query(default=50, ge=1, le=200),
    db:    Session = Depends(get_db),
    user:  User    = Depends(get_current_user),
) -> ConsultaListResponse:
    consultas = expediente_service.get_consultas_by_expediente(
        db, expediente_id, user.id, skip=skip, limit=limit
    )
    return ConsultaListResponse(
        items=[_consulta_to_summary(c) for c in consultas],
        total=len(consultas),
    )


@router.get(
    "/{expediente_id}/documents",
    summary="Listar documentos vinculados a un expediente",
)
def list_documents_by_expediente(
    expediente_id: str,
    document_scope: Optional[str] = Query(default=None, description="Filtrar por scope: corpus | case"),
    page:  int     = Query(default=1,  ge=1),
    per_page: int  = Query(default=20, ge=1, le=100),
    db:    Session = Depends(get_db),
    user:  User    = Depends(get_current_user),
) -> dict:
    # Verify ownership
    expediente_service.get_expediente(db, expediente_id, user.id)

    result = _document_service.list_documents(
        db,
        user_id=user.id,
        expediente_id=expediente_id,
        document_scope=document_scope,
        page=page,
        per_page=per_page,
    )
    return {
        "expediente_id": expediente_id,
        "documents": [
            {
                "id": doc.get("id"),
                "title": doc.get("title"),
                "source_type": doc.get("source_type"),
                "source_hierarchy": doc.get("source_hierarchy"),
                "jurisdiction": doc.get("jurisdiction"),
                "legal_area": doc.get("legal_area"),
                "document_scope": doc.get("document_scope"),
                "status": doc.get("status"),
                "chunk_count": doc.get("chunk_count"),
                "created_at": doc.get("created_at"),
            }
            for doc in result["documents"]
        ],
        "total": result["total"],
        "page": result["page"],
        "per_page": result["per_page"],
    }
