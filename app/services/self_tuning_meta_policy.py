from __future__ import annotations

from typing import Any

from app.services.self_tuning_meta_constants import (
    META_CONFIDENCE_LOW,
    META_CONFIDENCE_MEDIUM,
    META_CONTEXT_FRAGILE,
    META_HIGH_CONFIDENCE_BAD_OUTCOME_RATE,
    META_HIGH_UNKNOWN_OUTCOME_RATE,
    META_MIN_HISTORY_CYCLES,
    META_MIN_KNOWN_OUTCOMES,
    META_MODE_CONSERVATIVE_RATE,
    META_MODE_FAILURE_DOWNGRADE_RATE,
    META_MODE_ROLLBACK_DOWNGRADE_RATE,
    META_PARAMETER_FAILURE_BLOCK_RATE,
    META_PARAMETER_ROLLBACK_BLOCK_RATE,
    META_PARAMETER_SUCCESS_FAVOR_RATE,
    META_STRONG_HISTORY_CYCLES,
    META_STRONG_KNOWN_OUTCOMES,
    MODE_ORDER,
)


def build_meta_signals(
    *,
    strategy_memory: dict[str, Any],
    current_recommendation: dict[str, Any] | None,
    current_signals: dict[str, Any] | None,
    requested_mode: str,
) -> dict[str, Any]:
    history_window_summary = dict(strategy_memory.get("history_window_summary") or {})
    parameter_performance = dict(strategy_memory.get("parameter_performance") or {})
    mode_performance = dict(strategy_memory.get("mode_performance") or {})
    context_performance = dict(strategy_memory.get("context_performance") or {})
    candidates = list((current_recommendation or {}).get("candidate_adjustments") or [])
    actionable_candidates = [candidate for candidate in candidates if not candidate.get("blocked")]
    current_context = _resolve_current_context(current_signals=current_signals)

    parameter_assessments: dict[str, dict[str, Any]] = {}
    supportive_parameters: list[str] = []
    risky_parameters: list[str] = []
    fragile_parameters: list[str] = []

    for candidate in candidates:
        parameter_name = str(candidate.get("parameter_name") or "")
        if not parameter_name:
            continue
        performance = dict(parameter_performance.get(parameter_name) or {})
        assessment = _assess_parameter(performance=performance, current_context=current_context)
        parameter_assessments[parameter_name] = assessment
        if assessment["label"] == "supportive":
            supportive_parameters.append(parameter_name)
        elif assessment["label"] == "risky":
            risky_parameters.append(parameter_name)
        elif assessment["label"] == "fragile":
            fragile_parameters.append(parameter_name)

    current_mode_performance = dict(mode_performance.get(requested_mode) or _default_mode_performance(requested_mode))
    overall_risk_flags: list[str] = []
    if history_window_summary.get("total_cycles", 0) < META_MIN_HISTORY_CYCLES:
        overall_risk_flags.append("meta_insufficient_history")
    if history_window_summary.get("known_outcomes", 0) < META_MIN_KNOWN_OUTCOMES:
        overall_risk_flags.append("meta_insufficient_known_outcomes")
    if history_window_summary.get("unknown_outcome_rate", 0.0) >= META_HIGH_UNKNOWN_OUTCOME_RATE:
        overall_risk_flags.append("meta_high_unknown_outcome_rate")
    if history_window_summary.get("high_confidence_bad_outcome_rate", 0.0) >= META_HIGH_CONFIDENCE_BAD_OUTCOME_RATE:
        overall_risk_flags.append("meta_high_confidence_bad_outcome_rate")
    if history_window_summary.get("weighted_rollback_rate", history_window_summary.get("rollback_after_tuning_rate", 0.0)) >= META_MODE_ROLLBACK_DOWNGRADE_RATE:
        overall_risk_flags.append("meta_rollback_after_tuning_pressure")
    if float(strategy_memory.get("meta_confidence") or 0.0) < META_CONFIDENCE_LOW:
        overall_risk_flags.append("low_meta_confidence")
    elif float(strategy_memory.get("meta_confidence") or 0.0) < META_CONFIDENCE_MEDIUM:
        overall_risk_flags.append("medium_meta_confidence")

    return {
        "requested_mode": requested_mode,
        "history_window_summary": history_window_summary,
        "parameter_performance": parameter_performance,
        "mode_performance": mode_performance,
        "context_performance": context_performance,
        "current_mode_performance": current_mode_performance,
        "parameter_assessments": parameter_assessments,
        "supportive_parameters": sorted(set(supportive_parameters)),
        "risky_parameters": sorted(set(risky_parameters)),
        "fragile_parameters": sorted(set(fragile_parameters)),
        "actionable_candidates_count": len(actionable_candidates),
        "overall_risk_flags": overall_risk_flags,
        "current_signals": dict(current_signals or {}),
        "current_context": current_context,
        "meta_confidence": float(strategy_memory.get("meta_confidence") or 0.0),
        "meta_confidence_reasoning": list(strategy_memory.get("meta_confidence_reasoning") or []),
        "meta_confidence_components": dict(strategy_memory.get("meta_confidence_components") or {}),
    }


def evaluate_meta_policy(
    *,
    meta_signals: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    requested_mode = str(meta_signals.get("requested_mode") or "balanced")
    history = dict(meta_signals.get("history_window_summary") or {})
    current_mode_performance = dict(meta_signals.get("current_mode_performance") or {})
    supportive_parameters = list(meta_signals.get("supportive_parameters") or [])
    risky_parameters = list(meta_signals.get("risky_parameters") or [])
    fragile_parameters = list(meta_signals.get("fragile_parameters") or [])
    actionable_candidates_count = int(meta_signals.get("actionable_candidates_count") or 0)
    overall_risk_flags = list(meta_signals.get("overall_risk_flags") or [])
    current_signals = dict(meta_signals.get("current_signals") or {})
    current_context = str(meta_signals.get("current_context") or "stable")
    meta_confidence = float(meta_signals.get("meta_confidence") or 0.0)
    meta_confidence_reasoning = list(meta_signals.get("meta_confidence_reasoning") or [])
    meta_confidence_components = dict(meta_signals.get("meta_confidence_components") or {})

    recommended_mode = _resolve_recommended_mode(
        requested_mode=requested_mode,
        history_window_summary=history,
        current_mode_performance=current_mode_performance,
        current_signals=current_signals,
        overall_risk_flags=overall_risk_flags,
        meta_confidence=meta_confidence,
    )
    meta_risk_flags = list(overall_risk_flags)
    historical_support = {
        "supportive_parameters": supportive_parameters,
        "risky_parameters": risky_parameters,
        "fragile_parameters": fragile_parameters,
        "current_context": current_context,
        "meta_confidence": round(meta_confidence, 4),
        "meta_confidence_reasoning": meta_confidence_reasoning,
        "meta_confidence_components": meta_confidence_components,
        "mode_support": {
            "requested_mode": requested_mode,
            "recommended_mode": recommended_mode,
            "requested_mode_success_rate": round(float(current_mode_performance.get("weighted_success_rate") or current_mode_performance.get("success_rate") or 0.0), 4),
            "requested_mode_failure_rate": round(float(current_mode_performance.get("weighted_failure_rate") or current_mode_performance.get("failure_rate") or 0.0), 4),
            "requested_mode_evidence_status": str(current_mode_performance.get("evidence_status") or "insufficient_mode_evidence"),
        },
    }

    if actionable_candidates_count <= 0:
        return {
            "meta_status": "observe_only",
            "meta_reasoning": "Meta-learning sin candidatos accionables: observar historial.",
            "meta_risk_flags": meta_risk_flags,
            "recommended_mode": recommended_mode,
            "recommended_action": "observe_only",
            "historical_support": historical_support,
        }

    if risky_parameters and len(risky_parameters) >= actionable_candidates_count:
        meta_risk_flags.append("meta_all_candidates_historically_risky")
        if history.get("weighted_rollback_rate", history.get("rollback_after_tuning_rate", 0.0)) >= META_MODE_ROLLBACK_DOWNGRADE_RATE:
            return {
                "meta_status": "blocked",
                "meta_reasoning": "Meta-learning bloquea el ciclo: los parametros candidatos tienen historial riesgoso y alta presion de rollback.",
                "meta_risk_flags": list(dict.fromkeys(meta_risk_flags)),
                "recommended_mode": _more_conservative_mode(recommended_mode, "conservative"),
                "recommended_action": "block",
                "historical_support": historical_support,
            }
        return {
            "meta_status": "observe_only",
            "meta_reasoning": "Meta-learning recomienda observar: los parametros candidatos tienen historial riesgoso.",
            "meta_risk_flags": list(dict.fromkeys(meta_risk_flags)),
            "recommended_mode": _more_conservative_mode(recommended_mode, "conservative"),
            "recommended_action": "observe_only",
            "historical_support": historical_support,
        }

    if "low_meta_confidence" in meta_risk_flags and (
        "meta_high_unknown_outcome_rate" in meta_risk_flags
        or "meta_high_confidence_bad_outcome_rate" in meta_risk_flags
        or "meta_rollback_after_tuning_pressure" in meta_risk_flags
        or risky_parameters
        or fragile_parameters
    ):
        return {
            "meta_status": "low_meta_confidence",
            "meta_reasoning": "Meta-learning detecta baja confianza propia; prefiere observar o simular antes de endurecer el motor.",
            "meta_risk_flags": list(dict.fromkeys(meta_risk_flags)),
            "recommended_mode": _more_conservative_mode(recommended_mode, "conservative"),
            "recommended_action": "observe_only" if risky_parameters else "simulate",
            "historical_support": historical_support,
        }

    if "meta_insufficient_history" in meta_risk_flags or "meta_insufficient_known_outcomes" in meta_risk_flags:
        if requested_mode == "aggressive":
            return {
                "meta_status": "insufficient_meta_evidence",
                "meta_reasoning": "Meta-learning no tiene suficiente historial confiable para sostener modo aggressive; se degrada a simulacion prudente.",
                "meta_risk_flags": list(dict.fromkeys(meta_risk_flags)),
                "recommended_mode": _more_conservative_mode(recommended_mode, "balanced"),
                "recommended_action": "simulate",
                "historical_support": historical_support,
            }
        return {
            "meta_status": "cautious_support",
            "meta_reasoning": "Meta-learning tiene historial limitado; mantiene soporte prudente sin escalar agresividad.",
            "meta_risk_flags": list(dict.fromkeys(meta_risk_flags)),
            "recommended_mode": _more_conservative_mode(recommended_mode, "balanced"),
            "recommended_action": "apply" if not dry_run else "simulate",
            "historical_support": historical_support,
        }

    if (
        "meta_high_unknown_outcome_rate" in meta_risk_flags
        or "meta_high_confidence_bad_outcome_rate" in meta_risk_flags
        or fragile_parameters
    ):
        meta_risk_flags.append("meta_fragile_strategy_context")
        return {
            "meta_status": "simulate",
            "meta_reasoning": "Meta-learning detecta contexto fragil o ambiguo; conviene simular antes de aplicar.",
            "meta_risk_flags": list(dict.fromkeys(meta_risk_flags)),
            "recommended_mode": _more_conservative_mode(recommended_mode, "balanced"),
            "recommended_action": "simulate",
            "historical_support": historical_support,
        }

    if requested_mode == "aggressive" and recommended_mode != "aggressive":
        meta_risk_flags.append("meta_aggressive_mode_downgraded")
        return {
            "meta_status": "simulate",
            "meta_reasoning": "Meta-learning detecta que aggressive no tiene soporte historico suficiente; conviene degradar y simular.",
            "meta_risk_flags": list(dict.fromkeys(meta_risk_flags)),
            "recommended_mode": recommended_mode,
            "recommended_action": "simulate",
            "historical_support": historical_support,
        }

    if recommended_mode != requested_mode:
        meta_risk_flags.append("meta_mode_downgrade_recommended")

    return {
        "meta_status": "supported",
        "meta_reasoning": "Meta-learning acompana el ciclo actual con soporte historico suficiente.",
        "meta_risk_flags": list(dict.fromkeys(meta_risk_flags)),
        "recommended_mode": recommended_mode,
        "recommended_action": "apply" if not dry_run else "simulate",
        "historical_support": historical_support,
    }


def apply_meta_to_candidates(
    *,
    candidates: list[dict[str, Any]],
    parameter_assessments: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    adjusted_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        parameter_name = str(candidate.get("parameter_name") or "")
        assessment = dict(parameter_assessments.get(parameter_name) or {})
        candidate_copy = dict(candidate)
        candidate_copy["meta_assessment"] = assessment
        candidate_copy["meta_score"] = round(float(assessment.get("meta_score") or 0.0), 4)
        candidate_copy["meta_support_label"] = str(assessment.get("label") or "unknown")
        candidate_copy["meta_priority_score"] = round(
            float(candidate.get("priority_score") or 0.0) + max(float(assessment.get("meta_score") or 0.0), 0.0) * 0.15,
            4,
        )

        if not candidate_copy.get("blocked") and assessment.get("block_parameter"):
            candidate_copy["blocked"] = True
            blocked_reasons = list(candidate_copy.get("blocked_reasons") or [])
            blocked_reasons.append("meta_historically_risky_parameter")
            candidate_copy["blocked_reasons"] = list(dict.fromkeys(blocked_reasons))
            explanation = dict(candidate_copy.get("explanation") or {})
            why_not = list(explanation.get("why_not") or [])
            why_not.append("meta-learning blocked parameter due to ineffective historical support")
            explanation["why_not"] = why_not
            candidate_copy["explanation"] = explanation

        adjusted_candidates.append(candidate_copy)

    adjusted_candidates.sort(
        key=lambda item: (
            item.get("blocked", False),
            -float(item.get("meta_priority_score") or 0.0),
            -float(item.get("priority_score") or 0.0),
            item.get("parameter_name") or "",
        )
    )
    return adjusted_candidates

def _assess_parameter(*, performance: dict[str, Any], current_context: str) -> dict[str, Any]:
    known_outcomes = int(performance.get("known_outcomes") or 0)
    success_rate = float(performance.get("weighted_success_rate") or performance.get("success_rate") or 0.0)
    failure_rate = float(performance.get("weighted_failure_rate") or performance.get("failure_rate") or 0.0)
    rollback_rate = float(performance.get("weighted_rollback_rate") or performance.get("rollback_after_tuning_rate") or 0.0)
    unknown_rate = float(performance.get("weighted_unknown_outcome_rate") or performance.get("unknown_outcome_rate") or 0.0)
    meta_score = 0.0
    label = "unknown"
    block_parameter = False
    contextual_performance = dict((performance.get("context_performance") or {}).get(current_context) or {})
    contextual_failure_rate = float(contextual_performance.get("weighted_failure_rate") or 0.0)
    contextual_success_rate = float(contextual_performance.get("weighted_success_rate") or 0.0)
    contextual_meta_score = float(contextual_performance.get("context_meta_score") or 0.0)
    contextual_evidence_status = str(contextual_performance.get("evidence_status") or "insufficient_context_evidence")

    if known_outcomes >= META_MIN_KNOWN_OUTCOMES and success_rate >= META_PARAMETER_SUCCESS_FAVOR_RATE and rollback_rate <= 0.1:
        meta_score += 0.45
        label = "supportive"
    if known_outcomes >= META_MIN_KNOWN_OUTCOMES and (
        failure_rate >= META_PARAMETER_FAILURE_BLOCK_RATE or rollback_rate >= META_PARAMETER_ROLLBACK_BLOCK_RATE
    ):
        meta_score -= 0.55
        label = "risky"
        block_parameter = True
    elif performance.get("total_records", 0) >= META_MIN_HISTORY_CYCLES and unknown_rate >= META_HIGH_UNKNOWN_OUTCOME_RATE:
        meta_score -= 0.25
        label = "fragile"

    if (
        current_context == META_CONTEXT_FRAGILE
        and contextual_evidence_status == "sufficient_context_evidence"
        and contextual_failure_rate >= 0.45
    ):
        meta_score -= 0.2
        label = "risky"
        block_parameter = True
    elif (
        contextual_evidence_status == "sufficient_context_evidence"
        and contextual_success_rate >= 0.7
        and contextual_meta_score > 0
    ):
        meta_score += 0.1
    elif contextual_evidence_status != "sufficient_context_evidence":
        meta_score -= min(unknown_rate * 0.05, 0.05)

    meta_score -= min(unknown_rate * 0.2, 0.2)
    meta_score += min(success_rate * 0.15, 0.15)
    meta_score -= min(failure_rate * 0.25, 0.25)

    return {
        "label": label,
        "meta_score": round(max(-1.0, min(1.0, meta_score)), 4),
        "success_rate": round(success_rate, 4),
        "failure_rate": round(failure_rate, 4),
        "rollback_after_tuning_rate": round(rollback_rate, 4),
        "unknown_outcome_rate": round(unknown_rate, 4),
        "known_outcomes": known_outcomes,
        "block_parameter": block_parameter,
        "current_context": current_context,
        "contextual_meta_score": round(contextual_meta_score, 4),
        "contextual_evidence_status": contextual_evidence_status,
    }


def _resolve_recommended_mode(
    *,
    requested_mode: str,
    history_window_summary: dict[str, Any],
    current_mode_performance: dict[str, Any],
    current_signals: dict[str, Any],
    overall_risk_flags: list[str],
    meta_confidence: float,
) -> str:
    recommended_mode = requested_mode if requested_mode in MODE_ORDER else "balanced"
    failure_rate = float(current_mode_performance.get("weighted_failure_rate") or current_mode_performance.get("failure_rate") or 0.0)
    rollback_rate = float(current_mode_performance.get("weighted_rollback_rate") or current_mode_performance.get("rollback_after_tuning_rate") or 0.0)
    success_rate = float(current_mode_performance.get("weighted_success_rate") or current_mode_performance.get("success_rate") or 0.0)
    total_cycles = int(history_window_summary.get("total_cycles") or 0)
    known_outcomes = float(history_window_summary.get("weighted_known_outcomes") or history_window_summary.get("known_outcomes") or 0)
    trend_stability = float(current_signals.get("trend_stability") or 0.0)
    consistency = float(current_signals.get("consistency") or 0.0)
    evidence_status = str(current_mode_performance.get("evidence_status") or "insufficient_mode_evidence")

    if requested_mode == "aggressive":
        if (
            failure_rate >= META_MODE_CONSERVATIVE_RATE
            or rollback_rate >= META_MODE_ROLLBACK_DOWNGRADE_RATE
            or "meta_rollback_after_tuning_pressure" in overall_risk_flags
            or evidence_status == "insufficient_mode_evidence"
            or meta_confidence < META_CONFIDENCE_MEDIUM
        ):
            return "conservative"
        if (
            total_cycles < META_STRONG_HISTORY_CYCLES
            or known_outcomes < META_STRONG_KNOWN_OUTCOMES
            or success_rate < 0.75
            or trend_stability < 0.75
            or consistency < 0.78
            or meta_confidence < META_CONFIDENCE_MEDIUM
        ):
            return "balanced"
        return "aggressive"

    if failure_rate >= META_MODE_FAILURE_DOWNGRADE_RATE or rollback_rate >= META_MODE_ROLLBACK_DOWNGRADE_RATE:
        return _more_conservative_mode(recommended_mode, "conservative")

    if "meta_high_unknown_outcome_rate" in overall_risk_flags or evidence_status == "insufficient_mode_evidence":
        return _more_conservative_mode(recommended_mode, "balanced")

    return recommended_mode


def _more_conservative_mode(current_mode: str, candidate_mode: str) -> str:
    current_rank = MODE_ORDER.get(current_mode, MODE_ORDER["balanced"])
    candidate_rank = MODE_ORDER.get(candidate_mode, MODE_ORDER["balanced"])
    if candidate_rank < current_rank:
        return candidate_mode
    return current_mode


def _resolve_current_context(*, current_signals: dict[str, Any] | None) -> str:
    current_signals = dict(current_signals or {})
    rollback_ratio = float(current_signals.get("rollback_ratio") or 0.0)
    drift_level = str(current_signals.get("drift_level") or "none").strip().lower()
    sample_size = int(current_signals.get("sample_size") or 0)
    trend_stability = float(current_signals.get("trend_stability") or 0.0)
    consistency = float(current_signals.get("consistency") or 0.0)
    if rollback_ratio >= META_MODE_ROLLBACK_DOWNGRADE_RATE:
        return "rollback_pressure"
    if drift_level in {"high", "medium"}:
        return "drift_context"
    if sample_size and sample_size < 40:
        return "low_evidence_context"
    if trend_stability < 0.6 or consistency < 0.6:
        return META_CONTEXT_FRAGILE
    return "stable"


def _default_mode_performance(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "total_cycles": 0,
        "known_outcomes": 0,
        "success_rate": 0.0,
        "failure_rate": 0.0,
        "weighted_success_rate": 0.0,
        "weighted_failure_rate": 0.0,
        "weighted_rollback_rate": 0.0,
        "rollback_after_tuning_rate": 0.0,
        "unknown_outcome_rate": 1.0,
        "weighted_unknown_outcome_rate": 1.0,
        "evidence_status": "insufficient_mode_evidence",
    }
