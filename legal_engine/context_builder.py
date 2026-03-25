"""
AILEX -- LegalContextBuilder

Design rationale:
  The context builder is the quality gate between raw retriever output and
  downstream reasoning.  It enforces four invariants before any analysis:

    1. Validity   -- every chunk has source_id, article, and non-empty texto.
    2. Uniqueness -- exact and near-duplicate articles are removed.
    3. Ordering   -- chunks are ranked by a composite score that balances
                     retrieval relevance, jurisdiction alignment, domain match,
                     and match type.
    4. Budget     -- total character count stays within a configurable limit
                     so downstream LLM calls never overflow their context window.

  LegalArticleChunk and LegalContext are the canonical shared data structures
  used by all other legal_engine modules.  Import them from here.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_CHARS   = 16_000   # safe for most LLM context windows
DEFAULT_MAX_RESULTS = 20       # hard cap on included articles
_NEAR_DUP_THRESHOLD = 0.80     # Jaccard trigram threshold for near-dup detection
_COMPARE_CHARS      = 400      # characters compared for near-dup detection

_JURISDICTION_WEIGHT: dict[str, float] = {
    "jujuy":    1.20,
    "nacional": 1.10,
    "federal":  1.10,
}

_MATCH_TYPE_WEIGHT: dict[str, float] = {
    "exact":    1.30,
    "hybrid":   1.10,
    "lexical":  1.00,
    "semantic": 1.00,
}

_SOURCE_LABELS: dict[str, str] = {
    "cpcc_jujuy":             "CPCC Jujuy",
    "constitucion_jujuy":     "Constitucion de Jujuy",
    "constitucion_nacional":  "Constitucion Nacional",
    "codigo_civil_comercial": "CCyC (Ley 26.994)",
    "lct_20744":              "LCT (Ley 20.744)",
}

_SECTION_ORDER: list[str] = [
    "constitutional_norms",
    "procedural_norms",
    "civil_norms",
    "labor_norms",
    "other_norms",
]

_SECTION_LABELS: dict[str, str] = {
    "constitutional_norms": "NORMATIVA CONSTITUCIONAL",
    "procedural_norms":     "NORMATIVA PROCESAL",
    "civil_norms":          "NORMATIVA CIVIL Y COMERCIAL",
    "labor_norms":          "NORMATIVA LABORAL",
    "other_norms":          "OTRAS NORMAS",
}

_DOMAIN_SECTION: dict[str, str] = {
    "constitutional": "constitutional_norms",
    "procedural":     "procedural_norms",
    "civil":          "civil_norms",
    "labor":          "labor_norms",
}


# ---------------------------------------------------------------------------
# Canonical data structures (shared across all legal_engine modules)
# ---------------------------------------------------------------------------

@dataclass
class LegalArticleChunk:
    """
    Canonical representation of a single legal article.

    Used as the shared data contract between context_builder and all
    downstream reasoning modules.  All fields are always present (never None).
    """

    source_id:    str
    article:      str
    label:        str
    titulo:       str
    texto:        str
    score:        float
    match_type:   str
    jurisdiction: str
    norm_type:    str
    domain:       str

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict) -> "LegalArticleChunk":
        """
        Build from a retriever result dict.

        Tolerates both 'texto' (NormativeEngine) and 'text' (SemanticLegalIndex)
        key names for the article body.
        """
        texto = str(d.get("texto") or d.get("text") or "")
        return cls(
            source_id=    str(d.get("source_id",    "")),
            article=      str(d.get("article",      "")),
            label=        str(d.get("label",        "")),
            titulo=       str(d.get("titulo",       "")),
            texto=        texto,
            score=        float(d.get("score",      0.0)),
            match_type=   str(d.get("match_type",   "semantic")),
            jurisdiction= str(d.get("jurisdiction", "")),
            norm_type=    str(d.get("norm_type",    "")),
            domain=       str(d.get("domain",       "unknown")),
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id":    self.source_id,
            "article":      self.article,
            "label":        self.label,
            "titulo":       self.titulo,
            "texto":        self.texto,
            "score":        self.score,
            "match_type":   self.match_type,
            "jurisdiction": self.jurisdiction,
            "norm_type":    self.norm_type,
            "domain":       self.domain,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def source_label(self) -> str:
        """Human-readable source name."""
        return _SOURCE_LABELS.get(self.source_id, self.source_id)

    def char_count(self) -> int:
        """Approximate character cost for budget tracking (includes separators)."""
        return len(self.label) + len(self.titulo) + len(self.texto) + 80

    def citation_key(self) -> tuple[str, str]:
        """Unique key for deduplication and citation validation."""
        return (self.source_id, self.article)


@dataclass
class LegalContext:
    """
    Structured legal context produced by LegalContextBuilder.

    This is the primary input contract for all downstream reasoning modules.
    Always well-formed: guaranteed non-None fields, even on empty input.

    Attributes:
        query:              Original user query.
        jurisdiction:       Target jurisdiction (lower-case).
        domain:             Dominant legal domain of the context.
        applicable_norms:   Curated, de-duplicated, sorted article list.
        total_chars:        Characters in context_text.
        truncated:          True if context was cut for budget.
        source_ids_used:    Ordered list of distinct source_ids included.
        context_text:       Ready-to-inject formatted text for an LLM.
        formatted_sections: Articles grouped by domain section.
        warnings:           Non-fatal issues logged during building.
    """

    query:              str
    jurisdiction:       str
    domain:             str
    applicable_norms:   list[LegalArticleChunk]
    total_chars:        int
    truncated:          bool
    source_ids_used:    list[str]
    context_text:       str
    formatted_sections: dict[str, list[LegalArticleChunk]]
    warnings:           list[str]

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def is_empty(self) -> bool:
        return not self.applicable_norms

    def get_by_source(self, source_id: str) -> list[LegalArticleChunk]:
        """Return all chunks from the given source."""
        return [c for c in self.applicable_norms if c.source_id == source_id]

    def get_by_domain(self, domain: str) -> list[LegalArticleChunk]:
        """Return all chunks matching the given domain."""
        return [c for c in self.applicable_norms if c.domain == domain]

    def citation_keys(self) -> set[tuple[str, str]]:
        """Return the set of (source_id, article) pairs in this context."""
        return {c.citation_key() for c in self.applicable_norms}

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "query":            self.query,
            "jurisdiction":     self.jurisdiction,
            "domain":           self.domain,
            "applicable_norms": [c.to_dict() for c in self.applicable_norms],
            "total_chars":      self.total_chars,
            "truncated":        self.truncated,
            "source_ids_used":  self.source_ids_used,
            "context_text":     self.context_text,
            "warnings":         self.warnings,
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LegalContextBuilder:
    """
    Converts raw LegalRetrieverOrchestrator results into a LegalContext.

    Pipeline: parse -> deduplicate -> sort -> truncate -> split_sections -> format

    Usage::

        builder = LegalContextBuilder()
        retriever_resp = retriever.retrieve(query, top_k=10)
        context = builder.build_context(
            query=query,
            retriever_results=retriever_resp["results"],
        )
    """

    def __init__(
        self,
        max_chars:            int = DEFAULT_MAX_CHARS,
        max_results:          int = DEFAULT_MAX_RESULTS,
        default_jurisdiction: str = "jujuy",
    ) -> None:
        self._max_chars            = max_chars
        self._max_results          = max_results
        self._default_jurisdiction = default_jurisdiction

    # ---- Public API -------------------------------------------------------

    def build_context(
        self,
        query:             str,
        retriever_results: list[dict] | None,
        jurisdiction:      str | None = None,
        domain:            str | None = None,
        _forum:            str | None = None,
    ) -> LegalContext:
        """
        Build a LegalContext from raw retriever result dicts.

        Args:
            query:             User legal query.
            retriever_results: List from retrieve()["results"]; may be None or [].
            jurisdiction:      Override jurisdiction (falls back to instance default).
            domain:            Override domain (inferred from chunks if absent).
            _forum:            Reserved for future use (forum/court hint).

        Returns:
            LegalContext -- always well-formed, even on empty/invalid input.
        """
        warnings_list: list[str] = []

        query        = (query or "").strip()
        jurisdiction = ((jurisdiction or self._default_jurisdiction) or "jujuy").strip().lower()

        if not query:
            warnings_list.append("Empty query provided to LegalContextBuilder.")

        chunks, parse_warn = self._parse_results(retriever_results or [])
        warnings_list.extend(parse_warn)

        if not chunks:
            warnings_list.append(
                "No se encontraron articulos validos en los resultados proporcionados."
            )
            return _make_empty_context(query, jurisdiction, domain or "unknown", warnings_list)

        domain = domain or _infer_domain(chunks)

        chunks = self._deduplicate(chunks, warnings_list)
        chunks = self._sort(chunks, jurisdiction, domain)
        chunks, truncated = self._truncate(chunks, warnings_list)
        sections = _split_sections(chunks)
        context_text = _format_context(query, sections, jurisdiction, domain)

        source_ids = list(dict.fromkeys(c.source_id for c in chunks))

        return LegalContext(
            query=              query,
            jurisdiction=       jurisdiction,
            domain=             domain,
            applicable_norms=   chunks,
            total_chars=        len(context_text),
            truncated=          truncated,
            source_ids_used=    source_ids,
            context_text=       context_text,
            formatted_sections= sections,
            warnings=           warnings_list,
        )

    def build(
        self,
        query:          str,
        retrieved_items: list[dict] | None = None,
        jurisdiction:   str | None = None,
        domain:         str | None = None,
        forum:          str | None = None,
    ) -> LegalContext:
        """
        Pipeline-friendly entry point.

        Accepts the `retrieved_items` kwarg the pipeline passes — a list of
        retriever result schema dicts, each shaped as::

            {"query": ..., "strategy": ..., "results": [...], "warnings": [...]}

        Flattens the nested ``results`` lists and delegates to build_context().
        """
        flat: list[dict] = []
        for item in (retrieved_items or []):
            if isinstance(item, dict):
                results = item.get("results")
                if isinstance(results, list):
                    flat.extend(results)
                else:
                    # Item is already a flat chunk dict
                    flat.append(item)
        return self.build_context(
            query=query,
            retriever_results=flat,
            jurisdiction=jurisdiction,
            domain=domain,
            _forum=forum,
        )

    def format_for_llm(
        self,
        context:        LegalContext,
        include_header: bool = True,
    ) -> str:
        """
        Return the context text, optionally wrapped with a system-prompt header.

        Use this to inject the context into an LLM messages list.
        """
        if not include_header:
            return context.context_text

        header = (
            f"CONTEXTO JURIDICO DISPONIBLE\n"
            f"Consulta: {context.query}\n"
            f"Jurisdiccion: {context.jurisdiction.capitalize()}\n"
            f"Dominio: {context.domain}\n"
            f"{'=' * 50}\n\n"
        )
        return header + context.context_text

    # ---- Step 1: parse ----------------------------------------------------

    @staticmethod
    def _parse_results(
        raw: list,
    ) -> tuple[list[LegalArticleChunk], list[str]]:
        """Parse raw result dicts into LegalArticleChunk objects."""
        chunks:   list[LegalArticleChunk] = []
        warnings: list[str]               = []

        if not isinstance(raw, list):
            warnings.append("retriever_results must be a list -- no chunks loaded.")
            return [], warnings

        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                warnings.append(f"Result[{i}] is not a dict -- skipped.")
                continue

            texto = str(item.get("texto") or item.get("text") or "").strip()
            if not texto:
                warnings.append(
                    f"Result[{i}] ({item.get('source_id','?')} "
                    f"art. {item.get('article','?')}) has no text -- skipped."
                )
                continue

            chunks.append(LegalArticleChunk.from_dict(item))

        return chunks, warnings

    # ---- Step 2: deduplicate ----------------------------------------------

    def _deduplicate(
        self,
        chunks:   list[LegalArticleChunk],
        warnings: list[str],
    ) -> list[LegalArticleChunk]:
        """
        Two-pass deduplication:
          Pass 1 -- exact (source_id, article) key: keeps highest score.
          Pass 2 -- near-duplicate text (trigram Jaccard >= threshold): keeps first.
        """
        # Pass 1: exact key
        exact: dict[tuple[str, str], LegalArticleChunk] = {}
        for c in chunks:
            k = c.citation_key()
            if k not in exact or c.score > exact[k].score:
                exact[k] = c
        after_exact = list(exact.values())

        removed_exact = len(chunks) - len(after_exact)
        if removed_exact:
            warnings.append(
                f"Deduplicacion exacta: {removed_exact} articulo(s) duplicado(s) eliminado(s)."
            )

        # Pass 2: near-duplicate text
        final: list[LegalArticleChunk] = []
        for c in after_exact:
            if not _is_near_dup(c, final):
                final.append(c)

        removed_near = len(after_exact) - len(final)
        if removed_near:
            warnings.append(
                f"Deduplicacion semantica: {removed_near} fragmento(s) muy similar(es) eliminado(s)."
            )

        return final

    # ---- Step 3: sort -----------------------------------------------------

    @staticmethod
    def _sort(
        chunks:       list[LegalArticleChunk],
        jurisdiction: str,
        domain:       str,
    ) -> list[LegalArticleChunk]:
        """
        Sort by composite score:
            score * jurisdiction_weight * jurisdiction_match * match_type_weight * domain_weight
        """
        def _key(c: LegalArticleChunk) -> float:
            jw      = _JURISDICTION_WEIGHT.get(c.jurisdiction, 1.0)
            jmatch  = 1.15 if c.jurisdiction == jurisdiction else 1.0
            mw      = _MATCH_TYPE_WEIGHT.get(c.match_type, 1.0)
            dw      = 1.20 if c.domain == domain else 1.0
            return c.score * jw * jmatch * mw * dw

        return sorted(chunks, key=_key, reverse=True)

    # ---- Step 4: truncate -------------------------------------------------

    def _truncate(
        self,
        chunks:   list[LegalArticleChunk],
        warnings: list[str],
    ) -> tuple[list[LegalArticleChunk], bool]:
        """Keep chunks within character budget and result cap."""
        kept:      list[LegalArticleChunk] = []
        used:      int                     = 0
        truncated: bool                    = False

        for c in chunks:
            if len(kept) >= self._max_results:
                truncated = True
                break
            cost = c.char_count()
            if used + cost > self._max_chars and kept:
                truncated = True
                break
            kept.append(c)
            used += cost

        if truncated:
            warnings.append(
                f"Contexto truncado: {len(kept)}/{len(chunks)} articulos incluidos "
                f"(limite: {self._max_chars:,} chars, {self._max_results} max resultados)."
            )

        return kept, truncated


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------

def _infer_domain(chunks: list[LegalArticleChunk]) -> str:
    """Return the most common domain among chunks (ignoring 'unknown')."""
    counts = Counter(c.domain for c in chunks if c.domain not in ("unknown", ""))
    if not counts:
        return "unknown"
    return counts.most_common(1)[0][0]


def _split_sections(
    chunks: list[LegalArticleChunk],
) -> dict[str, list[LegalArticleChunk]]:
    """Group chunks into named domain sections."""
    sections: dict[str, list[LegalArticleChunk]] = {}
    for c in chunks:
        key = _DOMAIN_SECTION.get(c.domain, "other_norms")
        sections.setdefault(key, []).append(c)
    return sections


def _format_context(
    query:        str,
    sections:     dict[str, list[LegalArticleChunk]],
    jurisdiction: str,
    domain:       str,
) -> str:
    """Format sections into a numbered text block for LLM injection."""
    lines:   list[str] = [
        f"Consulta: {query}",
        f"Jurisdiccion: {jurisdiction} | Dominio: {domain}",
        "",
    ]
    counter: int = 1

    for sec_key in _SECTION_ORDER:
        chunks = sections.get(sec_key, [])
        if not chunks:
            continue
        lines.append(f"[ {_SECTION_LABELS[sec_key]} ]")
        lines.append("")
        for c in chunks:
            header = f"[{counter}] {c.label}"
            if c.titulo and c.titulo not in c.label:
                header += f" -- {c.titulo}"
            lines.append(header)
            lines.append(f"    Fuente: {c.source_label()} | Jurisdiccion: {c.jurisdiction}")
            lines.append(f"    {c.texto}")
            lines.append("")
            counter += 1

    if not lines:
        return "(Sin normativa disponible para esta consulta.)"

    return "\n".join(lines).strip()


def _normalise_text(text: str) -> str:
    """Lowercase, remove accents, collapse whitespace."""
    nfkd   = unicodedata.normalize("NFKD", text)
    no_acc = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return " ".join(no_acc.casefold().split())


def _trigrams(text: str) -> frozenset[str]:
    """Character trigrams of a text string."""
    if len(text) < 3:
        return frozenset()
    return frozenset(text[i : i + 3] for i in range(len(text) - 2))


def _is_near_dup(
    candidate: LegalArticleChunk,
    existing:  list[LegalArticleChunk],
) -> bool:
    """True if candidate is a near-duplicate of any existing chunk."""
    c_text = _normalise_text(candidate.texto)[:_COMPARE_CHARS]
    c_tri  = _trigrams(c_text)
    if not c_tri:
        return False
    for ex in existing:
        e_text = _normalise_text(ex.texto)[:_COMPARE_CHARS]
        e_tri  = _trigrams(e_text)
        if not e_tri:
            continue
        inter = len(c_tri & e_tri)
        union = len(c_tri | e_tri)
        if union and inter / union >= _NEAR_DUP_THRESHOLD:
            return True
    return False


def _make_empty_context(
    query:        str,
    jurisdiction: str,
    domain:       str,
    warnings:     list[str],
) -> LegalContext:
    return LegalContext(
        query=              query,
        jurisdiction=       jurisdiction,
        domain=             domain,
        applicable_norms=   [],
        total_chars=        0,
        truncated=          False,
        source_ids_used=    [],
        context_text=       "(Sin normativa disponible para esta consulta.)",
        formatted_sections= {},
        warnings=           warnings,
    )
