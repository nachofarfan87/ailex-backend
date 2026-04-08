# backend/app/services/decision_transparency_service.py
from __future__ import annotations

from typing import Any


def build_decision_transparency(
    *,
    context: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    judgment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_context = dict(context or {})
    safe_calibration = dict(calibration or {})
    safe_judgment = dict(judgment or {})

    contradiction_label = _clean_text(safe_context.get("contradiction_label"))
    blocking_label = _clean_text(safe_context.get("blocking_label"))
    critical_gap_label = _clean_text(safe_context.get("critical_gap_label"))
    important_gap_label = _clean_text(safe_context.get("important_gap_label"))
    evidence_label = _clean_text(safe_context.get("evidence_label"))
    followup_need = _clean_text(safe_context.get("followup_need"))
    followup_question = _clean_text(safe_context.get("followup_question"))
    primary_step_label = _clean_text(safe_context.get("primary_step_label"))
    clarification_status = _clean_text(safe_context.get("clarification_status"))
    response_quality = _clean_text(safe_context.get("response_quality"))
    response_strategy = _clean_text(safe_context.get("response_strategy"))
    canonical_slot = _clean_text(safe_context.get("canonical_slot"))
    user_cannot_answer = bool(safe_context.get("user_cannot_answer"))
    detected_loop = bool(safe_context.get("detected_loop"))
    precision_required = bool(safe_context.get("precision_required"))

    decision_intent = _clean_text(safe_calibration.get("decision_intent"))
    calibrated_state = _clean_text(safe_calibration.get("calibrated_state"))
    dominant_signal = _clean_text(safe_calibration.get("dominant_signal"))
    dominant_signal_score = _safe_int(safe_calibration.get("dominant_signal_score"))
    dominance_level = _clean_text(safe_calibration.get("dominance_level"))
    signal_scores = dict(safe_calibration.get("signal_scores") or {})
    rule_trace = _as_list(safe_calibration.get("rule_trace"))
    decision_trace = _as_list(safe_calibration.get("decision_trace"))
    decision_confidence_score = _safe_int(safe_calibration.get("decision_confidence_score"))
    decision_confidence_level = _clean_text(safe_calibration.get("decision_confidence_level"))
    confidence_clarity_score = _safe_int(safe_calibration.get("confidence_clarity_score"))
    confidence_stability_score = _safe_int(safe_calibration.get("confidence_stability_score"))
    blocking_severity = _clean_text(safe_calibration.get("blocking_severity"))
    prudence_level = _clean_text(safe_calibration.get("prudence_level"))

    driving_signals = _dedupe_texts(
        [
            _signal_to_text(signal=dominant_signal, safe_context=safe_context, safe_judgment=safe_judgment),
            _clean_text(safe_judgment.get("dominant_factor")),
            _clean_text(safe_judgment.get("strengthens_position")),
        ]
    )
    weakening_signals = _dedupe_texts(
        [
            _clean_text(safe_judgment.get("practical_risk")),
            _clean_text(safe_judgment.get("weakens_position")),
            _clean_text(safe_judgment.get("missing_to_strengthen")),
            precision_required and "La respuesta actual todavia deja abierta una ambiguedad relevante.",
            response_quality == "insufficient" and "La respuesta actual no termina de aportar el dato que destraba este punto.",
        ]
    )
    blocking_signals = _dedupe_texts(
        [
            _clean_text(safe_judgment.get("blocking_issue")),
            contradiction_label and f"Hay una contradiccion relevante sobre {contradiction_label}.",
            blocking_label and f"Hay un bloqueo relevante en {blocking_label}.",
            critical_gap_label and f"Falta un dato critico: {critical_gap_label}.",
        ]
    )
    relevant_missing = _dedupe_texts(
        [
            critical_gap_label and f"Falta cerrar {critical_gap_label}.",
            important_gap_label and f"Conviene precisar {important_gap_label}.",
            followup_need and f"La pregunta actual busca definir {followup_need}.",
        ]
    )
    contradictions = _dedupe_texts(
        [
            contradiction_label and f"Existe una tension factica sobre {contradiction_label}.",
        ]
    )
    confidence_summary = _build_confidence_summary(
        decision_confidence_level=decision_confidence_level,
        confidence_clarity_score=confidence_clarity_score,
        confidence_stability_score=confidence_stability_score,
        blocking_severity=blocking_severity,
        contradiction_label=contradiction_label,
        precision_required=precision_required,
    )
    confidence_context = {
        "summary": confidence_summary,
        "decision_confidence_score": decision_confidence_score,
        "decision_confidence_level": decision_confidence_level,
        "confidence_clarity_score": confidence_clarity_score,
        "confidence_stability_score": confidence_stability_score,
        "dominance_level": dominance_level,
        "dominant_signal_score": dominant_signal_score,
        "blocking_severity": blocking_severity,
        "prudence_level": prudence_level,
    }

    technical_trace = {
        "decision_intent": decision_intent,
        "calibrated_state": calibrated_state,
        "dominant_signal": dominant_signal,
        "dominant_signal_score": dominant_signal_score,
        "signal_scores": signal_scores,
        "decision_trace": decision_trace,
        "rule_trace": rule_trace,
        "clarification_status": clarification_status,
        "response_quality": response_quality,
        "response_strategy": response_strategy,
        "precision_required": precision_required,
        "followup_present": bool(followup_question),
        "canonical_slot": canonical_slot,
        "user_cannot_answer": user_cannot_answer,
        "detected_loop": detected_loop,
        "confidence_context": confidence_context,
    }

    professional_explanation = {
        "decision_explanation": _build_professional_explanation(
            decision_intent=decision_intent,
            calibrated_state=calibrated_state,
            dominant_signal=dominant_signal,
            confidence_summary=confidence_summary,
            contradiction_label=contradiction_label,
            critical_gap_label=critical_gap_label,
            followup_need=followup_need,
            primary_step_label=primary_step_label,
            safe_judgment=safe_judgment,
        ),
        "driving_signals": driving_signals,
        "weakening_signals": weakening_signals,
        "blocking_signals": blocking_signals,
        "relevant_missing": relevant_missing,
        "contradictions": contradictions,
        "confidence_context": confidence_summary,
    }

    user_explanation = {
        "user_why_this": _build_user_why_this(
            decision_intent=decision_intent,
            safe_judgment=safe_judgment,
        ),
        "what_limits_this": _build_user_limit(
            contradiction_label=contradiction_label,
            critical_gap_label=critical_gap_label,
            important_gap_label=important_gap_label,
            clarification_status=clarification_status,
            response_quality=response_quality,
            response_strategy=response_strategy,
            user_cannot_answer=user_cannot_answer,
            precision_required=precision_required,
            safe_judgment=safe_judgment,
        ),
        "what_would_change_this": _build_user_change_hint(
            followup_need=followup_need,
            evidence_label=evidence_label,
            contradiction_label=contradiction_label,
            primary_step_label=primary_step_label,
            clarification_status=clarification_status,
            response_quality=response_quality,
            followup_question=followup_question,
        ),
    }

    alternatives_considered = _build_alternatives_considered(
        decision_intent=decision_intent,
        contradiction_label=contradiction_label,
        critical_gap_label=critical_gap_label,
        followup_question=followup_question,
        primary_step_label=primary_step_label,
    )

    applies = bool(
        decision_trace
        or rule_trace
        or driving_signals
        or weakening_signals
        or blocking_signals
        or relevant_missing
        or contradictions
        or alternatives_considered
        or _clean_text(safe_judgment.get("dominant_factor"))
        or _clean_text(safe_judgment.get("best_next_move"))
        or _clean_text(safe_judgment.get("why_this_matters_now"))
    )

    return {
        "applies": applies,
        "technical_trace": technical_trace,
        "professional_explanation": professional_explanation,
        "user_explanation": user_explanation,
        "alternatives_considered": alternatives_considered,
    }


def _build_confidence_summary(
    *,
    decision_confidence_level: str,
    confidence_clarity_score: int | None,
    confidence_stability_score: int | None,
    blocking_severity: str,
    contradiction_label: str,
    precision_required: bool,
) -> str:
    clarity_score = _int_or_zero(confidence_clarity_score)
    stability_score = _int_or_zero(confidence_stability_score)
    if contradiction_label:
        return "La decision se entiende, pero pierde estabilidad porque hay una contradiccion relevante todavia abierta."
    if precision_required:
        return "La orientacion mantiene direccion, pero la respuesta actual todavia no alcanza para sostenerla con mas firmeza."
    if blocking_severity == "hard":
        return "La decision es prudente y su solidez esta limitada por un bloqueo fuerte."
    if decision_confidence_level == "high":
        return "La decision tiene buena claridad y tambien una base estable."
    if clarity_score > stability_score:
        return "La direccion del caso es clara, aunque la decision sigue sensible a uno o dos datos que todavia no estan cerrados."
    if stability_score > clarity_score:
        return "La decision es relativamente estable, aunque no todos los factores tienen el mismo nivel de claridad."
    return "La decision orienta bien, pero todavia no cierra todos los frentes con la misma solidez."


def _build_professional_explanation(
    *,
    decision_intent: str,
    calibrated_state: str,
    dominant_signal: str,
    confidence_summary: str,
    contradiction_label: str,
    critical_gap_label: str,
    followup_need: str,
    primary_step_label: str,
    safe_judgment: dict[str, Any],
) -> str:
    lead = _professional_lead(
        decision_intent=decision_intent,
        calibrated_state=calibrated_state,
        contradiction_label=contradiction_label,
        critical_gap_label=critical_gap_label,
    )
    if decision_intent == "block":
        if contradiction_label:
            return (
                f"{lead} evita una recomendacion firme porque la contradiccion sobre {contradiction_label} "
                f"sigue afectando el criterio aplicable. {confidence_summary}"
            ).strip()
        if critical_gap_label:
            return (
                f"{lead} no prioriza ejecutar todavia porque falta cerrar {critical_gap_label}, "
                f"y ese dato condiciona la solidez del siguiente paso. {confidence_summary}"
            ).strip()
        return (
            f"{lead} prioriza cerrar el punto que hoy bloquea el caso antes de pasar a una accion concreta. "
            f"{confidence_summary}"
        ).strip()

    if decision_intent == "clarify":
        target = followup_need or "el dato que hoy mas condiciona la orientacion"
        return (
            f"{lead} mantiene una orientacion util, pero todavia conviene precisar {target} antes de fijar un curso mas cerrado. "
            f"{confidence_summary}"
        ).strip()

    if decision_intent == "prepare":
        next_move = _clean_text(safe_judgment.get("best_next_move")) or primary_step_label
        if next_move:
            return (
                f"{lead} no se orienta a cerrar mas teoria, sino a ordenar la base para {next_move.lower()}. "
                f"{confidence_summary}"
            ).strip()
        return (
            f"{lead} prioriza ordenar la base del caso antes de forzar una accion que todavia no seria la mejor. "
            f"{confidence_summary}"
        ).strip()

    if decision_intent == "act_with_guardrails":
        next_move = _clean_text(safe_judgment.get("best_next_move")) or primary_step_label or "mover una accion concreta"
        return (
            f"{lead} prioriza {next_move.lower()} sin esperar completitud total, "
            f"porque hoy pesa mas la necesidad practica de actuar que seguir demorando el caso. {confidence_summary}"
        ).strip()

    next_move = _clean_text(safe_judgment.get("best_next_move")) or primary_step_label
    if next_move:
        return (
            f"{lead} prioriza {next_move.lower()} porque ese es el movimiento que hoy mejor ordena el caso. "
            f"{confidence_summary}"
        ).strip()
    if dominant_signal == "actionability":
        return f"{lead} ya muestra una base suficiente para una orientacion operativa razonablemente firme. {confidence_summary}".strip()
    return confidence_summary


def _build_user_why_this(
    *,
    decision_intent: str,
    safe_judgment: dict[str, Any],
) -> str:
    if decision_intent == "block":
        return _clean_text(safe_judgment.get("blocking_issue")) or "Antes de avanzar, conviene cerrar el punto que hoy deja la decision floja."
    if decision_intent == "clarify":
        return _clean_text(safe_judgment.get("followup_why")) or "Esta pregunta ayuda a definir el dato que mas puede cambiar la orientacion."
    if decision_intent == "act_with_guardrails":
        return _clean_text(safe_judgment.get("why_this_matters_now")) or "Conviene mover este paso ahora, pero sin sobreactuar lo que todavia no esta cerrado."
    return _clean_text(safe_judgment.get("why_this_matters_now")) or "Este paso se prioriza porque hoy es el que mejor hace avanzar el caso."


def _build_user_limit(
    *,
    contradiction_label: str,
    critical_gap_label: str,
    important_gap_label: str,
    clarification_status: str,
    response_quality: str,
    response_strategy: str,
    user_cannot_answer: bool,
    precision_required: bool,
    safe_judgment: dict[str, Any],
) -> str:
    if contradiction_label:
        return f"El limite principal es que todavia hay una contradiccion sobre {contradiction_label}."
    if user_cannot_answer:
        return "Con lo que pudiste aportar hasta ahora, la orientacion sigue siendo util pero no cierra todos los detalles."
    if response_strategy == "reformulate_question" or response_quality == "insufficient":
        return "La respuesta ayuda, pero todavia no termina de aclarar el dato que hoy mas cambia la orientacion."
    if precision_required or clarification_status == "ambiguous":
        return "Con esta respuesta todavia no alcanza para cerrar del todo la orientacion."
    if critical_gap_label:
        return f"La orientacion todavia depende de cerrar {critical_gap_label}."
    if important_gap_label:
        return f"Tambien conviene precisar {important_gap_label} para reforzar la decision."
    return _clean_text(safe_judgment.get("missing_to_strengthen"))


def _build_user_change_hint(
    *,
    followup_need: str,
    evidence_label: str,
    contradiction_label: str,
    primary_step_label: str,
    clarification_status: str,
    response_quality: str,
    followup_question: str,
) -> str:
    if contradiction_label:
        return f"Si se confirma {contradiction_label}, la decision puede sostenerse con mucha mas firmeza."
    if response_quality == "insufficient" and followup_question:
        return "Si se responde este punto con un poco mas de precision, la orientacion puede pasar de prudente a mucho mas concreta."
    if clarification_status == "ambiguous" and followup_question:
        return "Una respuesta un poco mas concreta a esta pregunta puede cambiar bastante la firmeza de la orientacion."
    if followup_need:
        return f"Si se define {followup_need}, se puede orientar mejor el siguiente movimiento."
    if evidence_label:
        return f"Si se suma {evidence_label}, la recomendacion gana respaldo practico."
    if primary_step_label:
        return f"Si se consolida la base actual, se puede pasar con mas seguridad a {primary_step_label.lower()}"
    return ""


def _build_alternatives_considered(
    *,
    decision_intent: str,
    contradiction_label: str,
    critical_gap_label: str,
    followup_question: str,
    primary_step_label: str,
) -> list[dict[str, str]]:
    alternatives: list[dict[str, str]] = []

    if decision_intent == "block" and primary_step_label:
        alternatives.append(
            {
                "option": primary_step_label,
                "status": "blocked",
                "reason": "No se priorizo porque primero hay que cerrar un bloqueo relevante.",
            }
        )
    elif decision_intent == "clarify" and followup_question:
        alternatives.append(
            {
                "option": "Avanzar sin responder la pregunta actual",
                "status": "not_prioritized",
                "reason": "No se priorizo porque esa aclaracion todavia puede cambiar la orientacion del caso.",
            }
        )
    elif decision_intent == "act_with_guardrails":
        alternatives.append(
            {
                "option": "Esperar completitud total antes de actuar",
                "status": "deferred",
                "reason": "No se priorizo porque hoy conviene mover una accion util con prudencia.",
            }
        )

    if contradiction_label:
        alternatives.append(
            {
                "option": f"Tomar una decision firme sobre {contradiction_label}",
                "status": "blocked",
                "reason": "No se priorizo porque la contradiccion sigue abierta.",
            }
        )
    elif critical_gap_label and decision_intent in {"block", "act_with_guardrails"}:
        alternatives.append(
            {
                "option": f"Ejecutar sin cerrar {critical_gap_label}",
                "status": "not_prioritized",
                "reason": "No se priorizo porque ese faltante todavia afecta la solidez del siguiente paso.",
            }
        )

    prioritized = _prioritize_alternatives(alternatives)
    if len(prioritized) == 1 and _alternative_is_low_value(prioritized[0]):
        return []
    return prioritized[:2]


def _signal_to_text(*, safe_context: dict[str, Any], safe_judgment: dict[str, Any], signal: str) -> str:
    contradiction_label = _clean_text(safe_context.get("contradiction_label"))
    blocking_label = _clean_text(safe_context.get("blocking_label"))
    critical_gap_label = _clean_text(safe_context.get("critical_gap_label"))
    if signal == "contradiction" and contradiction_label:
        return f"La contradiccion sobre {contradiction_label} ordena la decision."
    if signal == "blocking_issue" and blocking_label:
        return f"El bloqueo en {blocking_label} ordena la decision."
    if signal == "critical_missing" and critical_gap_label:
        return f"El faltante critico sobre {critical_gap_label} condiciona la decision."
    if signal == "urgency":
        return "La urgencia practica pesa mas que seguir refinando detalles secundarios."
    if signal == "practical_risk":
        return _clean_text(safe_judgment.get("practical_risk"))
    if signal == "actionability":
        return "La base actual ya permite mover el caso de forma concreta."
    return _clean_text(safe_judgment.get("dominant_factor"))


def _dedupe_texts(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _int_or_zero(value: int | None) -> int:
    return int(value) if isinstance(value, int) else 0


def _professional_lead(
    *,
    decision_intent: str,
    calibrated_state: str,
    contradiction_label: str,
    critical_gap_label: str,
) -> str:
    if contradiction_label:
        return "El problema hoy"
    if decision_intent == "clarify":
        return "Con lo que hay"
    if decision_intent == "prepare":
        return "En este punto"
    if decision_intent == "act_with_guardrails":
        return "Hoy conviene"
    if decision_intent == "block" or calibrated_state == "blocked" or critical_gap_label:
        return "En este punto"
    return "Hoy conviene"


def _prioritize_alternatives(alternatives: list[dict[str, str]]) -> list[dict[str, str]]:
    status_rank = {
        "blocked": 0,
        "not_prioritized": 1,
        "deferred": 2,
    }

    return sorted(
        alternatives,
        key=lambda item: (
            status_rank.get(str(item.get("status") or "").strip(), 9),
            1 if _alternative_is_generic(item) else 0,
            -len(_clean_text(item.get("reason"))),
            -len(_clean_text(item.get("option"))),
        ),
    )


def _alternative_is_generic(item: dict[str, str]) -> bool:
    option = _clean_text(item.get("option")).casefold()
    return option in {
        "esperar completitud total antes de actuar",
        "avanzar sin responder la pregunta actual",
    }


def _alternative_is_low_value(item: dict[str, str]) -> bool:
    reason = _clean_text(item.get("reason"))
    return _alternative_is_generic(item) and len(reason) < 95
