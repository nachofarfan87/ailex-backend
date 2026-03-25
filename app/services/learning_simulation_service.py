from __future__ import annotations

from typing import Any

from app.services.observability_signal_extractor import (
    SIGNAL_DRIFT_DETECTED,
    SIGNAL_HIGH_FAILURE_RATE,
    SIGNAL_HIGH_VARIANCE,
    SIGNAL_LOW_SAMPLE_SIZE,
    SIGNAL_POSITIVE_TREND,
    SIGNAL_RECENT_REGRESSION,
    SIGNAL_STRONG_POSITIVE_CONSISTENCY,
    SIGNAL_UNSTABLE_PATTERN,
)


SIMULATION_MODE = "historical_heuristic"
IMPACT_SCORE_MIN = -1.0
IMPACT_SCORE_MAX = 1.0

# Low sample: dampen observability signal weight and cap simulation confidence.
# Consistent with FASE 5 philosophy: little evidence => don't overreact.
LOW_SAMPLE_SIGNAL_DAMPEN = 0.3
LOW_SAMPLE_CONFIDENCE_CAP = 0.45


def simulate_recommendation_outcome(
    *,
    recommendation: dict[str, Any] | None,
    impact_decision: dict[str, Any] | None,
    adaptive_decision: dict[str, Any] | None,
    observability_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    recommendation = recommendation or {}
    impact_decision = impact_decision or {}
    adaptive_decision = adaptive_decision or {}
    observability_snapshot = observability_snapshot or {}

    evidence_points = _extract_evidence_points(impact_decision)
    raw_signals = [str(signal or "") for signal in (observability_snapshot.get("signals") or [])]
    has_data = bool(observability_snapshot.get("has_data", False))
    drivers: list[str] = []
    warnings: list[str] = []

    # When has_data is False, observability signals are not trustworthy —
    # don't let them penalize the simulation. We handle the no-data case
    # explicitly via warnings and the has_data gate on signal_adjustment.
    signals = raw_signals if has_data else []

    # Low sample only meaningful when there IS some data but not enough.
    low_sample = SIGNAL_LOW_SAMPLE_SIZE in signals

    history_score = 0.0
    evidence_quality = 0.0
    if evidence_points:
        weighted_score_total = sum(point["score"] * point["weight"] for point in evidence_points)
        weight_total = sum(point["weight"] for point in evidence_points) or 1.0
        history_score = weighted_score_total / weight_total
        evidence_quality = min(sum(point["quality"] for point in evidence_points) / len(evidence_points), 1.0)
        # Low sample: historical evidence is unreliable, pull score toward zero
        if low_sample:
            history_score *= 0.5
            evidence_quality *= 0.5
            drivers.append("low_sample_history_dampened")
        drivers.append(f"historical_signal={round(history_score, 4)}")
    else:
        warnings.append("limited_historical_evidence")

    impact_modifiers = 0.0
    adaptive_adjustment = _safe_float(adaptive_decision.get("confidence_adjustment"))
    if adaptive_adjustment:
        impact_modifiers += adaptive_adjustment * 0.8
        drivers.append(f"adaptive_confidence_adjustment={round(adaptive_adjustment, 4)}")

    adaptive_risk = str(adaptive_decision.get("risk_level") or "low").strip().lower()
    if adaptive_risk == "high":
        impact_modifiers -= 0.12
        warnings.append("adaptive_high_risk")
    elif adaptive_risk == "medium":
        impact_modifiers -= 0.05

    confidence_score = _safe_float(recommendation.get("confidence_score"))
    priority = _safe_float(recommendation.get("priority"))
    impact_modifiers += (confidence_score - 0.5) * 0.25
    impact_modifiers += (priority - 0.5) * 0.15
    drivers.append(f"recommendation_confidence={round(confidence_score, 4)}")
    drivers.append(f"recommendation_priority={round(priority, 4)}")

    # Signal adjustment from observability.
    # If has_data is False, we have no observability — don't invent penalties.
    if has_data:
        signal_delta = _signal_adjustment(signals, warnings)
        # Low sample: dampen signal weight to avoid overreaction on thin evidence
        if low_sample and signal_delta:
            signal_delta = round(signal_delta * LOW_SAMPLE_SIGNAL_DAMPEN, 4)
            drivers.append("low_sample_signal_dampened")
        if signal_delta:
            impact_modifiers += signal_delta
            drivers.append(f"observability_adjustment={round(signal_delta, 4)}")
    else:
        if not evidence_points:
            warnings.append("no_observability_data")

    conflict_summary = dict(impact_decision.get("conflict_summary") or {})
    if conflict_summary.get("has_conflict"):
        impact_modifiers -= 0.08
        warnings.append("conflicting_historical_signals")
        drivers.append("conflict_summary=present")

    expected_impact_score = _clamp(history_score + impact_modifiers, IMPACT_SCORE_MIN, IMPACT_SCORE_MAX)
    confidence_result = _compute_confidence(
        evidence_quality=evidence_quality,
        recommendation_confidence=confidence_score,
        signals=signals,
        warnings=warnings,
    )

    # Low sample: hard cap on confidence — don't pretend we know more than we do
    if low_sample:
        confidence_result = min(confidence_result, LOW_SAMPLE_CONFIDENCE_CAP)
        confidence_result = round(confidence_result, 4)

    # Risk score uses signal presence as structural risk indicator.
    # Weights are moderate to avoid double-penalizing with _signal_adjustment
    # which already impacts expected_impact_score.
    risk_score = _compute_risk_score(
        adaptive_risk=adaptive_risk,
        signals=signals,
        warnings=warnings,
        confidence_score=confidence_result,
    )

    if low_sample:
        warnings.append("low_sample_evidence")
    if SIGNAL_DRIFT_DETECTED in signals:
        warnings.append("drift_detected")
    if SIGNAL_HIGH_VARIANCE in signals:
        warnings.append("high_variance")

    warnings = _dedupe(warnings)
    drivers = _dedupe(drivers)
    expected_outcome = _classify_outcome(
        score=expected_impact_score,
        confidence_score=confidence_result,
        evidence_available=bool(evidence_points),
    )
    reasoning = _build_reasoning(
        expected_outcome=expected_outcome,
        score=expected_impact_score,
        confidence_score=confidence_result,
        warnings=warnings,
    )

    return {
        "expected_outcome": expected_outcome,
        "expected_impact_score": expected_impact_score,
        "risk_score": risk_score,
        "confidence_score": confidence_result,
        "simulation_mode": SIMULATION_MODE,
        "reasoning": reasoning,
        "drivers": drivers,
        "warnings": warnings,
    }


def _extract_evidence_points(impact_decision: dict[str, Any]) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for level, weight in (("signature_evidence", 1.0), ("signature_family_evidence", 0.75), ("event_type_evidence", 0.55)):
        evidence = dict(impact_decision.get(level) or {})
        if not evidence.get("available"):
            continue
        score = _safe_float(evidence.get("score"))
        memory_confidence = _clamp(_safe_float(evidence.get("memory_confidence")), 0.0, 1.0)
        quality = memory_confidence
        if evidence.get("strong_enough"):
            quality = max(quality, 0.7)
        elif int(evidence.get("raw_total") or 0) > 0:
            quality = max(quality, 0.3)
        else:
            continue
        points.append(
            {
                "score": score,
                "weight": weight * max(quality, 0.2),
                "quality": quality,
            }
        )
    return points


def _signal_adjustment(signals: list[str], warnings: list[str]) -> float:
    """Adjust expected impact based on observability signals.

    These adjustments affect the projected score. Risk is handled separately
    in _compute_risk_score with moderate weights to avoid double-penalizing.
    """
    delta = 0.0
    if SIGNAL_POSITIVE_TREND in signals:
        delta += 0.08
    if SIGNAL_STRONG_POSITIVE_CONSISTENCY in signals:
        delta += 0.05
    if SIGNAL_RECENT_REGRESSION in signals:
        delta -= 0.15
        warnings.append("recent_regression")
    if SIGNAL_DRIFT_DETECTED in signals:
        delta -= 0.10
    if SIGNAL_HIGH_FAILURE_RATE in signals:
        delta -= 0.12
        warnings.append("high_failure_rate")
    if SIGNAL_HIGH_VARIANCE in signals:
        delta -= 0.06
    if SIGNAL_UNSTABLE_PATTERN in signals:
        delta -= 0.08
        warnings.append("unstable_pattern")
    if SIGNAL_LOW_SAMPLE_SIZE in signals:
        delta -= 0.03
    return round(delta, 4)


def _compute_confidence(
    *,
    evidence_quality: float,
    recommendation_confidence: float,
    signals: list[str],
    warnings: list[str],
) -> float:
    confidence = 0.2 + (evidence_quality * 0.5) + (_clamp(recommendation_confidence, 0.0, 1.0) * 0.2)
    if SIGNAL_LOW_SAMPLE_SIZE in signals:
        confidence -= 0.15
    if SIGNAL_DRIFT_DETECTED in signals:
        confidence -= 0.08
    if SIGNAL_HIGH_VARIANCE in signals:
        confidence -= 0.05
    if not evidence_quality:
        confidence -= 0.10
    if "limited_historical_evidence" in warnings:
        confidence -= 0.10
    return round(_clamp(confidence, 0.0, 1.0), 4)


def _compute_risk_score(
    *,
    adaptive_risk: str,
    signals: list[str],
    warnings: list[str],
    confidence_score: float,
) -> float:
    """Structural risk score.

    Signal contributions are intentionally moderate (lower than _signal_adjustment)
    to avoid disproportionate double-penalization. The score path captures projected
    impact; the risk path captures structural uncertainty.
    """
    risk = 0.2
    if adaptive_risk == "medium":
        risk += 0.15
    elif adaptive_risk == "high":
        risk += 0.30
    # Moderate weights for signals already penalizing expected_impact_score
    if SIGNAL_DRIFT_DETECTED in signals:
        risk += 0.10
    if SIGNAL_RECENT_REGRESSION in signals:
        risk += 0.12
    if SIGNAL_HIGH_FAILURE_RATE in signals:
        risk += 0.10
    if SIGNAL_HIGH_VARIANCE in signals:
        risk += 0.05
    if "conflicting_historical_signals" in warnings:
        risk += 0.08
    if confidence_score < 0.45:
        risk += 0.12
    return round(_clamp(risk, 0.0, 1.0), 4)


def _classify_outcome(*, score: float, confidence_score: float, evidence_available: bool) -> str:
    if not evidence_available or confidence_score < 0.35:
        return "uncertain"
    if score >= 0.2:
        return "positive"
    if score <= -0.2:
        return "negative"
    return "neutral"


def _build_reasoning(
    *,
    expected_outcome: str,
    score: float,
    confidence_score: float,
    warnings: list[str],
) -> str:
    if expected_outcome == "uncertain":
        return (
            "Simulacion incierta por evidencia limitada o confianza insuficiente "
            f"(score={score}, confidence={confidence_score})"
        )
    if warnings:
        return (
            f"Simulacion {expected_outcome} con cautelas activas "
            f"(score={score}, confidence={confidence_score}, warnings={','.join(warnings[:3])})"
        )
    return f"Simulacion {expected_outcome} basada en evidencia historica y senales actuales (score={score}, confidence={confidence_score})"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return round(max(min_value, min(max_value, value)), 4)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result
