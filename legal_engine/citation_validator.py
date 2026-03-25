"""
AILEX -- CitationValidator

Design rationale:
  Any citation that appears in a reasoning output must be verifiable against
  a known source.  This module is the trust boundary: it marks citations as
  VALID, DOUBTFUL, or INVALID before they reach the end user.

  Two complementary lookup strategies:
    1. Context lookup  -- check whether (source_id, article) is present in the
                          LegalContext that was used to build the reasoning.
                          This is the primary, fast path.
    2. Engine lookup   -- optionally fall back to NormativeEngine.get_article()
                          for citations that are structurally valid but were not
                          included in the truncated context.

  Citation string parsing handles common Spanish legal notation:
    - "Art. 34 CPCC Jujuy"
    - "Articulo 19 de la Constitucion Nacional"
    - "Art. 245 LCT"
    - "cpcc_jujuy:34"  (internal structured format)
    - bare source_id + article pairs from structured dicts

  All results are deterministic: same input always produces same output.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class CitationStatus(str, Enum):
    """Validation verdict for a single citation."""
    VALID   = "valid"
    DOUBTFUL = "doubtful"
    INVALID = "invalid"


@dataclass
class ValidatedCitation:
    """
    Validation result for a single citation reference.

    Attributes:
        raw:        The original citation string as provided.
        source_id:  Resolved source identifier (may be None if unparseable).
        article:    Resolved article number (may be None if unparseable).
        status:     VALID / DOUBTFUL / INVALID.
        reason:     Human-readable explanation of the verdict.
        confidence: 0.0 -- 1.0 indicating certainty of the verdict.
    """
    raw:        str
    source_id:  str | None
    article:    str | None
    status:     CitationStatus
    reason:     str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw":        self.raw,
            "source_id":  self.source_id,
            "article":    self.article,
            "status":     self.status.value,
            "reason":     self.reason,
            "confidence": self.confidence,
        }

    def is_valid(self) -> bool:
        return self.status == CitationStatus.VALID

    def is_safe(self) -> bool:
        return self.status in (CitationStatus.VALID, CitationStatus.DOUBTFUL)


@dataclass
class ValidationReport:
    """
    Aggregate result of validating a set of citations.

    Attributes:
        citations:      Per-citation validation results.
        valid_count:    Count of VALID citations.
        doubtful_count: Count of DOUBTFUL citations.
        invalid_count:  Count of INVALID citations.
        is_safe:        True when no INVALID citations are present.
        warnings:       Non-fatal issues encountered during validation.
    """
    citations:      list[ValidatedCitation]
    valid_count:    int
    doubtful_count: int
    invalid_count:  int
    is_safe:        bool
    warnings:       list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "citations":      [c.to_dict() for c in self.citations],
            "valid_count":    self.valid_count,
            "doubtful_count": self.doubtful_count,
            "invalid_count":  self.invalid_count,
            "is_safe":        self.is_safe,
            "warnings":       self.warnings,
        }

    def invalid_citations(self) -> list[ValidatedCitation]:
        return [c for c in self.citations if c.status == CitationStatus.INVALID]

    def doubtful_citations(self) -> list[ValidatedCitation]:
        return [c for c in self.citations if c.status == CitationStatus.DOUBTFUL]


# ---------------------------------------------------------------------------
# Source normalisation table
# ---------------------------------------------------------------------------

# Maps normalised text fragments to known source_ids.
# Checked in order: more specific patterns first.
_SOURCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bcpcc\b|\bprocesal\s+civil\b|\bcodigo\s+procesal\b", re.I), "cpcc_jujuy"),
    (re.compile(
        r"\bconst(?:itucion)?\s+nac(?:ional)?\b|\bconstitucion\s+nacional\b|\bcn\b", re.I),
     "constitucion_nacional"),
    (re.compile(
        r"\bconst(?:itucion)?\s+jujuy\b|\bconstitucion\s+prov(?:incial)?\b", re.I),
     "constitucion_jujuy"),
    (re.compile(
        r"\bcccn\b|\bccyc\b|\bcodigo\s+civil\b|\bcivil\s+y\s+comercial\b", re.I),
     "codigo_civil_comercial"),
    (re.compile(
        r"\blct\b|\bley\s+20\.?744\b|\bcontrato\s+de\s+trabajo\b", re.I),
     "lct_20744"),
]

# Known source_ids accepted in the internal "source_id:article" format
_KNOWN_SOURCE_IDS: frozenset[str] = frozenset([
    "cpcc_jujuy",
    "constitucion_jujuy",
    "constitucion_nacional",
    "codigo_civil_comercial",
    "lct_20744",
])

# Article number extraction (after the "Art." / "Articulo" prefix)
_ART_RE = re.compile(
    r"\barts?\.?\s*(\d+(?:\s*(?:bis|ter|quater))?)\b"
    r"|\barticulos?\s+(\d+(?:\s*(?:bis|ter|quater))?)\b"
    r"|\bart[i\xed]culos?\s+(\d+(?:\s*(?:bis|ter|quater))?)\b",
    re.I,
)

# Structured format: "source_id:article"
_STRUCTURED_RE = re.compile(
    r"^([a-z][a-z0-9_]+):(\d+(?:bis|ter|quater)?)$",
    re.I,
)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CitationValidator:
    """
    Validates citation strings against a LegalContext and/or NormativeEngine.

    Usage::

        from legal_engine.context_builder import LegalContext
        validator = CitationValidator()
        report = validator.validate(
            citations=["Art. 34 CPCC Jujuy", "Art. 9999 LCT"],
            context=legal_context,
        )
        if not report.is_safe:
            for inv in report.invalid_citations():
                print(inv.reason)
    """

    def __init__(self, normative_engine=None) -> None:
        """
        Args:
            normative_engine: Optional pre-loaded NormativeEngine instance.
                              When provided, enables engine-based fallback lookup.
        """
        self._engine = normative_engine

    # ---- Public API -------------------------------------------------------

    def validate(
        self,
        citations: list[str | dict],
        context=None,          # LegalContext | None
    ) -> ValidationReport:
        """
        Validate a list of citations against the provided context.

        Args:
            citations: Citation strings (e.g. "Art. 34 CPCC Jujuy") or
                       structured dicts with keys "source_id" and "article".
            context:   LegalContext produced by LegalContextBuilder.
                       Used as the primary lookup source.

        Returns:
            ValidationReport with per-citation results and aggregate counts.
        """
        warnings:  list[str]             = []
        validated: list[ValidatedCitation] = []

        if not isinstance(citations, list):
            warnings.append("citations must be a list.")
            citations = []

        # Build fast-lookup key set from context
        context_keys: set[tuple[str, str]] = set()
        if context is not None:
            if isinstance(context, dict):
                for norm in (context.get("applicable_norms") or []):
                    if isinstance(norm, dict):
                        sid = norm.get("source_id", "")
                        art = norm.get("article", "")
                        if sid and art:
                            context_keys.add((str(sid), str(art)))
            else:
                try:
                    context_keys = context.citation_keys()
                except AttributeError:
                    warnings.append("context object has no citation_keys() method -- skipped.")

        seen: set[str] = set()
        for raw in citations:
            raw_str = self._normalise_raw(raw)
            if raw_str in seen:
                continue
            seen.add(raw_str)
            vc = self._validate_one(raw_str, raw, context_keys)
            validated.append(vc)

        valid_count    = sum(1 for v in validated if v.status == CitationStatus.VALID)
        doubtful_count = sum(1 for v in validated if v.status == CitationStatus.DOUBTFUL)
        invalid_count  = sum(1 for v in validated if v.status == CitationStatus.INVALID)

        return ValidationReport(
            citations=      validated,
            valid_count=    valid_count,
            doubtful_count= doubtful_count,
            invalid_count=  invalid_count,
            is_safe=        invalid_count == 0,
            warnings=       warnings,
        )

    def validate_context(self, context) -> ValidationReport:
        """
        Validate every article in the context against the NormativeEngine.

        Useful as a corpus integrity check: confirms that all articles returned
        by the retriever actually exist in the normative corpus.

        Requires normative_engine to have been provided at construction time.
        Returns a DOUBTFUL report (not INVALID) for articles not found in engine,
        since the retriever may legitimately include articles the engine doesn't index.
        """
        if context is None or context.is_empty():
            return ValidationReport(
                citations=[], valid_count=0, doubtful_count=0,
                invalid_count=0, is_safe=True,
                warnings=["Context is empty -- nothing to validate."],
            )

        citations = [
            f"{c.source_id}:{c.article}" for c in context.applicable_norms
        ]
        return self.validate(citations, context=context)

    def parse_citation(self, raw: str) -> dict[str, str | None]:
        """
        Parse a citation string into its components.

        Args:
            raw: Citation string in any supported format.

        Returns:
            {"source_id": str | None, "article": str | None}
            Both fields are None if the citation is completely unparseable.
        """
        if not raw or not raw.strip():
            return {"source_id": None, "article": None}

        # Structured format: "cpcc_jujuy:34"
        m = _STRUCTURED_RE.match(raw.strip())
        if m:
            src = m.group(1).lower()
            art = re.sub(r"\s+", "", m.group(2))
            if src in _KNOWN_SOURCE_IDS:
                return {"source_id": src, "article": art}
            return {"source_id": None, "article": art}

        # Natural language format
        article  = self._extract_article(raw)
        source   = self._extract_source(raw)
        return {"source_id": source, "article": article}

    # ---- Private ----------------------------------------------------------

    def _validate_one(
        self,
        raw_str:      str,
        original:     str | dict,
        context_keys: set[tuple[str, str]],
    ) -> ValidatedCitation:
        """Validate a single citation string."""
        parsed = self.parse_citation(raw_str)
        source_id = parsed["source_id"]
        article   = parsed["article"]

        # Completely unparseable
        if source_id is None and article is None:
            return ValidatedCitation(
                raw=raw_str, source_id=None, article=None,
                status=CitationStatus.INVALID,
                reason="Cita no parseable: no se pudo extraer fuente ni articulo.",
                confidence=0.95,
            )

        # Article extracted but no source -- doubtful
        if source_id is None:
            return ValidatedCitation(
                raw=raw_str, source_id=None, article=article,
                status=CitationStatus.DOUBTFUL,
                reason=f"Fuente no identificada para el Art. {article}. "
                       "Verificar manualmente.",
                confidence=0.70,
            )

        # Article missing but source identified -- doubtful
        if article is None:
            return ValidatedCitation(
                raw=raw_str, source_id=source_id, article=None,
                status=CitationStatus.DOUBTFUL,
                reason=f"Numero de articulo no identificado en '{source_id}'. "
                       "Verificar manualmente.",
                confidence=0.70,
            )

        key = (source_id, article)

        # Primary check: context lookup (fast)
        if key in context_keys:
            return ValidatedCitation(
                raw=raw_str, source_id=source_id, article=article,
                status=CitationStatus.VALID,
                reason=f"Art. {article} de {source_id} presente en el contexto de recuperacion.",
                confidence=0.99,
            )

        # Secondary check: engine lookup (slower, optional)
        if self._engine is not None:
            art_data = self._engine.get_article(source_id, article)
            if art_data:
                return ValidatedCitation(
                    raw=raw_str, source_id=source_id, article=article,
                    status=CitationStatus.DOUBTFUL,
                    reason=f"Art. {article} de {source_id} existe en corpus pero "
                           "no fue incluido en el contexto actual (puede haber sido truncado).",
                    confidence=0.80,
                )
            # Not in engine either
            return ValidatedCitation(
                raw=raw_str, source_id=source_id, article=article,
                status=CitationStatus.INVALID,
                reason=f"Art. {article} de {source_id} no encontrado en corpus normativo.",
                confidence=0.90,
            )

        # No engine: if source is known, mark doubtful (can't confirm without engine)
        if source_id in _KNOWN_SOURCE_IDS:
            return ValidatedCitation(
                raw=raw_str, source_id=source_id, article=article,
                status=CitationStatus.DOUBTFUL,
                reason=f"Art. {article} de {source_id} no presente en el contexto actual. "
                       "Sin motor normativo, no es posible confirmar su existencia.",
                confidence=0.60,
            )

        # Unknown source
        return ValidatedCitation(
            raw=raw_str, source_id=source_id, article=article,
            status=CitationStatus.INVALID,
            reason=f"Fuente '{source_id}' no reconocida en el corpus normativo.",
            confidence=0.85,
        )

    @staticmethod
    def _extract_article(text: str) -> str | None:
        """Extract the article number from a citation string."""
        m = _ART_RE.search(text)
        if m:
            num = next(g for g in m.groups() if g is not None)
            return re.sub(r"\s+", "", num.strip())
        return None

    @staticmethod
    def _extract_source(text: str) -> str | None:
        """Extract the source_id from a citation string by pattern matching."""
        for pattern, src_id in _SOURCE_PATTERNS:
            if pattern.search(text):
                return src_id
        return None

    @staticmethod
    def _normalise_raw(raw: str | dict) -> str:
        """Normalise a raw citation input to a consistent string."""
        if isinstance(raw, dict):
            src = raw.get("source_id", "")
            art = raw.get("article", "")
            return f"{src}:{art}" if src and art else str(raw)
        return str(raw).strip()
