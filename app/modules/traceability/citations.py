"""
AILEX — Trazabilidad de citas documentales.

Convierte resultados de búsqueda (SearchResult) en
SourceCitationSchema compatibles con JuridicalResponse.

Esto es el puente entre el sistema de recuperación documental
y el contrato de respuesta jurídica.

Principio: toda afirmación que se respalde en un fragmento
de documento debe quedar registrada con:
  - documento de origen
  - chunk exacto
  - fragmento textual utilizado
  - score de relevancia
  - carácter (extraido | inferencia)
"""

from app.api.schemas.contracts import (
    SourceCitationSchema,
    SourceHierarchy,
    InformationType,
)


def search_result_to_citation(
    search_result,
    caracter: InformationType = InformationType.EXTRAIDO,
    fragment_max_chars: int = 400,
) -> SourceCitationSchema:
    """
    Convertir un SearchResult en un SourceCitationSchema.

    Args:
        search_result: SearchResult del HybridSearchService
        caracter: EXTRAIDO (del documento) | INFERENCIA (deducido)
        fragment_max_chars: recortar el texto del chunk a este largo

    Returns:
        SourceCitationSchema listo para incluir en fuentes_respaldo
    """
    # Recortar el fragmento si es muy largo
    fragment = search_result.text
    if len(fragment) > fragment_max_chars:
        fragment = fragment[:fragment_max_chars].rstrip() + "…"

    # Mapear source_hierarchy string → enum
    hierarchy_map = {
        "normativa": SourceHierarchy.NORMATIVA,
        "jurisprudencia": SourceHierarchy.JURISPRUDENCIA,
        "doctrina": SourceHierarchy.DOCTRINA,
        "interno": SourceHierarchy.INTERNO,
    }
    hierarchy = hierarchy_map.get(
        search_result.source_hierarchy, SourceHierarchy.INTERNO
    )

    # Construir referencia de sección/página
    page_or_section = None
    parts = []
    if search_result.article_reference:
        parts.append(search_result.article_reference)
    if search_result.section:
        parts.append(f"Sección: {search_result.section}")
    if search_result.page_number:
        parts.append(f"Pág. {search_result.page_number}")
    if parts:
        page_or_section = " | ".join(parts)

    return SourceCitationSchema(
        document_id=search_result.document_id,
        document_title=search_result.document_title,
        source_hierarchy=hierarchy,
        fragment=fragment,
        page_or_section=page_or_section,
        relevance_score=round(search_result.final_score, 4),
    )


def search_results_to_citations(
    search_results: list,
    caracter: InformationType = InformationType.EXTRAIDO,
    max_citations: int = 5,
    min_score: float = 0.05,
) -> list[SourceCitationSchema]:
    """
    Convertir una lista de SearchResult en fuentes_respaldo.

    Filtra por score mínimo para evitar citas irrelevantes.
    Limita el total de citas para no sobrecargar la respuesta.

    Args:
        search_results: resultados del HybridSearchService
        caracter: carácter de todas las citas (EXTRAIDO por defecto)
        max_citations: máximo de fuentes a incluir
        min_score: score mínimo para incluir una cita

    Returns:
        Lista de SourceCitationSchema ordenada por relevancia
    """
    citations = []

    for result in search_results:
        if result.final_score < min_score:
            continue
        if len(citations) >= max_citations:
            break

        citation = search_result_to_citation(result, caracter)
        citations.append(citation)

    return citations


def build_fuentes_respaldo_from_context(context: dict) -> list[SourceCitationSchema]:
    """
    Construir fuentes_respaldo desde el output de HybridSearchService.get_context().

    Uso típico en servicios de análisis/generación:

        context = search_service.get_context(query, chunks)
        fuentes = build_fuentes_respaldo_from_context(context)
        # fuentes → JuridicalResponse.fuentes_respaldo

    Args:
        context: dict con "fragments" (lista de fragmentos con metadata)

    Returns:
        Lista de SourceCitationSchema compatible con JuridicalResponse
    """
    citations = []

    for fragment in context.get("fragments", []):
        text = fragment.get("text", "")
        if not text:
            continue

        fragment_truncated = text[:400].rstrip() + ("…" if len(text) > 400 else "")

        hierarchy_raw = fragment.get("source_hierarchy", "interno")
        hierarchy_map = {
            "normativa": SourceHierarchy.NORMATIVA,
            "jurisprudencia": SourceHierarchy.JURISPRUDENCIA,
            "doctrina": SourceHierarchy.DOCTRINA,
            "interno": SourceHierarchy.INTERNO,
        }
        hierarchy = hierarchy_map.get(hierarchy_raw, SourceHierarchy.INTERNO)

        page_or_section = None
        parts = []
        if fragment.get("article_reference"):
            parts.append(fragment["article_reference"])
        if fragment.get("section"):
            parts.append(f"Sección: {fragment['section']}")
        if fragment.get("page_number"):
            parts.append(f"Pág. {fragment['page_number']}")
        if parts:
            page_or_section = " | ".join(parts)

        citation = SourceCitationSchema(
            document_id=fragment.get("document_id"),
            document_title=fragment.get("document_title", "Documento sin título"),
            source_hierarchy=hierarchy,
            fragment=fragment_truncated,
            page_or_section=page_or_section,
            relevance_score=round(fragment.get("relevance_score", 0.0), 4),
        )
        citations.append(citation)

    return citations


def deduplicate_citations(
    citations: list[SourceCitationSchema],
) -> list[SourceCitationSchema]:
    """
    Eliminar citas duplicadas (mismo documento_id + mismo fragmento inicial).

    Útil cuando múltiples búsquedas recuperan el mismo fragmento.
    """
    seen = set()
    unique = []

    for c in citations:
        key = (c.document_id, c.fragment[:100] if c.fragment else "")
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique
