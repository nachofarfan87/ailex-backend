"""Structured tag inference for model selection.

Replaces the inline string-matching approach in ailex_pipeline with a
declarative, rule-based system that separates *signal collection* from
*tag inference*.  Each rule is explicit about which signals it consumes,
what markers it looks for, and what tag it emits.

Design goals:
- Precision over coverage (avoid false positives).
- Every rule is inspectable and testable in isolation.
- Easy to extend: add a new TagRule to TAG_RULES and you're done.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Signal collection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TagSignals:
    """Structured signals extracted from the pipeline stages.

    Each field is a normalised, lowercased string ready for matching.
    Lists are already flattened to strings where needed.
    """
    query: str = ""
    action_slug: str = ""
    action_label: str = ""
    main_claim: str = ""
    case_summary: str = ""
    core_dispute: str = ""
    most_vulnerable_point: str = ""
    strategic_notes: str = ""
    facts_text: str = ""
    requirements_text: str = ""
    inferences_text: str = ""
    next_steps_text: str = ""
    recommended_actions_text: str = ""
    evidentiary_needs_text: str = ""


def collect_tag_signals(
    request_query: str,
    classification: dict[str, Any],
    case_structure: dict[str, Any],
    normative_reasoning: dict[str, Any],
    procedural_strategy: dict[str, Any],
    case_theory: dict[str, Any],
    conflict_evidence: dict[str, Any],
) -> TagSignals:
    """Build a TagSignals object from pipeline stage outputs."""

    def _s(value: Any) -> str:
        return str(value or "").strip().lower()

    def _join_list(collection: Any) -> str:
        if not isinstance(collection, list):
            return ""
        return " ".join(_s(item) for item in collection if _s(item))

    return TagSignals(
        query=_s(request_query),
        action_slug=_s(classification.get("action_slug")),
        action_label=_s(classification.get("action_label")),
        main_claim=_s(case_structure.get("main_claim")),
        case_summary=_s(case_structure.get("summary")),
        core_dispute=_s(conflict_evidence.get("core_dispute")),
        most_vulnerable_point=_s(conflict_evidence.get("most_vulnerable_point")),
        strategic_notes=_s(procedural_strategy.get("strategic_notes")),
        facts_text=_join_list(case_structure.get("facts")),
        requirements_text=_join_list(normative_reasoning.get("requirements")),
        inferences_text=_join_list(normative_reasoning.get("inferences")),
        next_steps_text=_join_list(procedural_strategy.get("next_steps")),
        recommended_actions_text=_join_list(case_theory.get("recommended_line_of_action")),
        evidentiary_needs_text=_join_list(case_theory.get("evidentiary_needs")),
    )


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TagRule:
    """A single declarative rule that may emit a tag.

    Attributes:
        tag: The tag to emit when the rule fires.
        markers: Phrases/words to search for in the signal fields.
        signal_fields: Which TagSignals fields to inspect.
                       Empty list means *all text fields*.
        require_all: If True, *all* markers must appear (AND).
                     If False, *any* marker suffices (OR).  Default: OR.
        exclude_markers: If *any* of these appear, the rule does NOT fire
                         (precision guard against false positives).
    """
    tag: str
    markers: tuple[str, ...]
    signal_fields: tuple[str, ...] = ()
    require_all: bool = False
    exclude_markers: tuple[str, ...] = ()


def _get_search_text(signals: TagSignals, field_names: tuple[str, ...]) -> str:
    """Return the concatenated text for the requested signal fields."""
    if not field_names:
        # All text fields
        parts = [
            signals.query, signals.action_slug, signals.action_label,
            signals.main_claim, signals.case_summary, signals.core_dispute,
            signals.most_vulnerable_point, signals.strategic_notes,
            signals.facts_text, signals.requirements_text,
            signals.inferences_text, signals.next_steps_text,
            signals.recommended_actions_text, signals.evidentiary_needs_text,
        ]
        return " ".join(parts)
    return " ".join(getattr(signals, f, "") for f in field_names)


def _rule_fires(rule: TagRule, signals: TagSignals) -> bool:
    """Evaluate whether a single rule fires for the given signals."""
    text = _get_search_text(signals, rule.signal_fields)
    if not text.strip():
        return False

    # Exclusion check first
    if rule.exclude_markers:
        for ex in rule.exclude_markers:
            if ex in text:
                return False

    if rule.require_all:
        return all(marker in text for marker in rule.markers)
    return any(marker in text for marker in rule.markers)


# ---------------------------------------------------------------------------
# Tag rules — family/alimentos focus, extensible
# ---------------------------------------------------------------------------

# Special structural tag: emitted by action_slug match, not marker search.
_ACTION_SLUG_TAGS: dict[str, list[str]] = {
    "alimentos_hijos": ["alimentos_hijos", "estructura_base"],
}

TAG_RULES: list[TagRule] = [
    # -- incumplimiento --
    TagRule(
        tag="incumplimiento",
        markers=("no paga", "incumple", "incumplimiento", "falta de pago"),
        signal_fields=("query", "main_claim", "core_dispute", "facts_text"),
    ),
    # -- cuota provisoria --
    TagRule(
        tag="cuota_provisoria",
        markers=("cuota provisoria", "cuota alimentaria provisoria", "alimentos provisorios"),
        signal_fields=("query", "main_claim", "facts_text", "next_steps_text"),
    ),
    # -- urgencia --
    TagRule(
        tag="urgencia",
        markers=("urgencia", "urgente", "habilitacion de dia y hora", "pase a feria"),
        signal_fields=("query", "main_claim", "strategic_notes", "next_steps_text"),
    ),
    # -- embargo --
    TagRule(
        tag="embargo",
        markers=("embargo",),
        signal_fields=("query", "main_claim", "next_steps_text", "recommended_actions_text"),
    ),
    # -- vulnerabilidad --
    TagRule(
        tag="vulnerabilidad",
        markers=("vulnerabilidad", "proteccion reforzada", "situacion de vulnerabilidad"),
        signal_fields=("query", "main_claim", "core_dispute", "facts_text", "most_vulnerable_point"),
    ),
    # -- bajos_recursos --
    TagRule(
        tag="bajos_recursos",
        markers=("bajos recursos", "sin recursos", "escasos recursos", "carece de recursos"),
        signal_fields=("query", "facts_text", "core_dispute"),
    ),
    # -- justicia_gratuita --
    TagRule(
        tag="justicia_gratuita",
        markers=("justicia gratuita", "beneficio de litigar sin gastos"),
        signal_fields=("query", "facts_text", "next_steps_text"),
    ),
    # -- violencia --
    TagRule(
        tag="violencia",
        markers=("violencia", "violencia de genero", "violencia familiar"),
        signal_fields=("query", "main_claim", "facts_text", "core_dispute"),
    ),
    # -- hechos_sensibles: requires violencia OR explicit mention --
    TagRule(
        tag="hechos_sensibles",
        markers=("violencia", "hechos sensibles", "abuso"),
        signal_fields=("query", "main_claim", "facts_text", "core_dispute"),
    ),
    # -- hijo_mayor_estudiante --
    TagRule(
        tag="hijo_mayor_estudiante",
        markers=("hijo mayor", "mayor estudiante", "estudiante universitario", "art. 663", "art 663"),
        signal_fields=("query", "main_claim", "facts_text", "requirements_text"),
        exclude_markers=("ascendiente", "abuelo", "abuela"),
    ),
    # -- regularidad_academica --
    TagRule(
        tag="regularidad_academica",
        markers=("regularidad academica", "alumno regular", "certificado de alumno"),
        signal_fields=("query", "facts_text", "requirements_text", "evidentiary_needs_text"),
    ),
    # -- continuidad_de_asistencia --
    TagRule(
        tag="continuidad_de_asistencia",
        markers=("continuidad de asistencia",),
        signal_fields=("query", "facts_text", "requirements_text"),
    ),
    # -- ascendientes --
    TagRule(
        tag="ascendientes",
        markers=("ascendiente", "abuelo", "abuela", "ascendientes"),
        signal_fields=("query", "main_claim", "facts_text", "core_dispute"),
        exclude_markers=("hijo mayor", "mayor estudiante"),
    ),
    # -- obligacion_subsidiaria / subsidiariedad --
    TagRule(
        tag="subsidiariedad",
        markers=("subsidiariedad", "subsidiario", "obligacion subsidiaria"),
        signal_fields=("query", "main_claim", "facts_text", "requirements_text"),
    ),
    TagRule(
        tag="obligacion_subsidiaria",
        markers=("obligacion subsidiaria", "subsidiariedad"),
        signal_fields=("query", "main_claim", "facts_text", "requirements_text"),
    ),
    # -- insuficiencia_del_obligado_principal --
    TagRule(
        tag="insuficiencia_del_obligado_principal",
        markers=("obligado principal", "insuficiencia del obligado principal", "imposibilidad del obligado principal"),
        signal_fields=("query", "main_claim", "facts_text", "requirements_text", "core_dispute"),
    ),
    # -- componente_habitacional --
    TagRule(
        tag="componente_habitacional",
        markers=("vivienda", "alquiler", "habitacional", "componente habitacional"),
        signal_fields=("query", "facts_text", "main_claim"),
    ),
    # -- medidas_previas --
    TagRule(
        tag="medidas_previas",
        markers=("medidas previas",),
        signal_fields=("query", "next_steps_text", "recommended_actions_text"),
    ),
    # -- anses_auh_cbu --
    TagRule(
        tag="anses_auh_cbu",
        markers=("anses", "auh", "cbu"),
        signal_fields=("query", "facts_text"),
    ),
    # -- smvm_como_parametro --
    TagRule(
        tag="smvm_como_parametro",
        markers=("smvm",),
        signal_fields=("query", "facts_text", "main_claim"),
    ),
    # -- defensoria --
    TagRule(
        tag="defensoria",
        markers=("defensoria",),
        signal_fields=("query", "facts_text"),
    ),
    # -- caso_mixto --
    TagRule(
        tag="caso_mixto",
        markers=("conyuge", "alimentos conyuge"),
        signal_fields=("query", "main_claim", "facts_text"),
    ),
    # -- orden_de_pretensiones --
    TagRule(
        tag="orden_de_pretensiones",
        markers=("separacion de rubros", "orden de pretensiones"),
        signal_fields=("query", "main_claim", "strategic_notes"),
    ),
    # -- medidas_fuertes (high bar: needs urgencia context too) --
    TagRule(
        tag="medidas_fuertes",
        markers=("embargo", "inhibicion", "habilitacion de dia y hora", "pase a feria"),
        signal_fields=("query", "next_steps_text", "recommended_actions_text"),
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def infer_model_tags(signals: TagSignals) -> list[str]:
    """Infer tags from structured signals using declarative rules.

    Returns a deduplicated, order-preserving list of tags.
    """
    tags: list[str] = []

    # 1. Action-slug structural tags
    slug_tags = _ACTION_SLUG_TAGS.get(signals.action_slug, [])
    tags.extend(slug_tags)

    # 2. Rule-based inference
    for rule in TAG_RULES:
        if _rule_fires(rule, signals):
            tags.append(rule.tag)

    return _dedupe_preserve_order(tags)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
