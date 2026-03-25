"""
AILEX -- LegalReasoner

Design rationale:
  The reasoner takes a structured LegalContext (already cleaned by the context
  builder) and produces a grounded, structured legal analysis.

  Key design decisions:

  1. NO external API calls.
     All reasoning is performed over the retrieved context using token-overlap
     relevance scoring, domain heuristics, and template-based analysis.

  2. Output is structured, not prose.
     The ReasoningResult is a data structure that can be consumed:
       a. Directly by lawyers as a structured brief outline.
       b. By an LLM (via the existing /api/chat endpoint) for prose generation.

  3. Grounded-only citations.
     The reasoner only cites articles that are present in the provided context.
     If insufficient evidence is found, the confidence is degraded and
     evidence_sufficient is set to False.

  4. Query type detection.
     Five query types are detected from the query text:
       - deadline_query    ("plazo para ...", "cuanto tiempo ...")
       - validity_query    ("es valido ...", "procede ...")
       - requirement_query ("requisitos para ...", "que se necesita ...")
       - definition_query  ("que es ...", "que se entiende ...")
       - procedure_query   (default fallback)
     Each type generates slightly different analysis framing.

  5. Evidence quality assessment.
     Confidence is based on:
       - Number of relevant articles found
       - Match type quality (exact > hybrid > lexical/semantic)
       - Domain alignment between query and context
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from legal_engine.action_classifier import ActionClassification
from legal_engine.context_builder import LegalArticleChunk, LegalContext


# ---------------------------------------------------------------------------
# Query type vocabulary
# ---------------------------------------------------------------------------

_DEADLINE_TERMS: frozenset[str] = frozenset([
    "plazo", "dias", "tiempo", "vence", "vencimiento", "termino", "cuando",
    "cuanto", "limite", "fecha", "prescripcion", "caducidad",
])

_VALIDITY_TERMS: frozenset[str] = frozenset([
    "valido", "valida", "procede", "corresponde", "admite", "admisible",
    "nulo", "nula", "invalido", "viable", "posible",
])

_REQUIREMENT_TERMS: frozenset[str] = frozenset([
    "requisito", "requisitos", "necesita", "necesario", "exige", "exigencia",
    "condicion", "presupuesto", "requiere",
])

_DEFINITION_TERMS: frozenset[str] = frozenset([
    "que es", "que significa", "que se entiende", "definicion", "concepto",
    "como se define", "que implica",
])

# Stop words for relevance scoring
_STOP: frozenset[str] = frozenset([
    "de", "la", "el", "en", "que", "y", "a", "los", "se", "del",
    "las", "un", "una", "su", "con", "por", "para", "es", "al",
    "o", "no", "lo", "le", "si", "como", "al", "ante", "sin",
])

# Confidence thresholds
_HIGH_CONF_THRESHOLD   = 0.75
_MEDIUM_CONF_THRESHOLD = 0.45

_LEGAL_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("divorcio", "disolucion del matrimonio", "disolucion del vinculo", "disolucion del vinculo matrimonial"),
    ("alimentos", "cuota alimentaria", "obligacion alimentaria"),
    ("cuidado personal", "tenencia", "guarda"),
    ("regimen comunicacional", "regimen de comunicacion", "contacto con los hijos", "visitas"),
    ("compensacion economica", "indemnizacion por desequilibrio"),
    ("sociedad conyugal", "comunidad de ganancias", "gananciales"),
)

_QUERY_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "deadline_query": ("procedural",),
    "requirement_query": ("procedural", "civil"),
    "validity_query": ("civil", "procedural"),
    "definition_query": ("civil", "procedural", "constitutional"),
    "procedure_query": ("procedural", "civil"),
}


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

@dataclass
class NormativeGrounding:
    """
    A single normative article and why it is relevant to the query.

    Attributes:
        source_id:      Corpus source identifier.
        article:        Article number.
        label:          Human-readable article label.
        texto:          Full article text.
        relevance_note: One-line explanation of relevance to the query.
        score:          Relevance score (0--1, computed by the reasoner).
    """
    source_id:      str
    article:        str
    label:          str
    texto:          str
    relevance_note: str
    score:          float

    def citation(self) -> str:
        """Short citation string usable in reasoning text."""
        _LABELS = {
            "cpcc_jujuy":             "CPCC Jujuy",
            "constitucion_jujuy":     "Const. Jujuy",
            "constitucion_nacional":  "Const. Nacional",
            "codigo_civil_comercial": "CCyC",
            "lct_20744":              "LCT",
        }
        src = _LABELS.get(self.source_id, self.source_id)
        return f"Art. {self.article} {src}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id":      self.source_id,
            "article":        self.article,
            "label":          self.label,
            "texto":          self.texto,
            "relevance_note": self.relevance_note,
            "score":          self.score,
            "citation":       self.citation(),
        }


@dataclass
class ReasoningResult:
    """
    Structured output of LegalReasoner.reason().

    This is the primary output consumed by HallucinationGuard,
    ProceduralStrategy, ArgumentGenerator, and the frontend.

    Attributes:
        query:               Original query.
        query_type:          Detected query type (deadline/validity/etc.).
        short_answer:        Concise initial answer (template-based).
        normative_grounds:   Ranked list of relevant normative groundings.
        applied_analysis:    Structured analysis text citing grounded norms.
        limitations:         List of known limitations or gaps.
        citations_used:      List of citation strings (e.g. "Art. 34 CPCC Jujuy").
        confidence:          "high" | "medium" | "low"
        confidence_score:    Float 0--1 for programmatic use.
        evidence_sufficient: False when fewer than 2 relevant norms were found.
        domain:              Legal domain of the analysis.
        jurisdiction:        Target jurisdiction.
        warnings:            Non-fatal issues.
    """
    query:               str
    query_type:          str
    short_answer:        str
    normative_grounds:   list[NormativeGrounding]
    applied_analysis:    str
    limitations:         list[str]
    citations_used:      list[str]
    confidence:          str
    confidence_score:    float
    evidence_sufficient: bool
    domain:              str
    jurisdiction:        str
    warnings:            list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query":               self.query,
            "query_type":          self.query_type,
            "short_answer":        self.short_answer,
            "normative_grounds":   [g.to_dict() for g in self.normative_grounds],
            "normative_foundations": [g.to_dict() for g in self.normative_grounds],
            "applied_analysis":    self.applied_analysis,
            "case_analysis":       self.applied_analysis,
            "limitations":         self.limitations,
            "citations_used":      self.citations_used,
            "confidence":          self.confidence,
            "confidence_score":    self.confidence_score,
            "evidence_sufficient": self.evidence_sufficient,
            "domain":              self.domain,
            "jurisdiction":        self.jurisdiction,
            "warnings":            self.warnings,
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LegalReasoner:
    """
    Produces a structured, grounded legal analysis from a LegalContext.

    The reasoner does not invent norms.  Every citation in the output refers
    to an article that appears in the provided context.

    Usage::

        reasoner = LegalReasoner()
        result   = reasoner.reason(
            query=      "plazo para contestar demanda",
            context=    legal_context,
            jurisdiction="jujuy",
        )
        # result.citations_used contains only articles from context
        # result.confidence is "high" / "medium" / "low"
    """

    def __init__(
        self,
        min_relevant_norms:  int   = 1,
        top_norms_limit:     int   = 5,
        relevance_threshold: float = 0.05,
    ) -> None:
        """
        Args:
            min_relevant_norms:  Minimum norms needed for "evidence_sufficient".
            top_norms_limit:     Maximum normative grounds included in output.
            relevance_threshold: Minimum relevance score to include a norm.
        """
        self._min_norms    = min_relevant_norms
        self._top_limit    = top_norms_limit
        self._rel_thresh   = relevance_threshold

    # ---- Coercion ---------------------------------------------------------

    @staticmethod
    def _coerce_context(context: Any) -> LegalContext | None:
        """Accept either a LegalContext object or an equivalent plain dict."""
        if context is None or isinstance(context, LegalContext):
            return context
        if isinstance(context, dict):
            norms_raw = context.get("applicable_norms") or []
            norms = [
                LegalArticleChunk.from_dict(n) if isinstance(n, dict) else n
                for n in norms_raw
            ]
            return LegalContext(
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
        return None

    # ---- Public API -------------------------------------------------------

    def reason(
        self,
        query:        str,
        context:      Any,
        jurisdiction: str | None = None,
        forum:        str | None = None,
        classification: ActionClassification | dict[str, Any] | None = None,
    ) -> ReasoningResult:
        """
        Produce a structured legal analysis grounded in the provided context.

        Args:
            query:        User's legal query.
            context:      LegalContext object or equivalent dict.
            jurisdiction: Override jurisdiction (falls back to context.jurisdiction).
            forum:        Optional forum/court hint.

        Returns:
            ReasoningResult -- always well-formed, even on empty context.
        """
        context = self._coerce_context(context)

        warnings:     list[str] = []
        query         = (query or "").strip()
        jurisdiction  = (jurisdiction or (context.jurisdiction if context else "jujuy")).strip()

        if not query:
            warnings.append("Empty query provided to LegalReasoner.")

        if context is None or context.is_empty():
            return self._empty_result(query, jurisdiction, warnings + ["Context is empty."])

        classification_obj = self._coerce_classification(classification)

        # Detect query type
        query_type = self._classify_query(query)

        # Score and rank relevant norms
        scored = self._score_norms(query, context.applicable_norms, query_type)

        # Filter by threshold and cap
        grounds = [
            self._make_grounding(chunk, score, query, query_type)
            for chunk, score in scored
            if score >= self._rel_thresh
        ][: self._top_limit]

        # Assess evidence quality
        evidence_sufficient = len(grounds) >= self._min_norms
        confidence_score    = self._compute_confidence(grounds, context, query_type)
        confidence_label    = self._confidence_label(confidence_score)

        # Build outputs
        short_answer    = self._build_short_answer(
            query, query_type, grounds, jurisdiction, classification_obj
        )
        analysis        = self._build_analysis(
            query, query_type, grounds, jurisdiction, classification_obj
        )
        limitations     = self._build_limitations(grounds, evidence_sufficient, context)
        citations_used  = [g.citation() for g in grounds]

        return ReasoningResult(
            query=               query,
            query_type=          query_type,
            short_answer=        short_answer,
            normative_grounds=   grounds,
            applied_analysis=    analysis,
            limitations=         limitations,
            citations_used=      citations_used,
            confidence=          confidence_label,
            confidence_score=    round(confidence_score, 4),
            evidence_sufficient= evidence_sufficient,
            domain=              classification_obj.domain if classification_obj else context.domain,
            jurisdiction=        jurisdiction,
            warnings=            warnings,
        )

    # ---- Query classification --------------------------------------------

    @staticmethod
    def _classify_query(query: str) -> str:
        """Detect the query type from its vocabulary."""
        norm_q = _normalise(query)
        tokens = set(norm_q.split())

        # Explicit "what is" phrasing overrides domain terms
        if any(phrase in norm_q for phrase in ("que es", "que significa", "como se define")):
            return "definition_query"
        if tokens & _DEADLINE_TERMS:
            return "deadline_query"
        if tokens & _VALIDITY_TERMS:
            return "validity_query"
        if tokens & _REQUIREMENT_TERMS:
            return "requirement_query"
        return "procedure_query"

    # ---- Norm scoring ----------------------------------------------------

    def _score_norms(
        self,
        query:       str,
        norms:       list[LegalArticleChunk],
        query_type:  str,
    ) -> list[tuple[LegalArticleChunk, float]]:
        """
        Score each norm's relevance to the query using token overlap
        weighted by retrieval score and match type.
        """
        query_profile = _semantic_profile(query)
        query_tokens = query_profile["tokens"]
        if not query_tokens:
            # Fallback: return all norms at base retrieval score
            return sorted(
                [(c, c.score) for c in norms],
                key=lambda t: t[1], reverse=True,
            )

        scored: list[tuple[LegalArticleChunk, float]] = []
        for chunk in norms:
            doc_profile = _semantic_profile(f"{chunk.titulo} {chunk.texto}")
            doc_tokens = doc_profile["tokens"]
            overlap = len(query_tokens & doc_tokens)
            lexical_overlap = overlap / max(len(query_tokens), 1)
            jaccard = overlap / max(len(query_tokens | doc_tokens), 1)
            semantic_overlap = len(query_profile["concepts"] & doc_profile["concepts"]) / max(
                len(query_profile["concepts"]) or 1, 1
            )
            expanded_overlap = len(query_profile["expanded_tokens"] & doc_profile["expanded_tokens"]) / max(
                len(query_profile["expanded_tokens"]), 1
            )
            bigram_overlap = len(query_profile["bigrams"] & doc_profile["bigrams"]) / max(
                len(query_profile["bigrams"]) or 1, 1
            )
            lexical_signal = min((lexical_overlap * 0.65) + (jaccard * 0.35), 1.0)
            semantic_signal = min((semantic_overlap * 0.65) + (expanded_overlap * 0.35), 1.0)

            match_bonus = {"exact": 0.20, "hybrid": 0.10, "lexical": 0.05}.get(
                chunk.match_type, 0.0
            )
            domain_bonus = 0.04 if chunk.domain in _QUERY_DOMAIN_HINTS.get(query_type, ()) else 0.0
            phrase_bonus = min(bigram_overlap * 0.08, 0.08)
            combined = (
                (chunk.score * 0.45)
                + (lexical_signal * 0.24)
                + (semantic_signal * 0.21)
                + domain_bonus
                + phrase_bonus
                + match_bonus
            )
            scored.append((chunk, min(combined, 1.0)))

        return sorted(scored, key=lambda t: t[1], reverse=True)

    # ---- Grounding construction ------------------------------------------

    @staticmethod
    def _make_grounding(
        chunk:      LegalArticleChunk,
        score:      float,
        query:      str,
        query_type: str,
    ) -> NormativeGrounding:
        """Build a NormativeGrounding with a template relevance note."""
        _NOTE_TEMPLATES = {
            "deadline_query":     "Regula plazos y terminos relevantes para la consulta.",
            "validity_query":     "Establece condiciones de validez aplicables al caso.",
            "requirement_query":  "Define requisitos y presupuestos procesales o sustanciales.",
            "definition_query":   "Contiene definiciones o conceptos normativos pertinentes.",
            "procedure_query":    "Regula el procedimiento aplicable a la situacion consultada.",
        }
        relevance_note = _NOTE_TEMPLATES.get(query_type, "Norma potencialmente aplicable.")

        return NormativeGrounding(
            source_id=      chunk.source_id,
            article=        chunk.article,
            label=          chunk.label,
            texto=          chunk.texto,
            relevance_note= _specific_relevance_note(chunk, relevance_note),
            score=          round(score, 4),
        )

    # ---- Confidence assessment -------------------------------------------

    @staticmethod
    def _compute_confidence(
        grounds:    list[NormativeGrounding],
        context:    LegalContext,
        query_type: str,
    ) -> float:
        """
        Compute a 0--1 confidence score based on evidence quality.

        Factors:
          - Number of relevant norms found (more = higher)
          - Average relevance score of top norms
          - Whether context domain matches query type domain
          - Presence of exact/hybrid matches
        """
        if not grounds:
            return 0.10

        n = len(grounds)
        avg_score  = sum(g.score for g in grounds) / n
        norm_count_factor = min(n / 4.0, 1.0)    # saturates at 4 norms

        # Check norms come from the right chunk type
        high_quality = sum(
            1 for g in grounds
            if context.applicable_norms and any(
                c.source_id == g.source_id and c.article == g.article
                and c.match_type in ("exact", "hybrid")
                for c in context.applicable_norms
            )
        )
        quality_factor = min(high_quality / max(n, 1), 1.0)

        confidence = (avg_score * 0.50) + (norm_count_factor * 0.30) + (quality_factor * 0.20)
        return round(min(max(confidence, 0.05), 0.98), 4)

    @staticmethod
    def _confidence_label(score: float) -> str:
        if score >= _HIGH_CONF_THRESHOLD:
            return "high"
        if score >= _MEDIUM_CONF_THRESHOLD:
            return "medium"
        return "low"

    # ---- Text construction -----------------------------------------------

    @staticmethod
    def _build_short_answer(
        query:        str,
        query_type:   str,
        grounds:      list[NormativeGrounding],
        jurisdiction: str,
        classification: ActionClassification | None = None,
    ) -> str:
        """Build a concise initial answer sentence."""
        n = len(grounds)
        jur = jurisdiction.capitalize()

        if not grounds:
            return (
                f"La consulta '{query}' no pudo ser respondida con la normativa "
                f"disponible en {jur}. Se recomienda ampliar la busqueda o consultar "
                "con un abogado especializado."
            )

        citations = " | ".join(g.citation() for g in grounds[:3])
        if classification and classification.action_slug == "divorcio_mutuo_acuerdo":
            return (
                "La consulta encuadra, en principio, como divorcio a peticion conjunta "
                f"en el fuero de familia. Normativa relevante: {citations}."
            )
        if classification and classification.action_slug == "divorcio_unilateral":
            return (
                "La consulta encuadra, en principio, como divorcio unilateral en el "
                f"fuero de familia. Normativa relevante: {citations}."
            )
        if classification and classification.action_slug == "alimentos_hijos":
            return (
                "La consulta encuadra, en principio, como reclamo de alimentos a favor "
                f"de hijos en el fuero de familia. Normativa relevante: {citations}."
            )
        if classification and classification.action_slug == "sucesion_ab_intestato":
            return (
                "La consulta encuadra, en principio, como apertura de sucesion ab "
                f"intestato en el fuero civil. Normativa relevante: {citations}."
            )

        _INTRO = {
            "deadline_query":    f"Se encontraron {n} norma(s) que regulan plazos aplicables. Normativa relevante: {citations}.",
            "validity_query":    f"Se encontraron {n} norma(s) sobre condiciones de validez. Normativa relevante: {citations}.",
            "requirement_query": f"Se encontraron {n} norma(s) que definen requisitos aplicables. Normativa relevante: {citations}.",
            "definition_query":  f"Se encontraron {n} norma(s) con definiciones relevantes. Normativa relevante: {citations}.",
            "procedure_query":   f"Se identificaron {n} norma(s) procesales aplicables en {jur}. Normativa relevante: {citations}.",
        }
        return _INTRO.get(query_type, f"Normativa aplicable ({jur}): {citations}.")

    @staticmethod
    def _build_analysis(
        query:        str,
        query_type:   str,
        grounds:      list[NormativeGrounding],
        jurisdiction: str,
        classification: ActionClassification | None = None,
    ) -> str:
        """
        Build a structured analysis text that cites each grounding.

        The text is formatted for human readability and for downstream
        LLM enrichment.
        """
        if not grounds:
            return (
                "ANALISIS: No se encontro normativa suficiente para analizar "
                "la consulta con el corpus disponible."
            )

        lines = [
            f"ANALISIS JURIDICO -- {jurisdiction.upper()}",
            f"Consulta: {query}",
        ]
        if classification:
            lines.append(
                "Clasificacion: "
                f"{classification.action_slug} | fuero {classification.forum} | "
                f"proceso {classification.process_type}"
            )
        lines.append("")

        for i, g in enumerate(grounds, 1):
            lines.append(f"{i}. {g.citation()}")
            lines.append(f"   Relevancia: {g.relevance_note}")
            # Include first 300 chars of article text as evidence
            excerpt = g.texto[:300].strip()
            if len(g.texto) > 300:
                excerpt += "..."
            lines.append(f"   Texto normativo: \"{excerpt}\"")
            lines.append("")

        lines.append(
            "CONSIDERACION: El analisis precedente se basa exclusivamente en "
            "normativa recuperada del corpus interno de AILEX. Para aplicacion "
            "concreta, verificar vigencia y circunstancias especificas del caso."
        )
        return "\n".join(lines)

    @staticmethod
    def _build_limitations(
        grounds:             list[NormativeGrounding],
        evidence_sufficient: bool,
        context:             LegalContext,
    ) -> list[str]:
        """Build a list of known limitations for this analysis."""
        limitations: list[str] = []

        if not evidence_sufficient:
            limitations.append(
                "Evidencia insuficiente: se encontraron menos de las normas minimas "
                "recomendadas. El analisis puede estar incompleto."
            )

        if context.truncated:
            limitations.append(
                "El contexto fue truncado por limite de presupuesto. "
                "Pueden existir normas relevantes no incluidas en el analisis."
            )

        if len(set(g.source_id for g in grounds)) == 1:
            limitations.append(
                "Todas las normas provienen de una sola fuente. "
                "Verificar si existen normas complementarias en otras fuentes."
            )

        if not grounds:
            limitations.append(
                "No se encontraron normas relevantes. "
                "Ampliar busqueda o consultar con abogado especializado."
            )

        return limitations

    # ---- Empty result ----------------------------------------------------

    @staticmethod
    def _empty_result(
        query:        str,
        jurisdiction: str,
        warnings:     list[str],
    ) -> ReasoningResult:
        return ReasoningResult(
            query=               query,
            query_type=          "procedure_query",
            short_answer=        "No se encontro normativa aplicable para esta consulta.",
            normative_grounds=   [],
            applied_analysis=    "ANALISIS: Contexto vacio -- sin normativa disponible.",
            limitations=         ["Contexto de recuperacion vacio."],
            citations_used=      [],
            confidence=          "low",
            confidence_score=    0.05,
            evidence_sufficient= False,
            domain=              "unknown",
            jurisdiction=        jurisdiction,
            warnings=            warnings,
        )

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


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    nfkd   = unicodedata.normalize("NFKD", text)
    no_acc = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return " ".join(no_acc.casefold().split())


def _tokenise(text: str) -> list[str]:
    """Split into tokens, removing stop words and short tokens."""
    return [t for t in re.findall(r"[a-z0-9]+", text) if t not in _STOP and len(t) >= 2]


def _specific_relevance_note(
    chunk: LegalArticleChunk,
    fallback: str,
) -> str:
    specific = {
        ("codigo_civil_comercial", "437"): "Define la legitimacion del divorcio a peticion de ambos o de uno de los conyuges.",
        ("codigo_civil_comercial", "438"): "Regula los requisitos y el procedimiento del divorcio, incluida la propuesta reguladora.",
        ("codigo_civil_comercial", "439"): "Establece el contenido minimo del convenio regulador.",
        ("codigo_civil_comercial", "440"): "Regula la eficacia y modificacion del convenio regulador.",
        ("codigo_civil_comercial", "441"): "Regula la compensacion economica entre conyuges ante desequilibrio manifiesto.",
        ("codigo_civil_comercial", "717"): "Determina la competencia judicial en procesos de divorcio, incluida la presentacion conjunta.",
        ("codigo_civil_comercial", "721"): "Preve medidas provisionales personales durante el proceso de divorcio.",
        ("codigo_civil_comercial", "658"): "Establece la regla general de alimentos a favor de hijos dentro de la responsabilidad parental.",
        ("codigo_civil_comercial", "659"): "Delimita el contenido de la obligacion alimentaria respecto del hijo.",
        ("codigo_civil_comercial", "660"): "Reconoce el valor economico de las tareas de cuidado del progenitor conviviente.",
        ("codigo_civil_comercial", "661"): "Precisa la legitimacion para reclamar alimentos a favor del hijo.",
        ("codigo_civil_comercial", "662"): "Habilita la fijacion judicial del monto y modalidad de la cuota alimentaria.",
        ("codigo_civil_comercial", "663"): "Preve medidas para asegurar el cumplimiento de la cuota alimentaria.",
        ("codigo_civil_comercial", "664"): "Relaciona alimentos con convivencia y distribucion de cargas parentales.",
        ("codigo_civil_comercial", "669"): "Regula alimentos impagos y retroactividad del credito alimentario.",
        ("codigo_civil_comercial", "2277"): "Ubica la apertura de la sucesion en la muerte del causante y la transmision hereditaria.",
        ("codigo_civil_comercial", "2280"): "Determina quienes estan legitimados para promover la sucesion.",
        ("codigo_civil_comercial", "2288"): "Regula aceptacion o renuncia de la herencia y la situacion del heredero.",
        ("codigo_civil_comercial", "2335"): "Delimita el objeto del proceso sucesorio y la administracion del acervo.",
        ("codigo_civil_comercial", "2336"): "Fija la competencia territorial del proceso sucesorio.",
        ("codigo_civil_comercial", "2340"): "Aclara el alcance practico de la investidura hereditaria frente a terceros.",
        ("codigo_civil_comercial", "2424"): "Regula el orden sucesorio de los descendientes.",
        ("codigo_civil_comercial", "2431"): "Regula la concurrencia y derechos del conyuge superstite.",
    }
    return specific.get((chunk.source_id, chunk.article), fallback)


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


def _semantic_profile(text: str) -> dict[str, set[str]]:
    normalized = _normalise(text)
    tokens = set(_tokenise(normalized))
    concepts: set[str] = set()
    expanded_tokens = set(tokens)

    for canonical, group in ((group[0], group) for group in _LEGAL_SYNONYM_GROUPS):
        if any(_contains_phrase(normalized, phrase) for phrase in group):
            concepts.add(canonical)
            expanded_tokens.update(_tokenise(canonical))
            for phrase in group:
                expanded_tokens.update(_tokenise(phrase))

    bigrams = {
        " ".join(pair)
        for pair in zip(normalized.split(), normalized.split()[1:])
        if len(pair[0]) >= 2 and len(pair[1]) >= 2
    }
    return {
        "tokens": tokens,
        "expanded_tokens": expanded_tokens,
        "concepts": concepts,
        "bigrams": bigrams,
    }
