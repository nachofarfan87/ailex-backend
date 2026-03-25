"""
AILEX — Servicio de búsqueda jurídica (RAG).

Búsqueda semántica e híbrida sobre la base documental.
No es un buscador genérico — pondera jurisdicción,
jerarquía normativa, vigencia y tipo de fuente.

Modos de búsqueda:
  semantic_search  — solo similitud vectorial
  hybrid_search    — semántica + keyword + ranking jurídico (recomendado)

El ranking jurídico distingue:
  - normativa > jurisprudencia > doctrina > interno
  - Jujuy > Nacional > otra jurisdicción
  - vigente > no vigente (penalizado)
  - fuente autoritativa vs material interno (advertencia)
"""

import re
import math
from dataclasses import dataclass
from typing import Optional

from app.modules.search.ranking import LegalRanking
from app.modules.search.profiles import SearchProfile, get_profile
from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import get_default_provider


# ─── Resultado de búsqueda ────────────────────────────────

@dataclass
class SearchResult:
    """Resultado de búsqueda con trazabilidad completa."""
    chunk_id: str
    document_id: str
    text: str
    document_title: str
    source_type: str
    source_hierarchy: str
    jurisdiction: str
    legal_area: str
    section: str
    article_reference: str
    page_number: Optional[int] = None
    vigente: bool = True

    # Scores individuales
    vector_score:  float = 0.0
    keyword_score: float = 0.0
    legal_score:   float = 0.0

    # Score final combinado
    final_score: float = 0.0

    # Trazabilidad del ranking
    retrieval_explanation: str = ""
    usage_warning: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "document_title": self.document_title,
            "source_type": self.source_type,
            "source_hierarchy": self.source_hierarchy,
            "jurisdiction": self.jurisdiction,
            "legal_area": self.legal_area,
            "section": self.section,
            "article_reference": self.article_reference,
            "page_number": self.page_number,
            "vigente": self.vigente,
            "scores": {
                "vector":  round(self.vector_score, 4),
                "keyword": round(self.keyword_score, 4),
                "legal":   round(self.legal_score, 4),
                "final":   round(self.final_score, 4),
            },
            "retrieval_explanation": self.retrieval_explanation,
        }
        if self.usage_warning:
            d["usage_warning"] = self.usage_warning
        return d


# ─── Filtros de búsqueda ──────────────────────────────────

@dataclass
class SearchFilters:
    """Filtros jurídicos para la búsqueda."""
    jurisdiction:     Optional[str] = None
    source_hierarchy: Optional[str] = None   # normativa | jurisprudencia | doctrina | interno
    source_type:      Optional[str] = None   # codigo | ley | jurisprudencia | etc.
    legal_area:       Optional[str] = None
    court:            Optional[str] = None
    authority:        Optional[str] = None
    vigente:          Optional[bool] = None  # None = incluir todos
    date_from:        Optional[str] = None
    date_to:          Optional[str] = None


# ─── Servicio de búsqueda ────────────────────────────────

class HybridSearchService:
    """
    Servicio de búsqueda jurídica semántica e híbrida.

    Combina:
    1. Similitud vectorial (semántica real si hay sentence-transformers)
    2. Coincidencia keyword (BM25-like)
    3. Ranking jurídico (jerarquía, jurisdicción, vigencia, temática)

    Soporte de perfiles de búsqueda por módulo:
    - notifications: prioriza normativa procesal y acordadas
    - generation: prioriza plantillas y escritos del estudio
    - audit: prioriza normativa y jurisprudencia
    - strategy: prioriza jurisprudencia y doctrina
    """

    # BM25 parameters
    BM25_K1 = 1.5
    BM25_B = 0.75

    def __init__(self, embedder: EmbeddingProvider = None):
        self._embedder = embedder or get_default_provider()
        self._ranking = LegalRanking(
            boost_local_jurisdiction=0.20,
            boost_primary_source=0.15,
            penalize_not_vigente=0.30,
        )

    def _init_ranking_from_settings(self):
        """Actualizar parámetros de ranking desde settings (lazy)."""
        try:
            from app.config import settings
            self._ranking = LegalRanking(
                boost_local_jurisdiction=settings.boost_jurisdiccion_local,
                boost_primary_source=settings.boost_fuente_primaria,
                penalize_not_vigente=settings.penalize_no_vigente,
            )
        except Exception:
            pass  # Usar valores por defecto si settings no está disponible

    # ─── Búsqueda semántica pura ──────────────────────────

    def semantic_search(
        self,
        query: str,
        chunks: list[dict],
        filters: SearchFilters = None,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """
        Búsqueda por similitud vectorial únicamente.

        Útil para explorar semánticamente sin sesgo por keywords.
        Requiere embeddings reales para resultados significativos.

        Returns:
            Resultados ordenados por vector_score descendente.
        """
        if not chunks:
            return []
        if filters is None:
            filters = SearchFilters()

        filtered = self._apply_filters(chunks, filters)
        if not filtered:
            return []

        query_emb = self._embedder.embed_text(query)
        results = []

        for chunk in filtered:
            chunk_emb = self._embedder.from_json(chunk.get("embedding_json", ""))
            vector_score = 0.0
            if chunk_emb and query_emb:
                vector_score = max(0.0, self._embedder.cosine_similarity(query_emb, chunk_emb))

            results.append(SearchResult(
                chunk_id=chunk.get("id", ""),
                document_id=chunk.get("document_id", ""),
                text=chunk.get("text", ""),
                document_title=chunk.get("document_title", ""),
                source_type=chunk.get("source_type", ""),
                source_hierarchy=chunk.get("source_hierarchy", ""),
                jurisdiction=chunk.get("jurisdiction", ""),
                legal_area=chunk.get("legal_area", ""),
                section=chunk.get("section", ""),
                article_reference=chunk.get("article_reference", ""),
                page_number=chunk.get("page_number"),
                vigente=chunk.get("vigente", True),
                vector_score=vector_score,
                final_score=vector_score,
                retrieval_explanation=f"semantic_only | vector={vector_score:.4f}",
            ))

        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:top_k]

    # ─── Búsqueda híbrida ────────────────────────────────

    def hybrid_search(
        self,
        query: str,
        chunks: list[dict],
        filters: SearchFilters = None,
        top_k: int = 10,
        profile: "SearchProfile | str" = SearchProfile.GENERAL,
    ) -> list[SearchResult]:
        """
        Búsqueda híbrida con ranking jurídico (recomendado).

        Combina:
        - Similitud semántica (vectorial)
        - Coincidencia textual (BM25)
        - Ranking jurídico (jerarquía, jurisdicción, vigencia)

        El perfil determina los pesos y preferencias de recuperación.
        """
        if not chunks:
            return []
        if filters is None:
            filters = SearchFilters()

        profile_config = get_profile(profile)
        weights = profile_config.weights

        filtered = self._apply_filters(chunks, filters)

        # Aplicar exclusiones del perfil
        if profile_config.exclude_types:
            filtered = [
                c for c in filtered
                if c.get("source_type") not in profile_config.exclude_types
            ]

        if not filtered:
            return []

        query_emb = self._embedder.embed_text(query)
        avg_len = sum(len(c.get("text", "")) for c in filtered) / len(filtered)
        results = []

        for chunk in filtered:
            # Similitud vectorial
            chunk_emb = self._embedder.from_json(chunk.get("embedding_json", ""))
            vector_score = 0.0
            if chunk_emb and query_emb:
                vector_score = max(0.0, self._embedder.cosine_similarity(query_emb, chunk_emb))

            # Keyword BM25 con boost por términos del perfil
            effective_query = self._boost_query(query, profile_config.boost_terms)
            keyword_score = self._bm25_score(
                effective_query, chunk.get("text", ""),
                avg_len, len(filtered),
            )

            # Ranking jurídico compuesto
            ranking_result = self._ranking.rank(
                chunk=chunk,
                semantic_score=vector_score,
                keyword_score=keyword_score,
                query_jurisdiction=filters.jurisdiction,
                query_legal_area=filters.legal_area,
                weights=weights,
            )

            results.append(SearchResult(
                chunk_id=chunk.get("id", ""),
                document_id=chunk.get("document_id", ""),
                text=chunk.get("text", ""),
                document_title=chunk.get("document_title", ""),
                source_type=chunk.get("source_type", ""),
                source_hierarchy=chunk.get("source_hierarchy", ""),
                jurisdiction=chunk.get("jurisdiction", ""),
                legal_area=chunk.get("legal_area", ""),
                section=chunk.get("section", ""),
                article_reference=chunk.get("article_reference", ""),
                page_number=chunk.get("page_number"),
                vigente=chunk.get("vigente", True),
                vector_score=vector_score,
                keyword_score=keyword_score,
                legal_score=ranking_result.factors.hierarchy,
                final_score=ranking_result.final_score,
                retrieval_explanation=ranking_result.explanation,
                usage_warning=ranking_result.usage_warning,
            ))

        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:top_k]

    # ─── Alias compatibilidad ────────────────────────────

    def search(
        self,
        query: str,
        chunks: list[dict],
        filters: SearchFilters = None,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """Alias de hybrid_search con perfil GENERAL (compatibilidad)."""
        return self.hybrid_search(
            query=query,
            chunks=chunks,
            filters=filters,
            top_k=top_k,
            profile=SearchProfile.GENERAL,
        )

    # ─── Contexto trazable para RAG ──────────────────────

    def get_context(
        self,
        query: str,
        chunks: list[dict],
        filters: SearchFilters = None,
        max_chars: int = 8000,
        top_k: int = 10,
        profile: "SearchProfile | str" = SearchProfile.GENERAL,
    ) -> dict:
        """
        Obtener contexto trazable para alimentar el pipeline jurídico.

        Retorna fragmentos seleccionados con metadata completa.
        """
        results = self.hybrid_search(query, chunks, filters, top_k, profile)

        context_chunks = []
        total_chars = 0

        for result in results:
            if total_chars + len(result.text) > max_chars:
                break
            context_chunks.append({
                "text": result.text,
                "document_id": result.document_id,
                "document_title": result.document_title,
                "source_hierarchy": result.source_hierarchy,
                "source_type": result.source_type,
                "section": result.section,
                "article_reference": result.article_reference,
                "page_number": result.page_number,
                "vigente": result.vigente,
                "relevance_score": result.final_score,
                "usage_warning": result.usage_warning,
            })
            total_chars += len(result.text)

        return {
            "fragments": context_chunks,
            "total_chars": total_chars,
            "total_results": len(results),
            "sources_used": list({r.document_id for r in results[:len(context_chunks)]}),
        }

    def retrieve_for_module(
        self,
        query: str,
        chunks: list[dict],
        module: str,
        jurisdiction: str = "Jujuy",
        legal_area: str = None,
        top_k: int = 5,
        min_score: float = 0.05,
    ) -> list[SearchResult]:
        """
        Recuperar fragmentos relevantes orientados por módulo.

        Selecciona el perfil correcto y aplica filtros jurisdiccionales.
        Filtra por score mínimo para evitar citas irrelevantes.

        Args:
            module: "notifications" | "generation" | "audit" | "strategy" | "general"
            jurisdiction: jurisdicción de la consulta
            legal_area: materia jurídica (civil, penal, laboral...)
            min_score: score mínimo para incluir en resultados

        Returns:
            Lista de SearchResult filtrados y ordenados.
        """
        filters = SearchFilters(
            jurisdiction=jurisdiction,
            legal_area=legal_area,
            vigente=None,  # incluir todos; no vigentes son penalizados, no excluidos
        )

        results = self.hybrid_search(
            query=query,
            chunks=chunks,
            filters=filters,
            top_k=top_k * 2,  # recuperar más y filtrar por score
            profile=module,
        )

        return [r for r in results if r.final_score >= min_score][:top_k]

    # ─── BM25 ────────────────────────────────────────────

    def _bm25_score(
        self, query: str, text: str, avg_doc_len: float, corpus_size: int
    ) -> float:
        """BM25-like scoring simplificado."""
        query_terms = self._tokenize(query)
        doc_terms = self._tokenize(text)

        if not query_terms or not doc_terms:
            return 0.0

        doc_len = len(doc_terms)
        tf_doc: dict[str, int] = {}
        for term in doc_terms:
            tf_doc[term] = tf_doc.get(term, 0) + 1

        score = 0.0
        for term in query_terms:
            if term not in tf_doc:
                continue
            tf = tf_doc[term]
            idf = math.log(1 + (corpus_size / (1 + min(tf, corpus_size))))
            numerator = tf * (self.BM25_K1 + 1)
            denominator = tf + self.BM25_K1 * (
                1 - self.BM25_B + self.BM25_B * (doc_len / max(avg_doc_len, 1))
            )
            score += idf * (numerator / denominator)

        max_possible = (
            len(query_terms) * math.log(1 + corpus_size) * (self.BM25_K1 + 1)
        )
        return min(score / max(max_possible, 1), 1.0)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenización para BM25 (español jurídico)."""
        text = text.lower()
        text = re.sub(r'[^\w\sáéíóúñü]', ' ', text)
        stopwords = {
            'de', 'la', 'el', 'en', 'y', 'a', 'los', 'las', 'del',
            'un', 'una', 'que', 'es', 'por', 'con', 'se', 'al', 'lo',
            'su', 'para', 'como', 'no', 'más', 'o', 'le', 'ya', 'me',
        }
        return [t for t in text.split() if t not in stopwords and len(t) > 2]

    def _boost_query(self, query: str, boost_terms: list[str]) -> str:
        """
        Ampliar la query con términos del perfil presentes en el texto.

        Los términos boost se repiten en la query para aumentar su peso BM25.
        Solo se agregan si no están ya en la query original.
        """
        if not boost_terms:
            return query
        query_lower = query.lower()
        extras = [t for t in boost_terms if t.lower() not in query_lower]
        if extras:
            return query + " " + " ".join(extras[:5])  # max 5 extras
        return query

    # ─── Filtros jurídicos ──────────────────────────────

    def _apply_filters(self, chunks: list[dict], filters: SearchFilters) -> list[dict]:
        """Aplicar filtros jurídicos duros (inclusión/exclusión)."""
        result = chunks

        if filters.jurisdiction:
            result = [
                c for c in result
                if (c.get("jurisdiction", "").lower() == filters.jurisdiction.lower()
                    or not c.get("jurisdiction"))
            ]

        if filters.source_hierarchy:
            result = [
                c for c in result
                if c.get("source_hierarchy") == filters.source_hierarchy
            ]

        if filters.source_type:
            result = [
                c for c in result
                if c.get("source_type") == filters.source_type
            ]

        if filters.legal_area:
            result = [
                c for c in result
                if (c.get("legal_area", "").lower() == filters.legal_area.lower()
                    or not c.get("legal_area"))
            ]

        if filters.vigente is not None:
            result = [
                c for c in result
                if c.get("vigente", True) == filters.vigente
            ]

        return result
