from __future__ import annotations

from typing import Any

from app.services import learning_runtime_config


MIN_CONFIDENCE = 0.65
MIN_PRIORITY = 0.60
MIN_SAMPLE_SIZE = 8
MANUAL_ONLY_EVENT_TYPES = {
    "classification_review",
    "strategy_recalibration",
    "version_alert",
}


def _resolve_sample_size(recommendation: dict[str, Any]) -> int:
    evidence = dict(recommendation.get("evidence") or {})
    for key in ("sample_size", "feedback_count", "sample_count", "affected_queries", "count"):
        value = evidence.get(key)
        try:
            if value is not None:
                return max(int(value), 0)
        except (TypeError, ValueError):
            continue
    return 0


def should_apply_recommendation(recommendation: dict) -> tuple[bool, str]:
    event_type = str(recommendation.get("event_type") or "").strip()
    confidence_score = float(recommendation.get("confidence_score") or 0.0)
    priority = float(recommendation.get("priority") or 0.0)
    sample_size = _resolve_sample_size(recommendation)
    controls = learning_runtime_config.get_self_tuning_controls()
    min_confidence = max(0.0, min(1.0, MIN_CONFIDENCE + float(controls.get("apply_confidence_delta") or 0.0)))
    min_sample_size = max(1, MIN_SAMPLE_SIZE + int(controls.get("min_sample_size_delta") or 0))

    if event_type in MANUAL_ONLY_EVENT_TYPES:
        return False, "manual_only_event_type"
    if confidence_score < min_confidence:
        return False, "below_threshold"
    if priority < MIN_PRIORITY:
        return False, "below_threshold"
    if sample_size < min_sample_size:
        return False, "below_threshold"
    return True, "eligible"
