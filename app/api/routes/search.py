"""
AILEX — API Routes: Búsqueda Jurídica (RAG).

Búsqueda semántica e híbrida sobre la base documental.

Endpoints:
  POST /search/           — búsqueda híbrida (compatibilidad)
  POST /search/hybrid     — búsqueda híbrida con perfil de módulo
  POST /search/semantic   — búsqueda semántica pura (vectorial)
  POST /search/context    — contexto trazable para módulos de análisis
  GET  /search/profiles   — listar perfiles de búsqueda disponibles
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.modules.search.service import HybridSearchService, SearchFilters
from app.modules.search.profiles import list_profiles
from app.services.document_service import DocumentService

router = APIRouter(dependencies=[Depends(get_current_user)])

# Servicios
search_service = HybridSearchService()
_doc_service = DocumentService()


# ─── Schemas de request ──────────────────────────────────

class SearchRequest(BaseModel):
    """Solicitud de búsqueda jurídica."""
    query: str = Field(..., description="Consulta en lenguaje natural")
    jurisdiction: Optional[str] = Field(default="Jujuy", description="Jurisdicción")
    source_hierarchy: Optional[str] = Field(
        default=None, description="normativa | jurisprudencia | doctrina | interno"
    )
    source_type: Optional[str] = Field(
        default=None, description="codigo | ley | acordada | jurisprudencia | etc."
    )
    legal_area: Optional[str] = Field(
        default=None, description="civil | penal | laboral | contencioso | etc."
    )
    vigente: Optional[bool] = Field(
        default=None, description="True: solo vigentes, False: solo no vigentes, None: todos"
    )
    top_k: int = Field(default=10, ge=1, le=50)
    max_chars: Optional[int] = Field(default=8000, description="Caracteres max de contexto")


class HybridSearchRequest(SearchRequest):
    """Búsqueda híbrida con perfil de módulo."""
    search_profile: str = Field(
        default="general",
        description=(
            "Perfil de búsqueda: general | notifications | generation | audit | strategy"
        ),
    )


class ContextRequest(BaseModel):
    """Solicitud de contexto trazable para RAG."""
    query: str = Field(..., description="Consulta para obtener contexto")
    jurisdiction: Optional[str] = Field(default="Jujuy")
    source_hierarchy: Optional[str] = None
    legal_area: Optional[str] = None
    vigente: Optional[bool] = None
    search_profile: str = Field(default="general")
    max_chars: int = Field(default=8000)
    top_k: int = Field(default=10, ge=1, le=50)


# ─── Helpers ─────────────────────────────────────────────

def _build_filters(req) -> SearchFilters:
    return SearchFilters(
        jurisdiction=getattr(req, "jurisdiction", None),
        source_hierarchy=getattr(req, "source_hierarchy", None),
        source_type=getattr(req, "source_type", None),
        legal_area=getattr(req, "legal_area", None),
        vigente=getattr(req, "vigente", None),
    )


def _no_docs_response():
    return {
        "results": [],
        "total": 0,
        "message": "Base documental vacía. Cargue documentos primero.",
    }


# ─── Endpoints ───────────────────────────────────────────

@router.post("/")
async def search_documents(request: SearchRequest, db: Session = Depends(get_db)):
    """
    Búsqueda híbrida jurídica (compatibilidad).

    Combina similitud semántica + BM25 + ranking jurídico.
    Para control de perfil usar POST /search/hybrid.
    """
    chunks = _doc_service.get_all_chunks(db, document_scope="corpus")
    if not chunks:
        return _no_docs_response()

    filters = _build_filters(request)
    results = search_service.search(
        query=request.query,
        chunks=chunks,
        filters=filters,
        top_k=request.top_k,
    )

    return {
        "results": [r.to_dict() for r in results],
        "total": len(results),
        "query": request.query,
        "search_mode": "hybrid",
        "search_profile": "general",
        "filters_applied": {
            "jurisdiction": request.jurisdiction,
            "source_hierarchy": request.source_hierarchy,
            "source_type": request.source_type,
            "legal_area": request.legal_area,
            "vigente": request.vigente,
        },
    }


@router.post("/hybrid")
async def hybrid_search(request: HybridSearchRequest, db: Session = Depends(get_db)):
    """
    Búsqueda híbrida con perfil jurídico.

    Combina similitud vectorial + keyword BM25 + ranking jurídico.
    El perfil ajusta los pesos y preferencias de recuperación:

    - general:       equilibrado, sin prioridad especial
    - notifications: prioriza normativa procesal y acordadas
    - generation:    prioriza plantillas y escritos modelo
    - audit:         prioriza normativa y jurisprudencia
    - strategy:      prioriza jurisprudencia y doctrina

    Cada resultado incluye:
    - scores individuales (vector, keyword, legal)
    - retrieval_explanation: por qué fue recuperado
    - usage_warning: si es material interno no autoritativo
    """
    chunks = _doc_service.get_all_chunks(db, document_scope="corpus")
    if not chunks:
        return _no_docs_response()

    filters = _build_filters(request)
    results = search_service.hybrid_search(
        query=request.query,
        chunks=chunks,
        filters=filters,
        top_k=request.top_k,
        profile=request.search_profile,
    )

    return {
        "results": [r.to_dict() for r in results],
        "total": len(results),
        "query": request.query,
        "search_mode": "hybrid",
        "search_profile": request.search_profile,
        "filters_applied": {
            "jurisdiction": request.jurisdiction,
            "source_hierarchy": request.source_hierarchy,
            "source_type": request.source_type,
            "legal_area": request.legal_area,
            "vigente": request.vigente,
        },
    }


@router.post("/semantic")
async def semantic_search(request: SearchRequest, db: Session = Depends(get_db)):
    """
    Búsqueda semántica pura (solo similitud vectorial).

    Recupera fragmentos semánticamente similares sin considerar
    jerarquía ni metadatos jurídicos. Útil para exploración.

    NOTA: Requiere embeddings reales (sentence-transformers o similar)
    para resultados significativos. Con stub la similitud no es semántica.
    """
    chunks = _doc_service.get_all_chunks(db, document_scope="corpus")
    if not chunks:
        return _no_docs_response()

    filters = _build_filters(request)
    results = search_service.semantic_search(
        query=request.query,
        chunks=chunks,
        filters=filters,
        top_k=request.top_k,
    )

    return {
        "results": [r.to_dict() for r in results],
        "total": len(results),
        "query": request.query,
        "search_mode": "semantic",
        "nota": (
            "Solo similitud vectorial — sin ranking jurídico. "
            "Para uso en análisis jurídico, usar /hybrid con perfil adecuado."
        ),
    }


@router.post("/context")
async def get_search_context(request: ContextRequest, db: Session = Depends(get_db)):
    """
    Obtener contexto trazable para módulos de análisis/generación.

    Retorna fragmentos seleccionados con:
    - texto fuente
    - documento y jerarquía de origen
    - ubicación exacta (sección, artículo, página)
    - score de relevancia
    - advertencias de uso si corresponde

    Este endpoint alimenta el pipeline RAG.
    """
    chunks = _doc_service.get_all_chunks(db, document_scope="corpus")
    if not chunks:
        return {
            "fragments": [],
            "total_chars": 0,
            "total_results": 0,
            "sources_used": [],
            "message": "Base documental vacía.",
        }

    filters = _build_filters(request)
    context = search_service.get_context(
        query=request.query,
        chunks=chunks,
        filters=filters,
        max_chars=request.max_chars,
        top_k=request.top_k,
        profile=request.search_profile,
    )

    return context


@router.get("/profiles")
async def get_search_profiles():
    """
    Listar perfiles de búsqueda disponibles.

    Cada perfil está optimizado para un módulo específico del sistema.
    """
    return {
        "profiles": list_profiles(),
        "default": "general",
    }
