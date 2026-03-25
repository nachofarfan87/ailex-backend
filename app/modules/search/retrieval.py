"""
AILEX — Helper de recuperación documental para servicios.

Función de alto nivel que conecta una consulta en lenguaje natural
con fuentes_respaldo listas para JuridicalResponse.

Dos modos de retrieval:
  retrieve_sources()       — corpus normativo (scope=corpus)
  retrieve_case_sources()  — documentos del expediente (scope=case + expediente_id)

Ambas funciones son seguras: si la base está vacía o la búsqueda falla,
retornan lista vacía sin romper el pipeline jurídico.
"""

import os
from typing import Optional

from sqlalchemy.orm import Session

from app.api.schemas.contracts import SourceCitationSchema, InformationType
from app.modules.search.service import HybridSearchService, SearchFilters, SearchResult
from app.modules.traceability.citations import search_results_to_citations
from app.services.document_service import DocumentService


_doc_service = DocumentService()
_search = HybridSearchService()

# Boost multiplicador para resultados de documentos del expediente.
# Un doc del caso es más relevante que un doc genérico del corpus
# con el mismo score semántico.
_CASE_DOC_BOOST = float(os.getenv("CASE_DOC_BOOST", "1.25"))


async def retrieve_sources(
    query: str,
    module: str = "general",
    jurisdiction: str = "Jujuy",
    legal_area: Optional[str] = None,
    source_hierarchy: Optional[str] = None,
    source_type: Optional[str] = None,
    top_k: int = 5,
    min_score: float = 0.05,
    caracter: InformationType = InformationType.EXTRAIDO,
    db: Optional[Session] = None,
) -> list[SourceCitationSchema]:
    """
    Recuperar fuentes documentales relevantes del corpus normativo.

    Orquesta: DB → hybrid_search → citations → fuentes_respaldo.
    Solo busca documentos con scope=corpus.
    """
    try:
        if db is not None:
            return _retrieve_with_session(
                db, query, module, jurisdiction, legal_area,
                source_hierarchy, source_type, top_k, min_score, caracter,
            )

        from app.db.database import SessionLocal

        session = SessionLocal()
        try:
            return _retrieve_with_session(
                session, query, module, jurisdiction, legal_area,
                source_hierarchy, source_type, top_k, min_score, caracter,
            )
        finally:
            session.close()

    except Exception:
        return []


def retrieve_case_chunks(
    db: Session,
    query: str,
    expediente_id: str,
    jurisdiction: str = "Jujuy",
    legal_area: Optional[str] = None,
    top_k: int = 10,
    min_score: float = 0.03,
    profile: str = "general",
) -> list[SearchResult]:
    """
    Recuperar chunks relevantes de los documentos del expediente.

    Busca en documentos vinculados al expediente (cualquier scope)
    usando HybridSearchService. Aplica un boost de relevancia
    porque los docs del caso son contextualmente prioritarios.

    Args:
        db: SQLAlchemy session.
        query: consulta en lenguaje natural.
        expediente_id: ID del expediente cuyos docs buscar.
        jurisdiction: jurisdicción para filtrado.
        legal_area: área jurídica opcional.
        top_k: máximo de resultados.
        min_score: score mínimo (más bajo que corpus — los docs del
                   caso son relevantes por contexto incluso con match bajo).
        profile: perfil de búsqueda.

    Returns:
        Lista de SearchResult con boost aplicado, ordenados por score.
        Lista vacía si no hay documentos o no hay resultados.
    """
    try:
        chunks = _doc_service.get_expediente_chunks(db, expediente_id)
        if not chunks:
            return []

        filters = SearchFilters(
            jurisdiction=jurisdiction,
            legal_area=legal_area,
        )

        results = _search.hybrid_search(
            query=query,
            chunks=chunks,
            filters=filters,
            top_k=top_k * 2,
            profile=profile,
        )

        # Aplicar boost: docs del expediente son contextualmente prioritarios
        for r in results:
            r.final_score = r.final_score * _CASE_DOC_BOOST
            r.retrieval_explanation = f"case_doc_boost={_CASE_DOC_BOOST} | {r.retrieval_explanation}"

        return [r for r in results if r.final_score >= min_score][:top_k]

    except Exception:
        return []


def merge_normative_and_case_results(
    normative_items: list[dict],
    case_results: list[SearchResult],
    top_k: int = 10,
) -> list[dict]:
    """
    Combinar resultados normativos (del retriever) con resultados
    de documentos del caso (del HybridSearchService).

    Los case_results se convierten al schema del pipeline
    y se intercalan por score con los normativos.

    Dedup por chunk_id para evitar duplicados si un documento
    del caso también está en el corpus.

    Returns:
        Lista combinada ordenada por score, max top_k items.
    """
    # Convertir case SearchResults al schema de retrieved_items del pipeline
    case_items: list[dict] = []
    for r in case_results:
        case_items.append({
            "source_id": r.document_id,
            "article": r.article_reference or "",
            "label": r.document_title,
            "titulo": r.document_title,
            "texto": r.text,
            "score": r.final_score,
            "match_type": "case_document",
            "jurisdiction": r.jurisdiction,
            "norm_type": r.source_type,
            "domain": r.legal_area or "",
            "source_hierarchy": r.source_hierarchy,
            "chunk_id": r.chunk_id,
            "section": r.section,
            "page_number": r.page_number,
            "vigente": r.vigente,
            "retrieval_explanation": r.retrieval_explanation,
        })

    # Dedup: si un chunk_id del caso ya aparece en normative, quitar del normative
    case_chunk_ids = {item.get("chunk_id") for item in case_items if item.get("chunk_id")}
    deduped_normative = [
        item for item in normative_items
        if item.get("chunk_id") not in case_chunk_ids
    ]

    merged = case_items + deduped_normative
    merged.sort(key=lambda r: r.get("score", 0), reverse=True)
    return merged[:top_k]


def _retrieve_with_session(
    db: Session,
    query: str,
    module: str,
    jurisdiction: str,
    legal_area: Optional[str],
    source_hierarchy: Optional[str],
    source_type: Optional[str],
    top_k: int,
    min_score: float,
    caracter: InformationType,
) -> list[SourceCitationSchema]:
    """Core retrieval logic using a DB session."""
    chunks = _doc_service.get_all_chunks(db, document_scope="corpus")
    if not chunks:
        return []

    filters = SearchFilters(
        jurisdiction=jurisdiction,
        legal_area=legal_area,
        source_hierarchy=source_hierarchy,
        source_type=source_type,
    )

    results = _search.hybrid_search(
        query=query,
        chunks=chunks,
        filters=filters,
        top_k=top_k * 2,
        profile=module,
    )

    return search_results_to_citations(
        search_results=results,
        caracter=caracter,
        max_citations=top_k,
        min_score=min_score,
    )


def has_normative_sources(fuentes: list[SourceCitationSchema]) -> bool:
    """Verificar si hay al menos una fuente normativa o jurisprudencial."""
    from app.api.schemas.contracts import SourceHierarchy
    authoritative = {SourceHierarchy.NORMATIVA, SourceHierarchy.JURISPRUDENCIA}
    return any(f.source_hierarchy in authoritative for f in fuentes)
