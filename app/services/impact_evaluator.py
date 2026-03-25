from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_metric(payload: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in payload:
            return _safe_float(payload.get(key))
    return 0.0


def evaluate_impact(before: dict, after: dict) -> dict:
    score = 0.0

    before_fallback = _resolve_metric(before, "fallback_rate")
    after_fallback = _resolve_metric(after, "fallback_rate")
    if after_fallback < before_fallback:
        score += 0.3
    elif after_fallback > before_fallback:
        score -= 0.3

    before_confidence = _resolve_metric(before, "avg_confidence", "average_confidence")
    after_confidence = _resolve_metric(after, "avg_confidence", "average_confidence")
    if after_confidence > before_confidence:
        score += 0.3
    elif after_confidence < before_confidence:
        score -= 0.3

    before_success = _resolve_metric(before, "success_rate")
    after_success = _resolve_metric(after, "success_rate")
    if after_success > before_success:
        score += 0.4
    elif after_success < before_success:
        score -= 0.4

    if score > 0.2:
        label = "improved"
    elif score < -0.2:
        label = "regressed"
    else:
        label = "neutral"

    return {
        "impact_score": round(score, 4),
        "impact_label": label,
    }
