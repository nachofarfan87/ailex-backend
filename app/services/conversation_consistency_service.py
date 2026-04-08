# backend/app/services/conversation_consistency_service.py
"""
FASE 12.7 — Conversational Consistency Hardening

Capa de consistencia conversacional: traduce `strategy_mode` en constraints
concretos para el composer y el language service.

Problema que resuelve:
- El composer determina `turn_type` desde `dialogue_policy.action`, ignorando `strategy_mode`.
- El variation bucket del language service usa `turn_count`, produciendo cambios arbitrarios.
- No existía un lugar donde decir: "dado este strategy_mode, el composer solo puede
  usar estos tipos de lead y no puede agregar bridge".

Responsabilidades de esta capa:
- Retornar qué elementos puede agregar el composer (suppress flags)
- Retornar qué tipos de lead son compatibles con el strategy_mode (lead_type_whitelist)
- Retornar un bucket de variación estable que no cambie con el turn_count

No toca ni el LLM ni los datos. Solo reconcilia strategy_mode con la presentación.
"""
from __future__ import annotations

from typing import Any


# ── Whitelists de lead-type por strategy_mode ─────────────────────────────────
# Determina qué "tipos de turno" (definidos por el composer) son compatibles
# con cada strategy mode.
# None = sin restricción (el composer elige libremente por dialogue_policy).

_LEAD_TYPE_WHITELIST: dict[str, list[str] | None] = {
    "action_first": [],                                             # sin lead
    "close_without_more_questions": ["partial_closure"],           # solo cierre limpio
    "clarify_critical": ["clarification"],                         # solo framing de aclaración
    "guide_next_step": ["guided_followup", "partial_closure", "followup"],
    "orient_with_prudence": ["guided_followup", "partial_closure", "followup"],
    "substantive_analysis": None,                                   # libre
}

# ── Reglas de supresión de elementos del composer ────────────────────────────
# Cada modo define qué puede y qué no puede agregar el composer al texto base.

_SUPPRESS_RULES: dict[str, dict[str, bool]] = {
    "action_first": {
        "suppress_lead": True,          # va directo a la acción
        "suppress_body_bridge": True,   # ya cubierto por prioritize_action=True, pero explícito
        "suppress_question_intro": False,
    },
    "close_without_more_questions": {
        "suppress_lead": True,          # cierre conclusivo, no retoma el hilo
        "suppress_body_bridge": True,   # no hay nada que puente
        "suppress_question_intro": True,  # no abrir ninguna pregunta
    },
    "clarify_critical": {
        "suppress_lead": False,         # el framing de aclaración sí es útil
        "suppress_body_bridge": True,   # el bridge entre body y pregunta añade ruido
        "suppress_question_intro": False,  # la intro de pregunta es útil aquí
    },
    "guide_next_step": {
        "suppress_lead": False,
        "suppress_body_bridge": False,
        "suppress_question_intro": False,
    },
    "orient_with_prudence": {
        "suppress_lead": False,
        "suppress_body_bridge": False,
        "suppress_question_intro": False,
    },
    "substantive_analysis": {
        "suppress_lead": False,
        "suppress_body_bridge": False,
        "suppress_question_intro": False,
    },
}

# ── Límites de párrafos de body por strategy_mode ────────────────────────────
# Impide que contextos similares produzcan densidades muy diferentes.
# None = sin límite desde esta capa (el composer/postprocessor lo maneja).

_MAX_BODY_PARAGRAPHS: dict[str, int | None] = {
    "action_first": None,               # la lista de acciones puede tener N párrafos
    "close_without_more_questions": 2,  # conclusión breve
    "clarify_critical": 1,              # un solo punto de apoyo
    "guide_next_step": 2,
    "orient_with_prudence": None,
    "substantive_analysis": None,
}

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_SUPPRESS: dict[str, bool] = {
    "suppress_lead": False,
    "suppress_body_bridge": False,
    "suppress_question_intro": False,
}

_DEFAULT_MAX_BODY: int | None = None


def resolve_consistency_policy(
    *,
    strategy_mode: str,
    output_mode: str,
    composition_profile: dict[str, Any] | None = None,
    composition_metadata: dict[str, Any] | None = None,
    conversation_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Devuelve una policy de consistencia para el turno.

    Salida:
    {
        "strategy_mode": str,
        "suppress_lead": bool,
        "suppress_body_bridge": bool,
        "suppress_question_intro": bool,
        "max_body_paragraphs": int | None,
        "lead_type_whitelist": list[str] | None,
        "stable_variation_bucket": int,
        "reason": str,
    }

    Esta policy es consumida por:
    - `conversation_composer_service.compose()` (suppress flags + lead_type_whitelist)
    - `strategy_language_service.resolve_strategy_language_profile()` (stable_variation_bucket)
    """
    normalized_mode = str(strategy_mode or "orient_with_prudence").strip().lower()
    normalized_output = str(output_mode or "orientacion_inicial").strip().lower()
    composition_profile = dict(composition_profile or {})
    composition_metadata = dict(composition_metadata or {})
    conversation_state = dict(conversation_state or {})

    suppress_rules = dict(_SUPPRESS_RULES.get(normalized_mode) or _DEFAULT_SUPPRESS)
    lead_whitelist = _LEAD_TYPE_WHITELIST.get(normalized_mode, None)  # None = libre
    max_body = _MAX_BODY_PARAGRAPHS.get(normalized_mode, _DEFAULT_MAX_BODY)

    # Refinamientos contextuales
    # Si el composition_profile dice allow_followup=False, suprimir question_intro siempre
    if not bool(composition_profile.get("allow_followup", True)):
        suppress_rules = dict(suppress_rules)
        suppress_rules["suppress_question_intro"] = True

    # Para output_mode != orientacion_inicial, el lead siempre se suprime
    # (el composition service ya maneja la apertura en esos modos)
    if normalized_output != "orientacion_inicial":
        suppress_rules = dict(suppress_rules)
        suppress_rules["suppress_lead"] = True

    stable_bucket = _compute_stable_variation_bucket(
        strategy_mode=normalized_mode,
        output_mode=normalized_output,
        conversation_state=conversation_state,
    )

    reason = _build_reason(
        strategy_mode=normalized_mode,
        suppress_lead=suppress_rules.get("suppress_lead", False),
        suppress_body_bridge=suppress_rules.get("suppress_body_bridge", False),
        suppress_question_intro=suppress_rules.get("suppress_question_intro", False),
    )

    return {
        "strategy_mode": normalized_mode,
        "suppress_lead": bool(suppress_rules.get("suppress_lead", False)),
        "suppress_body_bridge": bool(suppress_rules.get("suppress_body_bridge", False)),
        "suppress_question_intro": bool(suppress_rules.get("suppress_question_intro", False)),
        "max_body_paragraphs": max_body,
        "lead_type_whitelist": lead_whitelist,
        "stable_variation_bucket": stable_bucket,
        "reason": reason,
    }


def _compute_stable_variation_bucket(
    *,
    strategy_mode: str,
    output_mode: str,
    conversation_state: dict[str, Any],
) -> int:
    """
    Computa un bucket de variación estable para el language service.

    Ancla: (strategy_mode, output_mode, case_completeness).
    No usa turn_count — evita cambios de variante entre turnos consecutivos
    con el mismo contexto estratégico.

    Cambia cuando cambia el strategy_mode, el output_mode, o la completitud del caso,
    lo cual corresponde a un cambio real de contexto estratégico.
    """
    progress = dict(conversation_state.get("progress_signals") or {})
    case_completeness = str(progress.get("case_completeness") or "low").strip().lower()

    seed = (
        len(strategy_mode) * 7
        + len(output_mode) * 5
        + len(case_completeness) * 3
    )
    return seed % 3


def _build_reason(
    *,
    strategy_mode: str,
    suppress_lead: bool,
    suppress_body_bridge: bool,
    suppress_question_intro: bool,
) -> str:
    parts: list[str] = [f"strategy_mode={strategy_mode!r}"]
    if suppress_lead:
        parts.append("sin lead")
    if suppress_body_bridge:
        parts.append("sin bridge")
    if suppress_question_intro:
        parts.append("sin question_intro")
    return "; ".join(parts) if len(parts) > 1 else f"strategy_mode={strategy_mode!r}; sin restricciones adicionales"
