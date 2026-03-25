"""
AILEX — API Routes: Fuentes documentales.
Consulta y estadísticas de la base documental por jerarquía.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from sqlalchemy.orm import Session

from app.api.schemas.contracts import SourceType
from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.services.document_service import DocumentService

router = APIRouter(dependencies=[Depends(get_current_user)])
_doc_service = DocumentService()


@router.get("/")
async def list_sources(
    hierarchy: Optional[str] = None,
    source_type: Optional[str] = None,
    materia: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    db: Session = Depends(get_db),
):
    """
    Listar fuentes documentales.
    Filtrar por jerarquía, tipo, materia y jurisdicción.

    hierarchy: normativa | jurisprudencia | doctrina | interno
    source_type: codigo | ley | reglamento | acordada | jurisprudencia | doctrina | escrito | modelo
    """
    result = _doc_service.list_documents(
        db,
        source_hierarchy=hierarchy,
        source_type=source_type,
        jurisdiction=jurisdiction,
        legal_area=materia,
        document_scope="corpus",
        page=page,
        per_page=per_page,
    )

    # Calcular counts por jerarquía para el resumen
    stats = _doc_service.get_stats(db, document_scope="corpus")
    hierarchy_counts = stats.get("by_hierarchy", {})
    type_counts = stats.get("by_type", {})

    return {
        "sources": result["documents"],
        "total": result["total"],
        "page": result["page"],
        "per_page": result["per_page"],
        "hierarchy_counts": hierarchy_counts,
        "type_counts": type_counts,
    }


@router.get("/hierarchy-summary")
async def get_hierarchy_summary(db: Session = Depends(get_db)):
    """
    Resumen de la base documental por jerarquía jurídica.
    Muestra cuántos documentos hay por tipo de fuente.
    """
    stats = _doc_service.get_stats(db, document_scope="corpus")
    return {
        "total_documents": stats["total_documents"],
        "total_chunks": stats["total_chunks"],
        "by_hierarchy": stats["by_hierarchy"],
        "by_type": stats["by_type"],
        "hierarchy_definitions": {
            "normativa": "Códigos, leyes, reglamentos, acordadas — máximo peso argumental",
            "jurisprudencia": "Fallos y sentencias — peso alto",
            "doctrina": "Comentarios doctrinarios — peso medio, no vinculante",
            "interno": "Material del estudio — uso práctico sin peso formal",
        },
    }


@router.get("/types")
async def get_source_types():
    """Listar tipos de fuente disponibles con descripción."""
    return {
        "source_types": [
            {
                "value": st.value,
                "label": st.value.replace("_", " ").title(),
                "hierarchy": _type_to_hierarchy(st.value),
                "uso": _type_to_uso(st.value),
            }
            for st in SourceType
        ],
    }


@router.get("/{source_id}")
async def get_source(source_id: str, db: Session = Depends(get_db)):
    """Obtener detalle de una fuente documental."""
    doc = _doc_service.get_document(db, source_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    return doc


@router.get("/{source_id}/citations")
async def get_source_citations(source_id: str, db: Session = Depends(get_db)):
    """
    Obtener chunks de una fuente que han sido usados como citas.
    En esta etapa retorna los chunks disponibles del documento.
    """
    doc = _doc_service.get_document(db, source_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")

    chunks = _doc_service.get_chunks(db, source_id)

    return {
        "source_id": source_id,
        "document_title": doc.get("title"),
        "source_hierarchy": doc.get("source_hierarchy"),
        "total_chunks": len(chunks),
        "chunks": [
            {
                "id": c.get("id"),
                "text": c.get("text", "")[:300] + ("\u2026" if len(c.get("text", "")) > 300 else ""),
                "section": c.get("section"),
                "article_reference": c.get("article_reference"),
                "chunk_index": c.get("chunk_index"),
            }
            for c in chunks
        ],
    }


# ─── Helpers internos ───────────────────────────────────────

def _type_to_hierarchy(source_type: str) -> str:
    mapping = {
        "codigo": "normativa",
        "ley": "normativa",
        "reglamento": "normativa",
        "acordada": "normativa",
        "jurisprudencia": "jurisprudencia",
        "doctrina": "doctrina",
        "escrito": "interno",
        "escritos_estudio": "interno",
        "modelo": "interno",
        "plantillas": "interno",
        "estrategia": "interno",
    }
    return mapping.get(source_type, "interno")


def _type_to_uso(source_type: str) -> str:
    mapping = {
        "codigo": "Vinculante \u2014 citable en escritos con peso m\u00e1ximo",
        "ley": "Vinculante \u2014 citable en escritos",
        "reglamento": "Vinculante \u2014 decreto reglamentario",
        "acordada": "Vinculante \u2014 acordada judicial",
        "jurisprudencia": "Referencial \u2014 orientador, no vinculante salvo STJ propio fuero",
        "doctrina": "Referencial \u2014 no vinculante, refuerza argumentaci\u00f3n",
        "escrito": "Interno \u2014 referencia para el estudio",
        "escritos_estudio": "Interno \u2014 referencia para el estudio",
        "modelo": "Interno \u2014 plantilla base",
        "plantillas": "Interno \u2014 plantilla base",
        "estrategia": "Interno \u2014 notas de estrategia procesal",
    }
    return mapping.get(source_type, "Interno")
