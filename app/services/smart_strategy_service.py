# backend/app/services/smart_strategy_service.py
from __future__ import annotations

import re
from typing import Any


_STRUCTURAL_FACT_PATTERNS = (
    "jurisdic",
    "vinculo",
    "relacion",
    "hijos",
    "hijo",
    "domicilio",
    "ingres",
    "conviv",
    "separa",
    "fecha",
    "urgenc",
    "document",
    "conflicto",
)

_URGENCY_PATTERNS = (
    "urgenc",
    "violenc",
    "riesgo",
    "cautelar",
    "salud",
    "nino",
    "nina",
    "exclusion",
    "medida_urgente",
    "alimentos_urgentes",
)


def resolve_smart_strategy(
    known_facts: dict,
    missing_facts: list,
    conversation_state: dict,
    case_followup: dict | None = None,
    case_confidence: dict | None = None,
    output_mode: str | None = None,
    case_progress: dict | None = None,
) -> dict:
    """
    Returns:
    {
        "strategy_mode": str,
        "response_goal": str,
        "recommended_tone": "prudente" | "directo" | "explicativo" | "ejecutivo",
        "recommended_structure": "brief" | "guided" | "standard" | "extended",
        "should_prioritize_action": bool,
        "should_prioritize_clarification": bool,
        "should_limit_analysis": bool,
        "should_offer_next_step": bool,
        "reason": str,
    }
    """
    known_facts = dict(known_facts or {})
    missing_facts = [dict(item) for item in list(missing_facts or []) if isinstance(item, dict)]
    conversation_state = dict(conversation_state or {})
    case_followup = dict(case_followup or {})
    case_confidence = dict(case_confidence or {})
    case_progress = dict(case_progress or {})
    normalized_output_mode = str(output_mode or "").strip().lower()

    progress_state = _resolve_progress_state(conversation_state, case_followup)
    user_cannot_answer = _resolve_boolean_signal("user_cannot_answer", conversation_state, case_followup)
    detected_loop = _resolve_boolean_signal("detected_loop", conversation_state, case_followup)

    confidence_level = str(case_confidence.get("confidence_level") or "low").strip().lower()
    confidence_score = _safe_float(case_confidence.get("confidence_score"), default=0.0)
    case_stage = str(case_confidence.get("case_stage") or "developing").strip().lower()
    closure_readiness = str(case_confidence.get("closure_readiness") or "low").strip().lower()
    needs_more_questions = bool(case_confidence.get("needs_more_questions"))

    urgency = _detect_urgency(known_facts, missing_facts)
    structural_fact_count = _count_structural_facts(known_facts)
    has_critical_missing = _has_critical_missing(missing_facts)
    has_high_impact_missing = _has_high_impact_missing(missing_facts)
    progress_signals = _resolve_case_progress_signals(case_progress)

    strategy_mode = _resolve_strategy_mode(
        urgency=urgency,
        progress_state=progress_state,
        user_cannot_answer=user_cannot_answer,
        detected_loop=detected_loop,
        needs_more_questions=needs_more_questions,
        confidence_level=confidence_level,
        confidence_score=confidence_score,
        case_stage=case_stage,
        closure_readiness=closure_readiness,
        has_critical_missing=has_critical_missing,
        has_high_impact_missing=has_high_impact_missing,
        structural_fact_count=structural_fact_count,
        case_followup=case_followup,
        output_mode=normalized_output_mode,
        case_progress=progress_signals,
    )

    response_goal = _resolve_response_goal(strategy_mode)
    recommended_tone = _resolve_recommended_tone(
        strategy_mode=strategy_mode,
        output_mode=normalized_output_mode,
        progress_state=progress_state,
        progress_signals=progress_signals,
    )
    recommended_structure = _resolve_recommended_structure(
        strategy_mode=strategy_mode,
        case_confidence=case_confidence,
    )

    return {
        "strategy_mode": strategy_mode,
        "response_goal": response_goal,
        "recommended_tone": recommended_tone,
        "recommended_structure": recommended_structure,
        "should_prioritize_action": _should_prioritize_action(strategy_mode),
        "should_prioritize_clarification": _should_prioritize_clarification(strategy_mode),
        "should_limit_analysis": _should_limit_analysis(strategy_mode),
        "should_offer_next_step": _should_offer_next_step(strategy_mode),
        "reason": _build_reason(
            strategy_mode=strategy_mode,
            progress_state=progress_state,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            case_stage=case_stage,
            closure_readiness=closure_readiness,
            has_critical_missing=has_critical_missing,
            has_high_impact_missing=has_high_impact_missing,
            needs_more_questions=needs_more_questions,
            urgency=urgency,
            user_cannot_answer=user_cannot_answer,
            detected_loop=detected_loop,
            structural_fact_count=structural_fact_count,
            output_mode=normalized_output_mode,
            case_progress=progress_signals,
        ),
    }


def _detect_urgency(known_facts: dict[str, Any], missing_facts: list[dict[str, Any]]) -> bool:
    for key, value in known_facts.items():
        normalized = _normalize_text(f"{key} {value}")
        if any(pattern in normalized for pattern in _URGENCY_PATTERNS):
            return True

    for fact in missing_facts:
        normalized = _normalize_text(
            f"{fact.get('key') or ''} {fact.get('label') or ''} {fact.get('suggested_question') or ''}"
        )
        if any(pattern in normalized for pattern in _URGENCY_PATTERNS):
            return True

    return False


def _count_structural_facts(known_facts: dict[str, Any]) -> int:
    count = 0
    for key, value in known_facts.items():
        if value in (None, "", [], {}, False):
            continue

        normalized = _normalize_text(key)
        if any(pattern in normalized for pattern in _STRUCTURAL_FACT_PATTERNS):
            count += 1

    return count


def _has_critical_missing(missing_facts: list[dict[str, Any]]) -> bool:
    return any(str(item.get("importance") or "").strip().lower() == "critical" for item in missing_facts)


def _has_high_impact_missing(missing_facts: list[dict[str, Any]]) -> bool:
    for item in missing_facts:
        importance = str(item.get("importance") or "").strip().lower()
        if importance == "critical":
            return True
        if importance == "high" and bool(item.get("impact_on_strategy")):
            return True
    return False


def _resolve_strategy_mode(
    *,
    urgency: bool,
    progress_state: str,
    user_cannot_answer: bool,
    detected_loop: bool,
    needs_more_questions: bool,
    confidence_level: str,
    confidence_score: float,
    case_stage: str,
    closure_readiness: str,
    has_critical_missing: bool,
    has_high_impact_missing: bool,
    structural_fact_count: int,
    case_followup: dict[str, Any],
    output_mode: str,
    case_progress: dict[str, Any],
) -> str:
    should_ask = bool(case_followup.get("should_ask"))

    if urgency:
        return "action_first"

    if case_progress["stage"] == "inconsistente":
        if should_ask and case_progress["next_step_type"] == "resolve_contradiction":
            return "clarify_critical"
        return "orient_with_prudence"

    if case_progress["stage"] == "bloqueado" or case_progress["progress_status"] == "blocked":
        if should_ask and case_progress["next_step_type"] == "ask":
            return "clarify_critical"
        return "orient_with_prudence"

    if (
        output_mode == "ejecucion"
        and case_progress["has_execution_steps"]
        and not case_progress["has_blockers"]
        and case_progress["next_step_type"] != "resolve_contradiction"
        and not should_ask
        and confidence_score >= 0.5
    ):
        return "action_first"

    if user_cannot_answer or detected_loop or progress_state == "blocked":
        if closure_readiness == "high":
            return "close_without_more_questions"
        return "orient_with_prudence"

    if case_progress["stage"] == "ejecucion" and case_progress["readiness_label"] == "high" and not case_progress["has_blockers"]:
        return "action_first"

    if case_progress["stage"] == "decision" and not case_progress["has_critical_gaps"]:
        if confidence_level == "high" or confidence_score >= 0.68:
            return "substantive_analysis"
        return "guide_next_step"

    if case_progress["stage"] == "exploracion" and case_progress["has_critical_gaps"]:
        return "clarify_critical" if should_ask else "orient_with_prudence"

    if case_progress["stage"] == "estructuracion":
        if case_progress["has_critical_gaps"]:
            return "clarify_critical" if should_ask else "orient_with_prudence"
        if structural_fact_count >= 2:
            return "guide_next_step"

    if (has_critical_missing or has_high_impact_missing) and needs_more_questions:
        if should_ask and case_stage in {"insufficient", "developing"}:
            return "clarify_critical"

    if confidence_level == "high" and case_stage in {"substantive", "mature"}:
        return "substantive_analysis"

    if case_stage == "mature" and confidence_level == "medium" and confidence_score >= 0.70:
        return "substantive_analysis"

    if case_stage == "substantive" and confidence_score >= 0.78 and not has_critical_missing:
        return "substantive_analysis"

    if not needs_more_questions and closure_readiness == "high":
        return "close_without_more_questions"

    if (
        case_stage in {"developing", "substantive"}
        and structural_fact_count >= 2
        and not has_critical_missing
        and progress_state in {"advancing", "complete", "stalled"}
        and confidence_score >= 0.45
    ):
        return "guide_next_step"

    if output_mode == "ejecucion" and confidence_score >= 0.55 and not has_critical_missing:
        return "action_first"

    if not needs_more_questions and closure_readiness in {"medium", "high"}:
        return "close_without_more_questions"

    return "orient_with_prudence"


def _resolve_response_goal(strategy_mode: str) -> str:
    goals = {
        "clarify_critical": "obtener la ultima aclaracion critica que destraba el caso",
        "guide_next_step": "orientar el siguiente paso util sin sobreexplicar",
        "orient_with_prudence": "orientar con limites claros y utilidad real",
        "substantive_analysis": "desarrollar una orientacion juridica mas rica y util",
        "action_first": "priorizar una salida operativa y accionable",
        "close_without_more_questions": "cerrar el turno con claridad sin seguir abriendo preguntas",
    }
    return goals.get(strategy_mode, "orientar el turno con la estrategia mas util")


def _resolve_recommended_tone(
    *,
    strategy_mode: str,
    output_mode: str,
    progress_state: str,
    progress_signals: dict[str, Any] | None = None,
) -> str:
    _signals = dict(progress_signals or {})
    has_non_blocking_critical_gaps = bool(_signals.get("has_non_blocking_critical_gaps"))

    if strategy_mode == "action_first":
        # Hay datos críticos pendientes que no bloquean la acción pero merecen prudencia.
        # No sonar 100% cerrado cuando aún queda un dato sensible.
        if has_non_blocking_critical_gaps:
            return "prudente"
        return "ejecutivo"
    if strategy_mode == "clarify_critical":
        return "directo"
    if strategy_mode == "substantive_analysis":
        return "explicativo"
    if strategy_mode == "guide_next_step" and output_mode == "ejecucion":
        return "ejecutivo"
    if progress_state in {"blocked", "stalled"}:
        return "prudente"
    return "prudente" if strategy_mode in {"orient_with_prudence", "close_without_more_questions"} else "explicativo"


def _resolve_recommended_structure(*, strategy_mode: str, case_confidence: dict[str, Any]) -> str:
    recommended_depth = str(case_confidence.get("recommended_depth") or "").strip().lower()

    if strategy_mode in {"clarify_critical", "close_without_more_questions"}:
        return "brief"

    if strategy_mode in {"action_first", "guide_next_step", "orient_with_prudence"}:
        return "guided"

    if strategy_mode == "substantive_analysis" and recommended_depth == "extended":
        return "extended"

    return "standard"


def _should_prioritize_action(strategy_mode: str) -> bool:
    return strategy_mode in {"action_first", "guide_next_step"}


def _should_prioritize_clarification(strategy_mode: str) -> bool:
    return strategy_mode == "clarify_critical"


def _should_limit_analysis(strategy_mode: str) -> bool:
    return strategy_mode in {
        "clarify_critical",
        "orient_with_prudence",
        "action_first",
        "close_without_more_questions",
    }


def _should_offer_next_step(strategy_mode: str) -> bool:
    return strategy_mode in {
        "guide_next_step",
        "orient_with_prudence",
        "substantive_analysis",
        "action_first",
        "close_without_more_questions",
    }


def _resolve_progress_state(conversation_state: dict[str, Any], case_followup: dict[str, Any]) -> str:
    for candidate in (
        case_followup.get("adaptive_progress_state"),
        conversation_state.get("progress_state"),
        dict(conversation_state.get("progress_signals") or {}).get("progress_state"),
    ):
        value = str(candidate or "").strip().lower()
        if value in {"complete", "advancing", "stalled", "blocked"}:
            return value
    return "advancing"


def _resolve_boolean_signal(key: str, conversation_state: dict[str, Any], case_followup: dict[str, Any]) -> bool:
    if key in case_followup:
        return bool(case_followup.get(key))
    if key in conversation_state:
        return bool(conversation_state.get(key))
    return bool(dict(conversation_state.get("progress_signals") or {}).get(key))


def _resolve_case_progress_signals(case_progress: dict[str, Any]) -> dict[str, Any]:
    """
    Traduce case_progress en señales operativas para _resolve_strategy_mode.

    Delega en resolve_progress_behavior_intent para mantener consistencia con
    case_followup_service (ambos leen la misma intención base).
    Agrega has_execution_steps que es una señal de datos, no de intención.
    """
    from app.services.case_progress_service import resolve_progress_behavior_intent
    intent = resolve_progress_behavior_intent(case_progress)
    basis = dict(case_progress.get("basis") or {})
    return {
        **intent,
        "has_execution_steps": bool(basis.get("has_execution_steps")),
    }


def _build_reason(
    *,
    strategy_mode: str,
    progress_state: str,
    confidence_level: str,
    confidence_score: float,
    case_stage: str,
    closure_readiness: str,
    has_critical_missing: bool,
    has_high_impact_missing: bool,
    needs_more_questions: bool,
    urgency: bool,
    user_cannot_answer: bool,
    detected_loop: bool,
    structural_fact_count: int,
    output_mode: str,
    case_progress: dict[str, Any],
) -> str:
    reasons = [
        f"Modo elegido: {strategy_mode}.",
        f"Progreso: {progress_state}.",
        f"Confianza: {confidence_level} ({confidence_score:.2f}).",
        f"Etapa del caso: {case_stage}.",
        f"Cierre estimado: {closure_readiness}.",
        f"Hechos estructurales detectados: {structural_fact_count}.",
    ]

    if case_progress["stage"]:
        reasons.append(f"Case progress stage: {case_progress['stage']}.")
    if case_progress["progress_status"]:
        reasons.append(f"Case progress status: {case_progress['progress_status']}.")
    if case_progress["next_step_type"]:
        reasons.append(f"Next step: {case_progress['next_step_type']}.")
    if case_progress.get("has_non_blocking_critical_gaps"):
        reasons.append("Hay gaps críticos pendientes que no bloquean la ejecución pero requieren prudencia en el tono.")
    if urgency:
        reasons.append("Hay señales de urgencia.")
    if has_critical_missing:
        reasons.append("Todavía hay datos críticos pendientes.")
    elif has_high_impact_missing:
        reasons.append("Quedan datos de alto impacto.")
    if not needs_more_questions:
        reasons.append("No conviene abrir más preguntas.")
    if user_cannot_answer:
        reasons.append("El usuario no puede aportar más datos útiles ahora.")
    if detected_loop:
        reasons.append("Se detectó redundancia reciente.")
    if output_mode:
        reasons.append(f"Output mode observado: {output_mode}.")

    return " ".join(reasons)


def _normalize_text(value: Any) -> str:
    text = re.sub(r"[^a-z0-9\s_]+", " ", str(value or "").casefold())
    return re.sub(r"\s+", " ", text).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
