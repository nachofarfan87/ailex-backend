# backend/app/services/professional_judgment_service.py
from __future__ import annotations

import re
from typing import Any

from app.services.professional_judgment_constants import (
    ACTION_CANDIDATE_BONUS,
    ACTION_FIRST_STRATEGY_BONUS,
    ACTION_READY_CONFIDENCE_WEIGHT,
    CLOSURE_HIGH_BONUS,
    CONFIDENCE_BASE_SCORE,
    CONFIDENCE_HIGH_BONUS,
    CONFIDENCE_MEDIUM_BONUS,
    CONFIDENCE_SCORE_WEIGHT,
    EVIDENCE_PRESENT_BONUS,
    PRACTICAL_RISK_BLOCKED_STATUS_BONUS,
    PRACTICAL_RISK_BLOCKING_BONUS,
    PRACTICAL_RISK_CONTRADICTION_BONUS,
    PRACTICAL_RISK_CRITICAL_GAP_BONUS,
    PRACTICAL_RISK_DETECTED_BONUS,
    PRACTICAL_RISK_IMPORTANT_GAP_BONUS,
    PROGRESS_READY_BONUS,
    NEXT_STEP_ACTION_BONUS,
    READINESS_HIGH_BONUS,
    READINESS_MEDIUM_BONUS,
    URGENCY_SIGNAL_SCORE,
)
from app.services.decision_transparency_service import build_decision_transparency
from app.services.professional_judgment_rules import calibrate_judgment


_URGENT_PATTERNS = (
    "urgenc",
    "urgente",
    "violenc",
    "salud",
    "riesgo",
    "cautelar",
    "provisoria",
    "cuanto antes",
    "inmediata",
    "inmediato",
)

_PRACTICAL_RISK_PATTERNS = (
    "riesgo",
    "demora",
    "escalar",
    "perjuicio",
    "sin cobertura",
    "sin sostener",
    "sin acreditar",
)


def build_professional_judgment(*, api_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(api_payload or {})
    context = _extract_judgment_context(payload)
    calibration = calibrate_judgment(context["signals"])

    contradiction_label = context["contradiction_label"]
    blocking_label = context["blocking_label"]
    critical_gap_label = context["critical_gap_label"]
    important_gap_label = context["important_gap_label"]
    evidence_label = context["evidence_label"]
    followup_question = context["followup_question"]
    followup_need = context["followup_need"]
    primary_step_label = context["primary_step_label"]
    primary_step_reason = context["primary_step_reason"]
    primary_focus_label = context["primary_focus_label"]
    primary_focus_reason = context["primary_focus_reason"]
    narrative_known = context["narrative_known"]
    urgency_detected = bool(context["signals"].get("urgency_detected"))

    dominant_factor = _build_dominant_factor(
        dominant_signal=calibration["dominant_signal"],
        contradiction_label=contradiction_label,
        blocking_label=blocking_label,
        critical_gap_label=critical_gap_label,
        important_gap_label=important_gap_label,
        primary_focus_label=primary_focus_label,
        evidence_label=evidence_label,
        urgency_detected=urgency_detected,
        calibrated_state=calibration["calibrated_state"],
    )
    practical_risk = _build_practical_risk(
        calibrated_state=calibration["calibrated_state"],
        contradiction_label=contradiction_label,
        blocking_label=blocking_label,
        critical_gap_label=critical_gap_label,
        important_gap_label=important_gap_label,
        urgency_detected=urgency_detected,
    )
    blocking_issue = _build_blocking_issue(
        calibrated_state=calibration["calibrated_state"],
        contradiction_label=contradiction_label,
        blocking_label=blocking_label,
        critical_gap_label=critical_gap_label,
        followup_need=followup_need,
        followup_question=followup_question,
    )
    best_next_move = _build_best_next_move(
        decision_intent=calibration["decision_intent"],
        calibrated_state=calibration["calibrated_state"],
        followup_need=followup_need,
        followup_question=followup_question,
        primary_step_label=primary_step_label,
        quick_start=context["quick_start"],
        primary_focus_label=primary_focus_label,
        urgency_detected=urgency_detected,
    )
    why_this_matters_now = _build_why_this_matters_now(
        calibrated_state=calibration["calibrated_state"],
        contradiction_label=contradiction_label,
        blocking_label=blocking_label,
        critical_gap_label=critical_gap_label,
        important_gap_label=important_gap_label,
        urgency_detected=urgency_detected,
        primary_step_reason=primary_step_reason,
        primary_focus_reason=primary_focus_reason,
        actionability=calibration["actionability"],
        practical_risk=practical_risk,
    )
    followup_why = _build_followup_why(
        followup_question=followup_question,
        contradiction_label=contradiction_label,
        critical_gap_label=critical_gap_label,
        blocking_label=blocking_label,
        followup_need=followup_need,
        calibrated_state=calibration["calibrated_state"],
    )
    strengthens_position = _build_strengthens_position(
        calibrated_state=calibration["calibrated_state"],
        evidence_label=evidence_label,
        primary_step_reason=primary_step_reason,
        narrative_known=narrative_known,
    )
    weakens_position = _build_weakens_position(
        contradiction_label=contradiction_label,
        blocking_label=blocking_label,
        critical_gap_label=critical_gap_label,
        important_gap_label=important_gap_label,
        calibration=calibration,
    )
    missing_to_strengthen = _build_missing_to_strengthen(
        critical_gap_label=critical_gap_label,
        important_gap_label=important_gap_label,
        evidence_label=evidence_label,
        calibrated_state=calibration["calibrated_state"],
    )

    highlights = _dedupe_texts(
        [
            dominant_factor,
            practical_risk,
            strengthens_position,
            weakens_position,
            missing_to_strengthen,
            why_this_matters_now,
        ]
    )[:4]
    applies = bool(_dedupe_texts([dominant_factor, best_next_move, why_this_matters_now, practical_risk]))
    transparency = build_decision_transparency(
        context=context,
        calibration=calibration,
        judgment={
            "dominant_factor": dominant_factor,
            "practical_risk": practical_risk,
            "blocking_issue": blocking_issue,
            "best_next_move": best_next_move,
            "why_this_matters_now": why_this_matters_now,
            "strengthens_position": strengthens_position,
            "weakens_position": weakens_position,
            "missing_to_strengthen": missing_to_strengthen,
            "followup_why": followup_why,
        },
    )

    return {
        "applies": applies,
        "dominant_factor": dominant_factor,
        "practical_risk": practical_risk,
        "position_strength": _resolve_position_strength(calibration, context["signals"]),
        "blocking_issue": blocking_issue,
        "best_next_move": best_next_move,
        "prudence_level": calibration["prudence_level"],
        "recommendation_stance": calibration["recommendation_stance"],
        "why_this_matters_now": why_this_matters_now,
        "exposure_level": _resolve_exposure_level(calibration, context["signals"]),
        "strengthens_position": strengthens_position,
        "weakens_position": weakens_position,
        "missing_to_strengthen": missing_to_strengthen,
        "followup_why": followup_why,
        "highlights": highlights,
        "calibration": calibration,
        "decision_transparency": transparency,
    }


def _extract_judgment_context(payload: dict[str, Any]) -> dict[str, Any]:
    case_progress = dict(payload.get("case_progress") or {})
    case_followup = dict(payload.get("case_followup") or {})
    conversational = dict(payload.get("conversational") or {})
    clarification_context = dict(dict(payload.get("metadata") or {}).get("clarification_context") or {})
    smart_strategy = dict(payload.get("smart_strategy") or {})
    case_workspace = dict(payload.get("case_workspace") or {})
    case_progress_narrative = dict(payload.get("case_progress_narrative") or {})
    case_confidence = dict(payload.get("case_confidence") or {})
    case_profile = dict(payload.get("case_profile") or {})
    quick_start = _clean_text(payload.get("quick_start"))
    response_text = _clean_text(payload.get("response_text"))

    contradictions = _as_list(case_progress.get("contradictions"))
    blocking_issues = _as_list(case_progress.get("blocking_issues"))
    critical_gaps = _as_list(case_progress.get("critical_gaps"))
    important_gaps = _as_list(case_progress.get("important_gaps"))
    action_plan = _as_list(case_workspace.get("action_plan"))
    evidence_checklist = dict(case_workspace.get("evidence_checklist") or {})
    primary_focus = dict(case_workspace.get("primary_focus") or {})
    professional_handoff = dict(case_workspace.get("professional_handoff") or {})

    contradiction_label = _first_item_label(contradictions)
    blocking_label = _first_item_label(blocking_issues) or _clean_text(
        professional_handoff.get("primary_friction")
    )
    critical_gap_label = _first_item_label(critical_gaps)
    important_gap_label = _first_item_label(important_gaps)
    primary_focus_label = _clean_text(primary_focus.get("label"))
    primary_focus_reason = _clean_text(primary_focus.get("reason"))
    primary_step = _first_action(action_plan)
    primary_step_label = _action_label(primary_step) or _simplify_action_text(quick_start)
    primary_step_reason = _clean_text(primary_step.get("why_it_matters")) or _clean_text(
        primary_step.get("why_now")
    )
    evidence_label = _first_item_label(_as_list(evidence_checklist.get("critical")))
    followup_question = (
        _clean_text(case_followup.get("question")) if bool(case_followup.get("should_ask")) else ""
    )
    followup_need = critical_gap_label or important_gap_label or _humanize_need_key(
        _clean_text(case_followup.get("need_key"))
    )
    readiness_label = _clean_text(case_progress.get("readiness_label")).lower()
    progress_status = _clean_text(case_progress.get("progress_status")).lower()
    next_step_type = _clean_text(case_progress.get("next_step_type")).lower()
    strategy_mode = _clean_text(smart_strategy.get("strategy_mode")).lower()
    case_domain = (
        _clean_text(payload.get("case_domain")).lower()
        or _clean_text(case_profile.get("case_domain")).lower()
        or _clean_text(payload.get("domain")).lower()
    )
    confidence_level = _clean_text(case_confidence.get("confidence_level")).lower()
    confidence_score = _safe_float(case_confidence.get("confidence_score"))
    closure_readiness = _clean_text(case_confidence.get("closure_readiness")).lower()
    urgency_detected = _detect_urgency(
        quick_start=quick_start,
        response_text=response_text,
        primary_focus_label=primary_focus_label,
        primary_step_label=primary_step_label,
        strategy_mode=strategy_mode,
        handoff_reason=_clean_text(professional_handoff.get("handoff_reason")),
    )
    practical_risk_detected = _detect_practical_risk(
        response_text=response_text,
        primary_focus_reason=primary_focus_reason,
        primary_step_reason=primary_step_reason,
        handoff_reason=_clean_text(professional_handoff.get("handoff_reason")),
    )
    base_strength_score = _resolve_base_strength_score(
        confidence_level=confidence_level,
        confidence_score=confidence_score,
        readiness_label=readiness_label,
        closure_readiness=closure_readiness,
        evidence_label=evidence_label,
    )
    action_ready_score = _resolve_action_ready_score(
        readiness_label=readiness_label,
        progress_status=progress_status,
        next_step_type=next_step_type,
        has_action_candidate=bool(primary_step_label),
        strategy_mode=strategy_mode,
        confidence_score=confidence_score,
    )
    practical_risk_score = _resolve_practical_risk_score(
        urgency_detected=urgency_detected,
        practical_risk_detected=practical_risk_detected,
        contradiction_count=len(contradictions),
        blocking_issue_count=len(blocking_issues),
        critical_gap_count=len(critical_gaps),
        important_gap_count=len(important_gaps),
        progress_status=progress_status,
    )
    followup_usefulness = _resolve_followup_usefulness(
        case_followup=case_followup,
        critical_gap_count=len(critical_gaps),
        contradiction_count=len(contradictions),
    )

    signals = {
        "urgency_detected": urgency_detected,
        "urgency_score": URGENCY_SIGNAL_SCORE if urgency_detected else 0,
        "practical_risk_score": practical_risk_score,
        "contradiction_count": len(contradictions),
        "blocking_issue_count": len(blocking_issues) + (1 if blocking_label else 0),
        "critical_gap_count": len(critical_gaps),
        "important_gap_count": len(important_gaps),
        "base_strength_score": base_strength_score,
        "action_ready_score": action_ready_score,
        "has_action_candidate": bool(primary_step_label),
        "followup_present": bool(followup_question),
        "followup_usefulness": followup_usefulness,
        "next_step_type": next_step_type,
        "readiness_label": readiness_label,
        "progress_status": progress_status,
        "strategy_mode": strategy_mode,
        "case_domain": case_domain,
    }

    return {
        "signals": signals,
        "quick_start": quick_start,
        "contradiction_label": contradiction_label,
        "blocking_label": blocking_label,
        "critical_gap_label": critical_gap_label,
        "important_gap_label": important_gap_label,
        "primary_focus_label": primary_focus_label,
        "primary_focus_reason": primary_focus_reason,
        "primary_step_label": primary_step_label,
        "primary_step_reason": primary_step_reason,
        "evidence_label": evidence_label,
        "followup_question": followup_question,
        "followup_need": followup_need,
        "narrative_known": _clean_text(case_progress_narrative.get("known_block")),
        "clarification_status": (
            _clean_text(clarification_context.get("response_quality")).lower()
            or _clean_text(conversational.get("clarification_status")).lower()
        ),
        "response_quality": _clean_text(clarification_context.get("response_quality")).lower(),
        "response_strategy": _clean_text(clarification_context.get("response_strategy")).lower(),
        "user_cannot_answer": bool(clarification_context.get("user_cannot_answer")),
        "detected_loop": bool(clarification_context.get("detected_loop")),
        "canonical_slot": _clean_text(clarification_context.get("canonical_slot")).lower(),
        "precision_required": bool(
            (
                _clean_text(clarification_context.get("response_strategy")).lower() in {"clarify", "reformulate_question"}
                or _clean_text(clarification_context.get("response_quality")).lower() == "ambiguous"
                or _clean_text(conversational.get("clarification_status")).lower() == "ambiguous"
            )
            and followup_question
        ),
    }


def _resolve_base_strength_score(
    *,
    confidence_level: str,
    confidence_score: float,
    readiness_label: str,
    closure_readiness: str,
    evidence_label: str,
) -> int:
    score = CONFIDENCE_BASE_SCORE
    if confidence_level == "high":
        score += CONFIDENCE_HIGH_BONUS
    elif confidence_level == "medium":
        score += CONFIDENCE_MEDIUM_BONUS
    score += int(max(0.0, min(1.0, confidence_score)) * CONFIDENCE_SCORE_WEIGHT)
    if readiness_label == "high":
        score += READINESS_HIGH_BONUS
    elif readiness_label == "medium":
        score += READINESS_MEDIUM_BONUS
    if closure_readiness == "high":
        score += CLOSURE_HIGH_BONUS
    if evidence_label:
        score += EVIDENCE_PRESENT_BONUS
    return min(score, 100)


def _resolve_action_ready_score(
    *,
    readiness_label: str,
    progress_status: str,
    next_step_type: str,
    has_action_candidate: bool,
    strategy_mode: str,
    confidence_score: float,
) -> int:
    score = 0
    if has_action_candidate:
        score += ACTION_CANDIDATE_BONUS
    if readiness_label == "high":
        score += READINESS_HIGH_BONUS + 10
    elif readiness_label == "medium":
        score += READINESS_MEDIUM_BONUS + 4
    if progress_status in {"ready", "advancing"}:
        score += PROGRESS_READY_BONUS
    if next_step_type in {"execute", "decide"}:
        score += NEXT_STEP_ACTION_BONUS
    if strategy_mode == "action_first":
        score += ACTION_FIRST_STRATEGY_BONUS
    score += int(max(0.0, min(1.0, confidence_score)) * ACTION_READY_CONFIDENCE_WEIGHT)
    return min(score, 100)


def _resolve_practical_risk_score(
    *,
    urgency_detected: bool,
    practical_risk_detected: bool,
    contradiction_count: int,
    blocking_issue_count: int,
    critical_gap_count: int,
    important_gap_count: int,
    progress_status: str,
) -> int:
    score = 0
    if practical_risk_detected:
        score += PRACTICAL_RISK_DETECTED_BONUS
    if contradiction_count > 0:
        score += PRACTICAL_RISK_CONTRADICTION_BONUS
    if blocking_issue_count > 0:
        score += PRACTICAL_RISK_BLOCKING_BONUS
    if critical_gap_count > 0:
        score += PRACTICAL_RISK_CRITICAL_GAP_BONUS
    elif important_gap_count > 0:
        score += PRACTICAL_RISK_IMPORTANT_GAP_BONUS
    if progress_status == "blocked":
        score += PRACTICAL_RISK_BLOCKED_STATUS_BONUS
    if urgency_detected and score:
        score = min(100, score + 5)
    return min(score, 100)


def _resolve_followup_usefulness(
    *,
    case_followup: dict[str, Any],
    critical_gap_count: int,
    contradiction_count: int,
) -> str:
    if not bool(case_followup.get("should_ask")):
        return "none"
    adaptive_type = _clean_text(case_followup.get("adaptive_question_type")).lower()
    if contradiction_count > 0 or adaptive_type == "confirmation":
        return "blocking"
    if critical_gap_count > 0:
        return "critical"
    return "refinement"


def _resolve_position_strength(calibration: dict[str, Any], signals: dict[str, Any]) -> str:
    if calibration["calibrated_state"] == "blocked":
        return "fragile"
    if calibration["calibrated_state"] == "action_ready":
        return "solid"
    if signals.get("base_strength_score", 0) >= 60:
        return "developing"
    return "fragile"


def _resolve_exposure_level(calibration: dict[str, Any], signals: dict[str, Any]) -> str:
    if signals.get("urgency_score", 0) >= 85 or signals.get("practical_risk_score", 0) >= 75:
        return "high"
    if calibration["blocking_severity"] in {"hard", "medium"}:
        return "high" if calibration["blocking_severity"] == "hard" else "medium"
    if signals.get("important_gap_count", 0) > 0:
        return "medium"
    return "low"


def _build_dominant_factor(
    *,
    dominant_signal: str,
    contradiction_label: str,
    blocking_label: str,
    critical_gap_label: str,
    important_gap_label: str,
    primary_focus_label: str,
    evidence_label: str,
    urgency_detected: bool,
    calibrated_state: str,
) -> str:
    if dominant_signal == "contradiction" and contradiction_label:
        return f"Lo que mas condiciona el caso hoy es aclarar {contradiction_label}."
    if dominant_signal == "blocking_issue" and blocking_label:
        return f"El punto que mas pesa ahora es resolver {blocking_label}."
    if dominant_signal == "urgency" and urgency_detected:
        return "Lo que mas pesa hoy es no demorar una medida util frente a la urgencia del caso."
    if dominant_signal == "critical_missing" and critical_gap_label:
        return f"El punto mas sensible hoy es sostener {critical_gap_label}."
    if dominant_signal == "practical_risk":
        if important_gap_label:
            return f"Lo que mas ordena la decision ahora es evitar el riesgo practico de avanzar sin {important_gap_label}."
        return "Lo que mas pesa hoy es evitar un movimiento que deje el caso mal orientado en lo practico."
    if dominant_signal == "actionability" and calibrated_state in {"action_ready", "guarded_action"}:
        return "Lo que mas pesa hoy es que ya hay base suficiente para mover el caso de forma concreta."
    if primary_focus_label:
        return f"El foco que mas ordena el caso ahora es {primary_focus_label}."
    if evidence_label:
        return f"Tu posicion mejora bastante si podes sostener {evidence_label}."
    return ""


def _build_practical_risk(
    *,
    calibrated_state: str,
    contradiction_label: str,
    blocking_label: str,
    critical_gap_label: str,
    important_gap_label: str,
    urgency_detected: bool,
) -> str:
    if contradiction_label:
        return f"El riesgo practico es avanzar con una inconsistencia en {contradiction_label}."
    if blocking_label:
        return f"El riesgo practico es que {blocking_label} siga frenando el movimiento del caso."
    if urgency_detected and calibrated_state == "guarded_action":
        return "El riesgo practico es perder tiempo util si no se toma una medida inmediata, aunque todavia falten precisiones."
    if critical_gap_label and calibrated_state == "blocked":
        return f"El riesgo practico es avanzar sin {critical_gap_label} y dejar el planteo mal sostenido."
    if important_gap_label:
        return f"El riesgo practico es discutir el fondo sin reforzar antes {important_gap_label}."
    return ""


def _build_blocking_issue(
    *,
    calibrated_state: str,
    contradiction_label: str,
    blocking_label: str,
    critical_gap_label: str,
    followup_need: str,
    followup_question: str,
) -> str:
    if contradiction_label:
        return f"Antes de afirmar una estrategia cerrada, conviene despejar la contradiccion sobre {contradiction_label}."
    if blocking_label:
        return f"Antes de avanzar con firmeza, conviene resolver {blocking_label}."
    if calibrated_state == "blocked" and critical_gap_label:
        return f"Hoy falta cerrar {critical_gap_label} para que el siguiente paso no quede flojo."
    if calibrated_state == "prudent" and followup_question and followup_need:
        return f"Todavia conviene precisar {followup_need} para orientar mejor la decision."
    return ""


def _build_best_next_move(
    *,
    decision_intent: str,
    calibrated_state: str,
    followup_need: str,
    followup_question: str,
    primary_step_label: str,
    quick_start: str,
    primary_focus_label: str,
    urgency_detected: bool,
) -> str:
    if decision_intent == "block":
        if followup_need:
            return f"Cerrar primero el dato pendiente sobre {followup_need}."
        if followup_question:
            return "Responder primero la pregunta pendiente."
    if decision_intent == "clarify":
        if followup_need:
            return f"Precisar ahora {followup_need} para orientar mejor el siguiente movimiento."
        if followup_question:
            return "Responder la pregunta pendiente para afinar la orientacion."
    if decision_intent == "prepare":
        if primary_focus_label:
            return f"Ordenar primero {primary_focus_label}."
        if followup_need:
            return f"Ordenar la base sobre {followup_need} antes de avanzar."
        if primary_step_label:
            return f"Preparar la base necesaria para {primary_step_label.rstrip('.') }."
    if decision_intent == "act_with_guardrails":
        if primary_step_label:
            return f"{primary_step_label.rstrip('.')} con resguardos sobre el punto todavia abierto."
        if urgency_detected and quick_start:
            return f"{_simplify_action_text(quick_start).rstrip('.')} con prudencia sobre el fondo."
    if decision_intent == "act" or calibrated_state == "action_ready":
        if primary_step_label:
            return primary_step_label
        if quick_start:
            return _simplify_action_text(quick_start)
    if primary_focus_label:
        return f"Ordenar primero {primary_focus_label}."
    return primary_step_label or _simplify_action_text(quick_start)


def _build_why_this_matters_now(
    *,
    calibrated_state: str,
    contradiction_label: str,
    blocking_label: str,
    critical_gap_label: str,
    important_gap_label: str,
    urgency_detected: bool,
    primary_step_reason: str,
    primary_focus_reason: str,
    actionability: str,
    practical_risk: str,
) -> str:
    if urgency_detected and calibrated_state == "action_ready":
        return "Porque el contexto ya muestra urgencia real y conviene actuar urgente antes de que la situacion se agrave."
    if calibrated_state == "blocked":
        if contradiction_label:
            return f"Porque mientras siga dudoso {contradiction_label}, cualquier paso posterior puede quedar mal orientado."
        if blocking_label:
            return f"Porque sin resolver {blocking_label}, el caso sigue frenado en lo practico."
        if critical_gap_label:
            return f"Porque sin {critical_gap_label}, el reclamo puede quedar debil o mal enfocado."
    if calibrated_state == "guarded_action":
        if urgency_detected:
            return "Porque hoy conviene mover una accion concreta sin esperar completitud total, pero manteniendo prudencia sobre el fondo."
        if practical_risk:
            return practical_risk
    if actionability == "ready_to_act":
        return "Porque ya hay base suficiente para pasar de ordenamiento a accion sin abrir mas frentes."
    if primary_step_reason:
        return _short_reason(primary_step_reason)
    if primary_focus_reason:
        return _short_reason(primary_focus_reason)
    if important_gap_label:
        return f"Porque cerrar {important_gap_label} mejora bastante la solidez del proximo movimiento."
    return ""


def _build_followup_why(
    *,
    followup_question: str,
    contradiction_label: str,
    critical_gap_label: str,
    blocking_label: str,
    followup_need: str,
    calibrated_state: str,
) -> str:
    if not followup_question:
        return ""
    if contradiction_label:
        return f"Esto sirve para confirmar {contradiction_label} antes de apoyar la orientacion en un dato dudoso."
    if blocking_label:
        return f"Esto ayuda a destrabar {blocking_label} antes de mover el caso."
    if critical_gap_label:
        return f"Esto permite cerrar {critical_gap_label}, que hoy condiciona el siguiente paso."
    if calibrated_state == "prudent" and followup_need:
        return f"Esto ayuda a definir {followup_need} sin frenar por completo la orientacion principal."
    if followup_need:
        return f"Esto ayuda a definir {followup_need} sin desviar la orientacion principal."
    return "Esto permite afinar el punto que hoy mas condiciona la recomendacion."


def _build_strengthens_position(
    *,
    calibrated_state: str,
    evidence_label: str,
    primary_step_reason: str,
    narrative_known: str,
) -> str:
    if calibrated_state == "action_ready":
        return "La posicion ya tiene una base util para pasar a una accion concreta."
    if evidence_label:
        return f"La posicion se fortalece si podes sostener {evidence_label}."
    if primary_step_reason:
        return _short_reason(primary_step_reason)
    if narrative_known:
        return _short_reason(narrative_known)
    return ""


def _build_weakens_position(
    *,
    contradiction_label: str,
    blocking_label: str,
    critical_gap_label: str,
    important_gap_label: str,
    calibration: dict[str, Any],
) -> str:
    if contradiction_label:
        return f"Lo que mas debilita hoy la posicion es la inconsistencia sobre {contradiction_label}."
    if blocking_label:
        return f"Lo que mas debilita hoy la posicion es no haber resuelto {blocking_label}."
    if critical_gap_label and calibration["blocking_severity"] in {"hard", "medium"}:
        return f"Lo que mas debilita hoy la posicion es no poder sostener {critical_gap_label}."
    if important_gap_label:
        return f"Lo que todavia queda flojo es {important_gap_label}."
    return ""


def _build_missing_to_strengthen(
    *,
    critical_gap_label: str,
    important_gap_label: str,
    evidence_label: str,
    calibrated_state: str,
) -> str:
    if calibrated_state == "blocked" and critical_gap_label:
        return f"Para sostener mejor la posicion, conviene cerrar {critical_gap_label}."
    if evidence_label:
        return f"Para sostener mejor la posicion, conviene reunir {evidence_label}."
    if important_gap_label:
        return f"Para sostener mejor la posicion, conviene definir {important_gap_label}."
    return ""


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _first_action(items: list[Any]) -> dict[str, Any]:
    for item in items:
        if isinstance(item, dict):
            return dict(item)
    return {}


def _action_label(item: dict[str, Any]) -> str:
    return _simplify_action_text(_clean_text(item.get("title")) or _clean_text(item.get("description")))


def _first_item_label(items: list[Any]) -> str:
    for item in items:
        if isinstance(item, dict):
            text = (
                _clean_text(item.get("label"))
                or _clean_text(item.get("summary"))
                or _clean_text(item.get("title"))
                or _humanize_need_key(_clean_text(item.get("key")))
                or _clean_text(item.get("reason"))
            )
            if text:
                return _strip_terminal_period(text)
        else:
            text = _clean_text(item)
            if text:
                return _strip_terminal_period(text)
    return ""


def _strip_terminal_period(text: str) -> str:
    return re.sub(r"[.]+$", "", _clean_text(text))


def _humanize_need_key(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if "::" in text:
        text = text.split("::", 1)[1]
    return text.replace("_", " ").replace("-", " ").strip()


def _simplify_action_text(text: str) -> str:
    value = _clean_text(text)
    if not value:
        return ""
    value = re.sub(r"^primer paso recomendado:\s*", "", value, flags=re.IGNORECASE)
    value = value.split("\n", 1)[0].strip()
    if ":" in value:
        _, tail = value.split(":", 1)
        if tail.strip():
            value = tail.strip()
    if not re.search(r"[.!?]$", value):
        value = f"{value}."
    return value


def _detect_urgency(
    *,
    quick_start: str,
    response_text: str,
    primary_focus_label: str,
    primary_step_label: str,
    strategy_mode: str,
    handoff_reason: str,
) -> bool:
    joined = " ".join(
        item.lower()
        for item in (
            quick_start,
            response_text,
            primary_focus_label,
            primary_step_label,
            strategy_mode,
            handoff_reason,
        )
        if item
    )
    return any(pattern in joined for pattern in _URGENT_PATTERNS)


def _detect_practical_risk(
    *,
    response_text: str,
    primary_focus_reason: str,
    primary_step_reason: str,
    handoff_reason: str,
) -> bool:
    joined = " ".join(
        item.lower()
        for item in (response_text, primary_focus_reason, primary_step_reason, handoff_reason)
        if item
    )
    return any(pattern in joined for pattern in _PRACTICAL_RISK_PATTERNS)


def _short_reason(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", cleaned)[0].strip()
    if sentence and len(sentence) <= 150:
        return sentence
    shortened = sentence[:147].rstrip()
    if not shortened.endswith("."):
        shortened += "..."
    return shortened


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = re.sub(r"\W+", " ", text.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
