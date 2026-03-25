"""
AILEX -- HallucinationGuard

Design rationale:
  This is the safety layer that runs after reasoning output is produced.
  It applies rule-based detection to catch the most common failure modes
  in AI-assisted legal systems, without calling any external service.

  Five detection rules (each independent, stackable):

    1. UNSUPPORTED_CITATION
       Finds article number references in the text that do not appear in
       the context.  If a sentence cites "Art. 99999" but that article was
       never retrieved, the claim is unsupported.

    2. ABSOLUTE_LANGUAGE
       Flags categorical language ("siempre", "nunca", "definitivamente",
       "es claro que", etc.) which overstates certainty in legal contexts
       where exceptions and jurisdictional variation always exist.

    3. JURISDICTION_MIXING
       Detects when text mentions multiple jurisdictions (e.g. Jujuy AND
       nacional) without an explicit caveat.  Mixing rules from different
       jurisdictions silently is a common and dangerous error.

    4. OVERCONCLUSION
       Flags strong conclusions ("por lo tanto procede", "se concluye que",
       "definitivamente corresponde", etc.) when the evidence confidence
       is below a threshold.  High-certainty language needs high-quality
       evidence.

    5. UNKNOWN_SOURCE
       Detects references to source names that are not part of the known
       corpus (e.g. "el Codigo de Comercio dice que..." when that source
       is not in the system).

  Output:
    GuardResult with:
      - is_safe: True when no HIGH-severity flag is found
      - flags: list of HallucinationFlag (type, severity, excerpt, suggestion)
      - confidence_adjustment: multiplicative factor to apply to confidence
      - warnings: informational messages
      - safe_mode_rewrite: optional simplified re-statement of the text
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Severity:
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


@dataclass
class HallucinationFlag:
    """A single detected hallucination risk."""
    flag_type:  str       # rule name (e.g. "absolute_language")
    severity:   str       # "low" | "medium" | "high"
    excerpt:    str       # the problematic text fragment
    suggestion: str       # what to do about it

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_type":  self.flag_type,
            "severity":   self.severity,
            "excerpt":    self.excerpt,
            "suggestion": self.suggestion,
        }


@dataclass
class GuardResult:
    """
    Output of HallucinationGuard.check().

    Attributes:
        is_safe:               True when no HIGH-severity flag is present.
        flags:                 All detected hallucination flags.
        confidence_adjustment: Multiply original confidence by this value.
                               1.0 = no adjustment, <1.0 = degraded.
        warnings:              Non-fatal informational messages.
        safe_mode_rewrite:     Optional rephrased text when high risk is found.
    """
    is_safe:               bool
    flags:                 list[HallucinationFlag]
    confidence_adjustment: float
    warnings:              list[str]
    safe_mode_rewrite:     str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_safe":               self.is_safe,
            "flags":                 [f.to_dict() for f in self.flags],
            "confidence_adjustment": self.confidence_adjustment,
            "warnings":              self.warnings,
            "safe_mode_rewrite":     self.safe_mode_rewrite,
        }

    def high_flags(self) -> list[HallucinationFlag]:
        return [f for f in self.flags if f.severity == Severity.HIGH]

    def medium_flags(self) -> list[HallucinationFlag]:
        return [f for f in self.flags if f.severity == Severity.MEDIUM]


# ---------------------------------------------------------------------------
# Detection vocabulary
# ---------------------------------------------------------------------------

# Absolute / overconfident language patterns (Spanish legal context)
_ABSOLUTE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bsiempre\b",                 re.I), "siempre"),
    (re.compile(r"\bnunca\b",                   re.I), "nunca"),
    (re.compile(r"\bdefinitivamente\b",         re.I), "definitivamente"),
    (re.compile(r"\bes\s+claro\s+que\b",        re.I), "es claro que"),
    (re.compile(r"\bsin\s+lugar\s+a\s+dudas?\b",re.I), "sin lugar a dudas"),
    (re.compile(r"\bcon\s+certeza\b",           re.I), "con certeza"),
    (re.compile(r"\bin(?:cuestionable|dudable)mente\b", re.I), "indudablemente"),
    (re.compile(r"\bobviamente\b",              re.I), "obviamente"),
    (re.compile(r"\bevidente(?:mente)?\b",      re.I), "evidentemente"),
    (re.compile(r"\bes\s+evidente\b",           re.I), "es evidente"),
]

# Overconclusion patterns (strong conclusions)
_OVERCONCLUSION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpor\s+lo\s+tanto\s+(?:corresponde|procede)\b", re.I),
     "por lo tanto corresponde/procede"),
    (re.compile(r"\bse\s+concluye\s+que\b",                        re.I), "se concluye que"),
    (re.compile(r"\bdefinitivamente\s+corresponde\b",              re.I), "definitivamente corresponde"),
    (re.compile(r"\bqueda\s+demostrado\b",                         re.I), "queda demostrado"),
    (re.compile(r"\bno\s+cabe\s+duda\b",                           re.I), "no cabe duda"),
    (re.compile(r"\bes\s+(?:absolutamente\s+)?claro\b",            re.I), "es absolutamente claro"),
]

# Known source names (to detect references to unknown sources)
_KNOWN_SOURCE_NAMES: list[re.Pattern] = [
    re.compile(r"\bcpcc(?:\s+jujuy)?\b",               re.I),
    re.compile(r"\bcodigo\s+procesal\b",               re.I),
    re.compile(r"\bconstitucion\s+(?:nacional|jujuy|provincial)\b", re.I),
    re.compile(r"\bcccn\b|\bccyc\b|\bcodigo\s+civil\b",re.I),
    re.compile(r"\blct\b|\bley\s+20\.?744\b",          re.I),
    re.compile(r"\bcpccn\b",                           re.I),   # national code, tolerated
]

# Sources that trigger "unknown source" if found (common mistakes)
_UNKNOWN_SOURCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bcodigo\s+de\s+comercio\b",        re.I), "Codigo de Comercio"),
    (re.compile(r"\bley\s+de\s+sociedades\b",          re.I), "Ley de Sociedades"),
    (re.compile(r"\bcodigo\s+penal\b",                 re.I), "Codigo Penal"),
    (re.compile(r"\bcodigo\s+de\s+mineria\b",          re.I), "Codigo de Mineria"),
]

# Jurisdiction name patterns for mixing detection
_JURISDICTION_PATTERNS: dict[str, re.Pattern] = {
    "jujuy":    re.compile(r"\bjujuy\b|\bprovincial\b|\bjujuya\b",  re.I),
    "nacional": re.compile(r"\bnacional\b|\bfederal\b|\bnacion\b",  re.I),
}

# Article number extraction from arbitrary text
_ART_IN_TEXT = re.compile(
    r"\barts?\.?\s*(\d+(?:\s*(?:bis|ter|quater))?)\b"
    r"|\barticulos?\s+(\d+(?:\s*(?:bis|ter|quater))?)\b"
    r"|\bart[i\xed]culos?\s+(\d+(?:\s*(?:bis|ter|quater))?)\b",
    re.I,
)

# Caveat patterns: text that explicitly acknowledges uncertainty
_CAVEAT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bsin\s+perjuicio\b",         re.I),
    re.compile(r"\bsalvo\s+(?:que|disposicion)",re.I),
    re.compile(r"\bcon\s+las\s+salvedades\b",  re.I),
    re.compile(r"\bverificar\b",               re.I),
    re.compile(r"\bconsultar\b",               re.I),
    re.compile(r"\bpodria\b|\bpuede\s+ser\b",  re.I),
    re.compile(r"\bsujeto\s+a\b",              re.I),
]


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class HallucinationGuard:
    """
    Rule-based safety filter for AI-generated legal reasoning output.

    Designed to be called after LegalReasoner produces output, and before
    the result reaches the end user.

    Usage::

        guard = HallucinationGuard()
        result = guard.check(
            text=reasoning_result.applied_analysis,
            context=legal_context,
            base_confidence=0.75,
        )
        if not result.is_safe:
            print("HIGH risk flags:", [f.excerpt for f in result.high_flags()])
    """

    def __init__(
        self,
        absolute_language_severity: str = Severity.MEDIUM,
        jurisdiction_mixing_severity: str = Severity.MEDIUM,
        overconclusion_threshold: float = 0.60,
    ) -> None:
        """
        Args:
            absolute_language_severity:   Severity assigned to absolute-language flags.
            jurisdiction_mixing_severity: Severity for jurisdiction-mixing flags.
            overconclusion_threshold:     Confidence below which overconcluding is HIGH.
        """
        self._abs_sev           = absolute_language_severity
        self._jmix_sev          = jurisdiction_mixing_severity
        self._overconc_threshold = overconclusion_threshold

    # ---- Public API -------------------------------------------------------

    def guard(
        self,
        _query:             str  = "",
        context=None,
        reasoning=None,
        **_kwargs: Any,
    ) -> "GuardResult":
        """
        Pipeline adapter.  Called by AilexPipeline as ``guard(query, context,
        reasoning, ...)``.  Extracts ``text`` and ``base_confidence`` from the
        reasoning dict and delegates to :meth:`check`.
        """
        text = ""
        base_confidence = 0.50
        if isinstance(reasoning, dict):
            text = (
                reasoning.get("applied_analysis")
                or reasoning.get("short_answer")
                or ""
            )
            cs = reasoning.get("confidence_score")
            if isinstance(cs, (int, float)):
                base_confidence = float(cs)

        # Coerce context dict -> LegalContext if needed
        legal_ctx = None
        if isinstance(context, dict) and context.get("applicable_norms"):
            from legal_engine.context_builder import LegalArticleChunk, LegalContext
            norms = [
                LegalArticleChunk.from_dict(n) if isinstance(n, dict) else n
                for n in (context.get("applicable_norms") or [])
            ]
            legal_ctx = LegalContext(
                query=             context.get("query", ""),
                jurisdiction=      context.get("jurisdiction", "jujuy"),
                domain=            context.get("domain", "unknown"),
                applicable_norms=  norms,
                total_chars=       context.get("total_chars", 0),
                truncated=         context.get("truncated", False),
                source_ids_used=   context.get("source_ids_used") or [],
                context_text=      context.get("context_text", ""),
                formatted_sections=context.get("formatted_sections") or {},
                warnings=          context.get("warnings") or [],
            )
        return self.check(text=text, context=legal_ctx, base_confidence=base_confidence)

    def check(
        self,
        text:             str,
        context=None,     # LegalContext | None
        base_confidence:  float = 0.70,
    ) -> GuardResult:
        """
        Run all hallucination checks on a text produced by the reasoning layer.

        Args:
            text:            Text to check (e.g. reasoning analysis or short answer).
            context:         LegalContext used to build the reasoning.
                             Used for citation verification.
            base_confidence: Confidence score of the reasoning result (0--1).

        Returns:
            GuardResult with flags, safety verdict, and confidence adjustment.
        """
        warnings: list[str] = []
        flags:    list[HallucinationFlag] = []

        text = (text or "").strip()
        if not text:
            warnings.append("Empty text provided to HallucinationGuard.")
            return GuardResult(
                is_safe=True, flags=[], confidence_adjustment=1.0,
                warnings=warnings, safe_mode_rewrite=None,
            )

        # Build context keys for citation verification
        context_keys: set[tuple[str, str]] = set()
        context_source_ids: set[str] = set()
        if context is not None:
            try:
                context_keys       = context.citation_keys()
                context_source_ids = set(context.source_ids_used)
            except AttributeError:
                warnings.append("context has no citation_keys() -- citation check skipped.")

        # Run all checks
        flags.extend(self._check_unsupported_citations(text, context_keys))
        flags.extend(self._check_absolute_language(text))
        flags.extend(self._check_jurisdiction_mixing(text, context))
        flags.extend(self._check_overconclusion(text, base_confidence))
        flags.extend(self._check_unknown_sources(text))

        # Aggregate result
        has_high    = any(f.severity == Severity.HIGH   for f in flags)
        has_medium  = any(f.severity == Severity.MEDIUM for f in flags)
        is_safe     = not has_high

        # Confidence adjustment: each HIGH flag -0.15, each MEDIUM flag -0.05
        adj = 1.0
        for f in flags:
            if f.severity == Severity.HIGH:
                adj -= 0.15
            elif f.severity == Severity.MEDIUM:
                adj -= 0.05
        adj = max(0.05, round(adj, 4))

        safe_rewrite = None
        if has_high:
            safe_rewrite = self._produce_safe_rewrite(text, flags)

        return GuardResult(
            is_safe=               is_safe,
            flags=                 flags,
            confidence_adjustment= adj,
            warnings=              warnings,
            safe_mode_rewrite=     safe_rewrite,
        )

    # ---- Detection rules --------------------------------------------------

    def _check_unsupported_citations(
        self,
        text:         str,
        context_keys: set[tuple[str, str]],
    ) -> list[HallucinationFlag]:
        """
        Flag article number mentions that are not backed by the context.

        Only fires when there IS a context (non-empty context_keys).
        If no context is available, we cannot determine what's unsupported.
        """
        if not context_keys:
            return []

        flags: list[HallucinationFlag] = []
        context_articles = {art for _, art in context_keys}

        for m in _ART_IN_TEXT.finditer(text):
            num = next(g for g in m.groups() if g is not None)
            num = re.sub(r"\s+", "", num.strip())
            if num not in context_articles:
                excerpt = text[max(0, m.start() - 20) : m.end() + 20].strip()
                flags.append(HallucinationFlag(
                    flag_type="unsupported_citation",
                    severity=Severity.HIGH,
                    excerpt=excerpt,
                    suggestion=(
                        f"El Art. {num} no fue recuperado en el contexto. "
                        "Verificar si es correcto o eliminar la referencia."
                    ),
                ))
        return flags

    def _check_absolute_language(self, text: str) -> list[HallucinationFlag]:
        """Flag categorical language that overstates legal certainty."""
        flags: list[HallucinationFlag] = []
        seen:  set[str] = set()
        for pattern, label in _ABSOLUTE_PATTERNS:
            m = pattern.search(text)
            if m and label not in seen:
                seen.add(label)
                excerpt = text[max(0, m.start() - 15) : m.end() + 15].strip()
                flags.append(HallucinationFlag(
                    flag_type="absolute_language",
                    severity=self._abs_sev,
                    excerpt=excerpt,
                    suggestion=(
                        f"Lenguaje absoluto detectado: '{label}'. "
                        "En contexto juridico, prefer 'en principio', 'en general' "
                        "o 'salvo disposicion en contrario'."
                    ),
                ))
        return flags

    def _check_jurisdiction_mixing(
        self,
        text:    str,
        context,
    ) -> list[HallucinationFlag]:
        """
        Flag texts that reference multiple jurisdictions without a caveat.

        Only flags if the context is restricted to one jurisdiction but
        the text references another without an explicit caveat phrase.
        """
        flags: list[HallucinationFlag] = []

        jurisdictions_found = {
            j for j, pat in _JURISDICTION_PATTERNS.items()
            if pat.search(text)
        }

        if len(jurisdictions_found) < 2:
            return []

        # Check whether the text includes a caveat acknowledging the mixing
        has_caveat = any(p.search(text) for p in _CAVEAT_PATTERNS)
        if has_caveat:
            return []

        # Determine expected jurisdiction from context
        expected_jur: str | None = None
        if context is not None:
            try:
                expected_jur = context.jurisdiction
            except AttributeError:
                pass

        if expected_jur and expected_jur in jurisdictions_found:
            other = jurisdictions_found - {expected_jur}
            flags.append(HallucinationFlag(
                flag_type="jurisdiction_mixing",
                severity=self._jmix_sev,
                excerpt=f"Jurisdicciones detectadas: {sorted(jurisdictions_found)}",
                suggestion=(
                    f"El contexto es de jurisdiccion '{expected_jur}' pero el texto "
                    f"tambien menciona {other}. Aclarar que la norma "
                    "de otra jurisdiccion es referencial y puede diferir."
                ),
            ))
        elif len(jurisdictions_found) >= 2:
            flags.append(HallucinationFlag(
                flag_type="jurisdiction_mixing",
                severity=self._jmix_sev,
                excerpt=f"Jurisdicciones detectadas: {sorted(jurisdictions_found)}",
                suggestion=(
                    "Se mezclan referencias de distintas jurisdicciones. "
                    "Aclarar explicitamente cual norma aplica a este caso."
                ),
            ))
        return flags

    def _check_overconclusion(
        self,
        text:            str,
        base_confidence: float,
    ) -> list[HallucinationFlag]:
        """
        Flag strong conclusory language when the evidence confidence is low.

        High-certainty conclusions require high-quality evidence.
        """
        if base_confidence >= self._overconc_threshold:
            return []

        flags: list[HallucinationFlag] = []
        seen:  set[str] = set()

        for pattern, label in _OVERCONCLUSION_PATTERNS:
            m = pattern.search(text)
            if m and label not in seen:
                seen.add(label)
                excerpt = text[max(0, m.start() - 20) : m.end() + 20].strip()
                flags.append(HallucinationFlag(
                    flag_type="overconclusion",
                    severity=Severity.HIGH,
                    excerpt=excerpt,
                    suggestion=(
                        f"Conclusion categorica ('{label}') con confianza baja "
                        f"({base_confidence:.0%}). Suavizar con 'podria corresponder', "
                        "'en principio', o 'sugiere que'."
                    ),
                ))
        return flags

    def _check_unknown_sources(self, text: str) -> list[HallucinationFlag]:
        """Flag references to sources not in the AILEX corpus."""
        flags: list[HallucinationFlag] = []
        for pattern, label in _UNKNOWN_SOURCE_PATTERNS:
            if pattern.search(text):
                flags.append(HallucinationFlag(
                    flag_type="unknown_source",
                    severity=Severity.HIGH,
                    excerpt=label,
                    suggestion=(
                        f"'{label}' no forma parte del corpus normativo de AILEX. "
                        "Eliminar la referencia o verificar manualmente antes de usar."
                    ),
                ))
        return flags

    # ---- Safe rewrite helper ----------------------------------------------

    @staticmethod
    def _produce_safe_rewrite(text: str, flags: list[HallucinationFlag]) -> str:
        """
        Produce a simplified disclaimer-based rewrite for high-risk texts.

        This is a minimal fallback that strips the most problematic assertions
        and appends a standard caution notice.  It does NOT attempt to rewrite
        legal content semantically.
        """
        rewritten = text

        # Soften absolute language
        for pattern, label in _ABSOLUTE_PATTERNS:
            rewritten = pattern.sub("en principio", rewritten)

        # Soften overconclusion language
        for pattern, label in _OVERCONCLUSION_PATTERNS:
            rewritten = pattern.sub("podria corresponder que", rewritten)

        disclaimer = (
            "\n\n[ADVERTENCIA AILEX] Este analisis contiene indicadores de riesgo "
            "de alucinacion. Se recomienda verificacion por abogado habilitado antes "
            "de utilizar este contenido en un tramite real."
        )
        return rewritten + disclaimer
