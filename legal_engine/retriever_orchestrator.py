"""
AILEX — LegalRetrieverOrchestrator

Orchestration layer on top of NormativeEngine and SemanticLegalIndex.

Classifies query intent and routes to the best retrieval strategy:
  - exact_article  : deterministic lookup via NormativeEngine.get_article()
  - lexical        : keyword scan via NormativeEngine.search_articles()
  - semantic       : TF-IDF cosine via SemanticLegalIndex.semantic_search()
  - hybrid         : lexical + semantic, merged and de-duplicated

This module is retrieval-only.  It never generates legal advice or narrative
answers; it only selects and returns the best legal chunks for a future
reasoning layer.

Standalone usage:
    from legal_engine import LegalRetrieverOrchestrator

    retriever = LegalRetrieverOrchestrator()
    response  = retriever.retrieve("plazo para contestar demanda", top_k=5)
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from legal_engine.action_classifier import ActionClassification
from legal_engine.normative_engine import NormativeEngine
from legal_engine.semantic_index import SemanticLegalIndex


# ---------------------------------------------------------------------------
# Source metadata (mirrors SemanticLegalIndex._SOURCE_META for independence)
# ---------------------------------------------------------------------------

_SOURCE_META: dict[str, tuple[str, str, str]] = {
    "cpcc_jujuy":             ("jujuy",    "codigo",       "procedural"),
    "constitucion_jujuy":     ("jujuy",    "constitucion", "constitutional"),
    "constitucion_nacional":  ("nacional", "constitucion", "constitutional"),
    "codigo_civil_comercial": ("nacional", "codigo",       "civil"),
    "lct_20744":              ("nacional", "ley",          "labor"),
}

# Normative hierarchy per jurisdiction (most authoritative first).
# Used as a preference boost layer — not a hard filter.
_HIERARCHY: dict[str, list[str]] = {
    "jujuy": [
        "constitucion_nacional",
        "constitucion_jujuy",
        "cpcc_jujuy",
        "codigo_civil_comercial",
        "lct_20744",
    ],
    "nacional": [
        "constitucion_nacional",
        "codigo_civil_comercial",
        "lct_20744",
    ],
}

# Preferred source for each legal domain
_DOMAIN_PREFERRED_SOURCE: dict[str, str] = {
    "procedural":     "cpcc_jujuy",
    "constitutional": "constitucion_nacional",
    "civil":          "codigo_civil_comercial",
    "family":         "codigo_civil_comercial",
    "labor":          "lct_20744",
}

# Domain vocabulary for query classification (accent-free, lowercase)
_DOMAIN_TERMS: dict[str, frozenset[str]] = {
    "procedural": frozenset([
        "demanda", "contestacion", "plazo", "traslado", "notificacion",
        "rebeldia", "apelacion", "caducidad", "recurso", "sentencia",
        "proceso", "accion", "excepcion", "prueba", "audiencia",
        "demandado", "actor", "intimacion", "expediente", "tribunal",
        "juzgado", "camara", "instancia", "juicio", "competencia",
        "cedula", "emplazamiento", "interlocutoria", "procesal",
    ]),
    "constitutional": frozenset([
        "defensa", "igualdad", "garantia", "derecho", "debido",
        "amparo", "constitucional", "libertad", "fundamental",
        "ciudadano", "estado", "provincia", "nacion", "derechos",
        "poder", "legislatura", "ejecutivo", "judicial", "publico",
        "soberania", "democracia", "republica", "federal", "constitucion",
    ]),
    "civil": frozenset([
        "contrato", "buena", "fe", "obligacion", "responsabilidad",
        "danos", "posesion", "propiedad", "bien", "cosa",
        "acreedor", "deudor", "credito", "compraventa", "locacion",
        "donacion", "herencia", "sucesion", "persona", "sociedad",
        "perjuicios", "incumplimiento", "mora", "contractual",
        "causante", "herederos", "declaratoria", "intestada", "fallecio",
        "murio", "fallecimiento",
    ]),
    "family": frozenset([
        "divorcio", "divorciarse", "conyuge", "conyuges", "matrimonio",
        "familia", "convenio", "regulador", "presentacion", "conjunta",
        "responsabilidad", "parental", "compensacion", "economica",
        "vivienda", "alimentos", "mutuo", "acuerdo", "hijo", "hija",
        "hijos", "padre", "madre", "progenitor", "progenitora", "cuota",
        "alimentaria", "incumplimiento",
    ]),
    "labor": frozenset([
        "despido", "salario", "jornada", "licencia", "trabajador",
        "empleador", "indemnizacion", "remuneracion", "vacaciones",
        "convenio", "sindical", "horas", "extras", "accidente",
        "enfermedad", "descanso", "preaviso", "estabilidad", "laboral",
    ]),
}

# ---------------------------------------------------------------------------
# Source inference patterns (order matters — more specific first)
# ---------------------------------------------------------------------------

_SOURCE_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bcpcc\b|\bprocesal\s+civil\b|\bcodigo\s+procesal\b", re.IGNORECASE),
     "cpcc_jujuy"),
    (re.compile(
        r"\bconst(?:itucion)?\s+nac(?:ional)?\b"
        r"|\bconstitucion\s+nacional\b"
        r"|\bcn\b",
        re.IGNORECASE,
    ), "constitucion_nacional"),
    (re.compile(
        r"\bconst(?:itucion)?\s+jujuy\b"
        r"|\bconstitucion\s+prov(?:incial)?\b"
        r"|\bconst\s+prov\b",
        re.IGNORECASE,
    ), "constitucion_jujuy"),
    (re.compile(
        r"\bcccn\b|\bccyc\b|\bcodigo\s+civil\b"
        r"|\bcivil\s+y\s+comercial\b",
        re.IGNORECASE,
    ), "codigo_civil_comercial"),
    (re.compile(
        r"\blct\b"
        r"|\bley\s+de\s+contrato\s+de\s+trabajo\b"
        r"|\bley\s+20\.?744\b"
        r"|\bcontrato\s+de\s+trabajo\b",
        re.IGNORECASE,
    ), "lct_20744"),
]

# ---------------------------------------------------------------------------
# Article reference patterns
# ---------------------------------------------------------------------------

# Matches: "art 34", "art. 34", "arts. 34", "artículo 34", "articulo 34"
_ART_PREFIX: re.Pattern = re.compile(
    r"\barts?\.?\s+(\d+(?:\s*(?:bis|ter|quater))?)\b"
    r"|\barticulos?\s+(\d+(?:\s*(?:bis|ter|quater))?)\b"
    r"|\bart[ií]culos?\s+(\d+(?:\s*(?:bis|ter|quater))?)\b",
    re.IGNORECASE,
)

# Matches: "34 cpcc", "34 del cpcc", "34 lct", "34 ccyc", "34 cccn", "34 cn"
_ART_SUFFIX: re.Pattern = re.compile(
    r"\b(\d+(?:\s*(?:bis|ter|quater))?)\s+(?:del?\s+)?(?:cpcc|ccyc|cccn|lct|cn)\b",
    re.IGNORECASE,
)

# Stop words for token counting
_STOP_WORDS: frozenset[str] = frozenset([
    "de", "la", "el", "en", "que", "y", "a", "los", "se", "del",
    "las", "un", "una", "su", "con", "por", "para", "es", "al",
    "o", "no", "lo", "le", "si", "como", "mas", "pero", "sus",
    "al", "ante", "sin", "ni", "e", "u", "ya",
])


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LegalRetrieverOrchestrator:
    """
    Orchestrates legal retrieval by selecting the best strategy for each query.

    Owns or receives NormativeEngine and SemanticLegalIndex instances.
    Routes queries to exact lookup, lexical search, semantic search,
    or hybrid retrieval.  Applies normative hierarchy preferences on output.

    Thread safety: read-only after __init__; safe for concurrent retrieve() calls.
    """

    def __init__(
        self,
        normative_engine: NormativeEngine | None = None,
        semantic_index: SemanticLegalIndex | None = None,
        corpus_root: Path | None = None,
    ) -> None:
        """
        Initialise the orchestrator.

        If engines are not provided they are created and loaded/built
        immediately.  Pass pre-built instances to share corpus memory across
        multiple orchestrator instances or to inject test doubles.

        Args:
            normative_engine: Pre-loaded NormativeEngine (optional).
            semantic_index:   Pre-built SemanticLegalIndex (optional).
            corpus_root:      Override corpus root for both engines.
        """
        if normative_engine is None:
            self._norm_engine = NormativeEngine(corpus_root=corpus_root)
            self._norm_engine.load_corpus()
        else:
            self._norm_engine = normative_engine

        if semantic_index is None:
            self._sem_index = SemanticLegalIndex(corpus_root=corpus_root)
            self._sem_index.build_index()
        else:
            self._sem_index = semantic_index

    # ── Public API ─────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        jurisdiction: str = "jujuy",
        forum: str | None = None,
        classification: ActionClassification | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Main retrieval entry point.

        Classifies the query, selects a strategy, executes retrieval,
        applies hierarchy boosting, and returns a structured result dict.

        Args:
            query:          Free-text legal query in Spanish.
            top_k:          Maximum number of results to return.
            jurisdiction:   Default jurisdiction context ("jujuy" by default).
            forum:          Reserved for future use (ignored in v1).
            classification: ActionClassification or dict with classification hints.

        Returns::

            {
                "query":    "...",
                "strategy": "exact_article" | "lexical" | "semantic" | "hybrid",
                "detected": {
                    "article_number": "34" | None,
                    "source_id":      "cpcc_jujuy" | None,
                    "domain":         "procedural" | ... | "unknown",
                },
                "results":  [ <unified result dicts> ],
                "warnings": [ <str> ],
            }
        """
        warnings_list: list[str] = []
        query = (query or "").strip()

        if not query:
            return self._empty_response("", warnings=["Empty query provided."])

        strategy = self.classify_query_strategy(query)
        article_ref = self.detect_article_reference(query)
        classification_obj = self._coerce_classification(classification)
        # Domain priority: ActionClassification > classification dict hint > query detection
        domain = (
            classification_obj.domain
            if classification_obj and classification_obj.domain
            else (
                (classification or {}).get("domain")
                if isinstance(classification, dict) and classification.get("domain")
                else self.detect_domain(query)
            )
        )
        inferred_src = article_ref.get("source_id") or self.infer_source_from_query(
            query, jurisdiction
        )

        detected: dict[str, Any] = {
            "article_number": article_ref.get("article_number"),
            "source_id": inferred_src,
            "domain": domain,
        }

        results: list[dict]

        if strategy == "exact_article":
            results, warn = self.retrieve_exact_article(
                article_ref=article_ref,
                domain=domain,
                jurisdiction=jurisdiction,
                top_k=top_k,
            )
            warnings_list.extend(warn)
            if not results:
                warnings_list.append(
                    "Exact article lookup failed; falling back to hybrid retrieval."
                )
                results, warn2 = self.retrieve_hybrid(query, domain, jurisdiction, top_k)
                warnings_list.extend(warn2)
                strategy = "hybrid"

        elif strategy == "lexical":
            results, warn = self.retrieve_lexical(query, domain, jurisdiction, top_k)
            warnings_list.extend(warn)

        elif strategy == "semantic":
            results, warn = self.retrieve_semantic(query, domain, jurisdiction, top_k)
            warnings_list.extend(warn)

        else:  # hybrid
            results, warn = self.retrieve_hybrid(query, domain, jurisdiction, top_k)
            warnings_list.extend(warn)

        results = self._augment_with_classification(
            results=results,
            classification=classification_obj,
            jurisdiction=jurisdiction,
        )
        results = self.boost_by_hierarchy(results, jurisdiction, domain)
        results = results[:top_k]

        return {
            "query":    query,
            "strategy": strategy,
            "detected": detected,
            "results":  results,
            "warnings": warnings_list,
        }

    @staticmethod
    def _coerce_classification(
        classification: ActionClassification | dict[str, Any] | None,
    ) -> ActionClassification | None:
        if classification is None:
            return None
        if isinstance(classification, ActionClassification):
            return classification
        if isinstance(classification, dict) and classification.get("action_slug"):
            return ActionClassification(
                query=str(classification.get("query", "")),
                normalized_query=str(classification.get("normalized_query", "")),
                legal_intent=str(classification.get("legal_intent", "")),
                action_slug=str(classification.get("action_slug", "")),
                action_label=str(classification.get("action_label", "")),
                forum=str(classification.get("forum", "")),
                jurisdiction=str(classification.get("jurisdiction", "")),
                process_type=str(classification.get("process_type", "")),
                domain=str(classification.get("domain", "")),
                confidence_score=float(classification.get("confidence_score", 0.0)),
                matched_patterns=list(classification.get("matched_patterns") or []),
                semantic_aliases=list(classification.get("semantic_aliases") or []),
                retrieval_queries=list(classification.get("retrieval_queries") or []),
                priority_articles=list(classification.get("priority_articles") or []),
                metadata=dict(classification.get("metadata") or {}),
            )
        return None

    def _augment_with_classification(
        self,
        results: list[dict],
        classification: ActionClassification | None,
        jurisdiction: str,
    ) -> list[dict]:
        if classification is None or classification.confidence_score < 0.7:
            return results

        enriched = list(results)
        for index, article_ref in enumerate(classification.priority_articles):
            source_id = str(article_ref.get("source_id", "")).strip()
            article = str(article_ref.get("article", "")).strip()
            if not source_id or not article:
                continue
            art = self._norm_engine.get_article(source_id, article)
            if not art:
                continue
            enriched.append(
                self.to_result_schema(
                    art,
                    match_type="exact",
                    score=max(0.90, 0.99 - (index * 0.01)),
                )
            )

        return self.dedupe_results(enriched)

    # ── Query analysis helpers ─────────────────────────────────────────────────

    def detect_article_reference(self, query: str) -> dict[str, str | None]:
        """
        Detect an explicit article number reference in the query.

        Recognised patterns:
          - "art 34", "art. 34", "arts 34"
          - "artículo 34", "articulo 34", "artículos 34"
          - "34 cpcc", "34 del lct", "34 ccyc"
          - "art 34 cpcc jujuy"

        Returns:
            {"article_number": "34", "source_id": "cpcc_jujuy" | None}
            or {} if no article reference is found.
        """
        article_number: str | None = None

        m = _ART_PREFIX.search(query)
        if m:
            # One of the capturing groups will be non-None
            article_number = next(g for g in m.groups() if g is not None).strip()

        if article_number is None:
            m2 = _ART_SUFFIX.search(query)
            if m2:
                article_number = m2.group(1).strip()

        if article_number is None:
            return {}

        # Normalise "34 bis" → "34bis" to match corpus keys
        article_number = re.sub(r"\s+", "", article_number)

        source_id = self.infer_source_from_query(query)

        return {
            "article_number": article_number,
            "source_id": source_id,
        }

    def infer_source_from_query(
        self, query: str, jurisdiction: str = "jujuy"
    ) -> str | None:
        """
        Map textual hints in the query to a known source_id.

        Examples:
          - "cpcc", "procesal civil"      → "cpcc_jujuy"
          - "constitucion nacional", "cn"  → "constitucion_nacional"
          - "constitucion jujuy"           → "constitucion_jujuy"
          - "codigo civil", "cccn", "ccyc" → "codigo_civil_comercial"
          - "lct", "contrato de trabajo"   → "lct_20744"

        Args:
            query:        Raw query string.
            jurisdiction: Unused in v1; reserved for jurisdiction-aware
                          disambiguation in future versions.

        Returns:
            Matched source_id string or None.
        """
        for pattern, src_id in _SOURCE_HINTS:
            if pattern.search(query):
                return src_id
        return None

    def classify_query_strategy(self, query: str) -> str:
        """
        Classify the retrieval strategy for a query.

        Heuristics (in priority order):
          1. Has an explicit article reference  → "exact_article"
          2. ≤ 3 meaningful tokens AND source hint → "lexical"
          3. ≥ 6 meaningful tokens              → "semantic"
          4. Everything else                    → "hybrid"

        Returns:
            One of "exact_article", "lexical", "semantic", "hybrid".
        """
        if not (query or "").strip():
            return "hybrid"

        article_ref = self.detect_article_reference(query)
        if article_ref:
            return "exact_article"

        tokens = _tokenise_query(query)
        has_source = self.infer_source_from_query(query) is not None

        if len(tokens) <= 3 and has_source:
            return "lexical"

        if len(tokens) >= 6:
            return "semantic"

        return "hybrid"

    def detect_domain(self, query: str) -> str:
        """
        Return the legal domain most strongly signalled by the query.

        Returns:
            "procedural", "constitutional", "civil", "labor", or "unknown".
        """
        norm_q = _normalise(query)
        tokens = set(norm_q.split())
        best_domain = "unknown"
        best_count = 0

        for domain, terms in _DOMAIN_TERMS.items():
            count = len(tokens & terms)
            if count > best_count:
                best_count = count
                best_domain = domain

        return best_domain if best_count > 0 else "unknown"

    # ── Retrieval strategies ───────────────────────────────────────────────────

    def retrieve_exact_article(
        self,
        article_ref: dict[str, str | None],
        domain: str,
        jurisdiction: str,
        top_k: int,
    ) -> tuple[list[dict], list[str]]:
        """
        Exact article lookup via NormativeEngine.get_article().

        Strategy:
          1. If source_id is known, try it first (score = 1.0).
          2. If not found (or source unknown), try candidate sources ordered
             by domain and jurisdiction preference (score = 0.95).
          3. Returns ([], warnings) on failure without raising.

        Returns:
            (results, warnings)
        """
        warn: list[str] = []
        article_number = article_ref.get("article_number")

        if not article_number:
            warn.append("No article number found for exact lookup.")
            return [], warn

        source_id = article_ref.get("source_id")
        results: list[dict] = []

        if source_id:
            art = self._norm_engine.get_article(source_id, article_number)
            if art:
                results.append(self.to_result_schema(art, match_type="exact", score=1.0))
            else:
                warn.append(f"Article {article_number} not found in '{source_id}'.")

        if not results:
            candidates = self._candidate_sources(domain, jurisdiction)
            for cid in candidates:
                if cid == source_id:
                    continue
                art = self._norm_engine.get_article(cid, article_number)
                if art:
                    results.append(
                        self.to_result_schema(art, match_type="exact", score=0.95)
                    )
                    if len(results) >= top_k:
                        break

            if not results:
                warn.append(
                    f"Article {article_number} not found in any candidate source."
                )

        return results, warn

    def retrieve_lexical(
        self,
        query: str,
        domain: str,
        jurisdiction: str,
        top_k: int,
    ) -> tuple[list[dict], list[str]]:
        """
        Keyword retrieval via NormativeEngine.search_articles().

        Fetches up to top_k × 3 raw results then converts them to the
        unified result schema (hierarchy boosting is applied later by retrieve()).

        Returns:
            (results, warnings)
        """
        warn: list[str] = []
        lexical_query = self._clean_lexical_query(query)
        raw = self._norm_engine.search_articles(lexical_query, max_results=top_k * 3)

        if not raw:
            warn.append(f"Lexical search returned no results for: {lexical_query!r}")
            return [], warn

        results = [
            self.to_result_schema(
                art,
                match_type="lexical",
                score=self.score_result(art, domain),
            )
            for art in raw
        ]
        return results, warn

    def retrieve_semantic(
        self,
        query: str,
        domain: str,
        jurisdiction: str,
        top_k: int,
    ) -> tuple[list[dict], list[str]]:
        """
        Semantic retrieval via SemanticLegalIndex.semantic_search().

        Passes jurisdiction as a mild boost signal.  Lazily ensures the
        index is built if it was constructed externally without build_index().

        Returns:
            (results, warnings)
        """
        warn: list[str] = []

        try:
            if not self._sem_index._built:
                self._sem_index.build_index()
            raw = self._sem_index.semantic_search(
                query=query,
                top_k=top_k * 2,
                jurisdiction_boost=jurisdiction or None,
            )
        except RuntimeError as exc:
            warn.append(f"Semantic index error: {exc}")
            return [], warn
        except Exception as exc:  # noqa: BLE001
            warn.append(f"Unexpected semantic retrieval error: {exc}")
            return [], warn

        results = [self._sem_result_to_schema(r, match_type="semantic") for r in raw]
        return results, warn

    def retrieve_hybrid(
        self,
        query: str,
        domain: str,
        jurisdiction: str,
        top_k: int,
    ) -> tuple[list[dict], list[str]]:
        """
        Combined lexical + semantic retrieval.

        Steps:
          1. Run both retrieve_lexical() and retrieve_semantic().
          2. Merge: items appearing in both get a 1.1× score bonus and
             match_type = "hybrid".
          3. De-duplicate by (source_id, article).
          4. Sort by score descending.

        Returns:
            (results, warnings)
        """
        all_warnings: list[str] = []

        lex_results, lex_warn = self.retrieve_lexical(query, domain, jurisdiction, top_k)
        sem_results, sem_warn = self.retrieve_semantic(query, domain, jurisdiction, top_k)
        all_warnings.extend(lex_warn)
        all_warnings.extend(sem_warn)

        merged = self.merge_results(lex_results, sem_results)
        deduped = self.dedupe_results(merged)
        deduped.sort(key=lambda r: r["score"], reverse=True)

        return deduped[:top_k], all_warnings

    # ── Result helpers ─────────────────────────────────────────────────────────

    def normalize_query(self, query: str) -> str:
        """Lowercase, remove accents, collapse whitespace."""
        return _normalise(query)

    def boost_by_hierarchy(
        self,
        results: list[dict],
        jurisdiction: str,
        domain: str,
    ) -> list[dict]:
        """
        Apply a small multiplicative score boost based on normative hierarchy.

        Sources listed earlier in the hierarchy receive a higher boost
        (range 1.00 – 1.15).  The preferred source for the detected domain
        receives an additional 1.08× bonus.

        This is a preference layer only — no results are removed.

        Returns:
            Sorted list (descending score).
        """
        hierarchy = _HIERARCHY.get(jurisdiction, list(_SOURCE_META.keys()))
        preferred_src = _DOMAIN_PREFERRED_SOURCE.get(domain)
        n = len(hierarchy)

        for r in results:
            src = r.get("source_id", "")
            pos = hierarchy.index(src) if src in hierarchy else n
            # h_boost: 1.15 for pos=0, 1.00 for pos=n (not in hierarchy)
            h_boost = 1.0 + 0.15 * (1.0 - pos / max(n, 1))
            d_boost = 1.08 if src == preferred_src else 1.0
            r["score"] = round(r["score"] * h_boost * d_boost, 6)

        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def merge_results(
        self,
        lexical: list[dict],
        semantic: list[dict],
    ) -> list[dict]:
        """
        Merge lexical and semantic result lists.

        Items appearing in both get:
          - score = max(lex_score, sem_score) × 1.1
          - match_type = "hybrid"

        Items appearing in only one list keep their original score and type.

        Returns:
            Combined (possibly containing duplicates by key — call dedupe_results).
        """
        Result = dict[str, Any]
        key_fn = lambda r: (r.get("source_id", ""), r.get("article", ""))

        lex_map: dict[tuple, Result] = {key_fn(r): r for r in lexical}
        sem_map: dict[tuple, Result] = {key_fn(r): r for r in semantic}

        merged: list[dict] = []
        seen: set[tuple] = set()

        for k, r in lex_map.items():
            if k in sem_map:
                combined = dict(r)
                combined["score"] = round(
                    max(r["score"], sem_map[k]["score"]) * 1.1, 6
                )
                combined["match_type"] = "hybrid"
                merged.append(combined)
            else:
                merged.append(dict(r))
            seen.add(k)

        for k, r in sem_map.items():
            if k not in seen:
                merged.append(dict(r))

        return merged

    def dedupe_results(self, results: list[dict]) -> list[dict]:
        """
        Remove duplicate results by (source_id, article) key.

        Keeps the entry with the highest score when duplicates exist.

        Returns:
            De-duplicated list (order is not guaranteed; sort after calling).
        """
        seen: dict[tuple[str, str], dict] = {}
        for r in results:
            k = (r.get("source_id", ""), r.get("article", ""))
            if k not in seen or r["score"] > seen[k]["score"]:
                seen[k] = r
        return list(seen.values())

    def to_result_schema(
        self,
        art: dict,
        match_type: str,
        score: float,
    ) -> dict:
        """
        Convert a NormativeEngine article dict to the unified result schema.

        Input shape (from NormativeEngine):
            {"code", "norma", "article", "titulo", "texto"}

        Output shape::

            {
                "source_id", "article", "label", "titulo", "texto",
                "score", "match_type", "jurisdiction", "norm_type", "domain"
            }
        """
        source_id = art.get("code", "")
        article = art.get("article", "")
        titulo = art.get("titulo", "")
        texto = art.get("texto", "")

        jurisdiction, norm_type, domain = _SOURCE_META.get(
            source_id, ("desconocida", "norma", "unknown")
        )
        label = f"Artículo {article}" + (f" — {titulo}" if titulo else "")

        return {
            "source_id":    source_id,
            "article":      article,
            "label":        label,
            "titulo":       titulo,
            "texto":        texto,
            "score":        round(score, 6),
            "match_type":   match_type,
            "jurisdiction": jurisdiction,
            "norm_type":    norm_type,
            "domain":       domain,
        }

    def score_result(self, art: dict, domain: str) -> float:
        """
        Assign a base relevance score to a lexical result.

        Domain-matching source → 0.70; otherwise → 0.50.
        (Hierarchy boosting is applied later by boost_by_hierarchy().)
        """
        source_id = art.get("code", "")
        _, _, src_domain = _SOURCE_META.get(source_id, ("", "", ""))
        return 0.70 if src_domain == domain else 0.50

    # ── Private helpers ────────────────────────────────────────────────────────

    def _candidate_sources(self, domain: str, jurisdiction: str) -> list[str]:
        """
        Return an ordered list of source_ids to try for exact lookup fallback.

        The domain-preferred source is moved to the front of the jurisdiction
        hierarchy so that the most likely match is tried first.
        """
        preferred = _DOMAIN_PREFERRED_SOURCE.get(domain)
        hierarchy = list(_HIERARCHY.get(jurisdiction, list(_SOURCE_META.keys())))

        if preferred and preferred in hierarchy:
            hierarchy.remove(preferred)
            hierarchy.insert(0, preferred)

        return hierarchy

    def _sem_result_to_schema(self, r: dict, match_type: str) -> dict:
        """
        Convert a SemanticLegalIndex result dict to the unified result schema.

        SemanticLegalIndex uses the key "text"; the unified schema uses "texto".
        The "titulo" is extracted from the label when available.
        """
        source_id = r.get("source_id", "")
        article = r.get("article", "")
        label = r.get("label", f"Artículo {article}")
        texto = r.get("text", "")
        score = r.get("score", 0.0)

        titulo = ""
        if " — " in label:
            titulo = label.split(" — ", 1)[1]

        _, _, domain = _SOURCE_META.get(source_id, ("", "", "unknown"))

        return {
            "source_id":    source_id,
            "article":      article,
            "label":        label,
            "titulo":       titulo,
            "texto":        texto,
            "score":        round(score, 6),
            "match_type":   match_type,
            "jurisdiction": r.get("jurisdiction", ""),
            "norm_type":    r.get("norm_type", ""),
            "domain":       domain,
        }

    def _clean_lexical_query(self, query: str) -> str:
        """
        Remove source-identifier tokens from a query before lexical search.

        Legal source abbreviations (cpcc, lct, cccn, ccyc, cn, jujuy) are
        not present in article text bodies, so searching for them produces
        zero matches.  Stripping them first yields better recall.

        Returns the cleaned query string (falls back to original if nothing remains).
        """
        # Tokens to strip when building the lexical search term
        _SOURCE_TOKENS = re.compile(
            r"\b(cpcc|lct|cccn|ccyc|cn|jujuy|nacional|provincial"
            r"|procesal\s+civil|codigo\s+procesal|codigo\s+civil"
            r"|civil\s+y\s+comercial|contrato\s+de\s+trabajo"
            r"|ley\s+de\s+contrato\s+de\s+trabajo"
            r"|constitucion\s+(?:nacional|jujuy|provincial)"
            r"|ley\s+20\.?744)\b",
            re.IGNORECASE,
        )
        cleaned = _SOURCE_TOKENS.sub(" ", query)
        cleaned = " ".join(cleaned.split())
        return cleaned if cleaned.strip() else query

    def _empty_response(self, query: str, warnings: list[str]) -> dict[str, Any]:
        """Return a structured empty response for edge cases (e.g. empty query)."""
        return {
            "query":    query,
            "strategy": "none",
            "detected": {
                "article_number": None,
                "source_id":      None,
                "domain":         "unknown",
            },
            "results":  [],
            "warnings": warnings,
        }


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, strip combining accents, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", text)
    no_acc = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(no_acc.casefold().split())


def _tokenise_query(query: str) -> list[str]:
    """Normalise, split, and remove stop-words; returns meaningful tokens only."""
    norm = _normalise(query)
    return [
        tok for tok in norm.split()
        if tok not in _STOP_WORDS and len(tok) >= 2
    ]
