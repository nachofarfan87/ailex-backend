from __future__ import annotations

LIVE_ALERT_SOURCE = "live_alert_service"

LIVE_ALERT_DEFAULT_WINDOW_HOURS = 6
LIVE_ALERT_DEFAULT_EVENT_LIMIT = 200
LIVE_ALERT_MIN_WINDOW_HOURS = 1
LIVE_ALERT_MAX_WINDOW_HOURS = 72
LIVE_ALERT_MIN_EVENT_LIMIT = 20
LIVE_ALERT_MAX_EVENT_LIMIT = 1000

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

SEVERITY_ORDER: dict[str, int] = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_INFO: 2,
}

LIVE_ALERT_THRESHOLDS: dict[str, dict[str, float | int]] = {
    "resolution_drop": {
        "min_recent_conversations": 3,
        "warning_resolution_rate": 0.45,
        "critical_resolution_rate": 0.25,
        "warning_drop_delta": 0.2,
        "critical_drop_delta": 0.35,
    },
    "excessive_clarification": {
        "min_turns": 6,
        "warning_ratio": 0.65,
        "critical_ratio": 0.8,
        "warning_unnecessary_count": 2,
        "critical_unnecessary_count": 4,
    },
    "loop_risk": {
        "warning_loop_conversations": 1,
        "critical_loop_conversations": 2,
        "warning_repeat_questions": 2,
        "critical_repeat_questions": 4,
    },
    "repeated_missing_fact_pattern": {
        "warning_count": 3,
        "critical_count": 5,
    },
    "spike_in_protective_mode": {
        "warning_events": 2,
        "critical_events": 4,
        "warning_ratio": 0.2,
        "critical_ratio": 0.35,
        "warning_spike_delta": 0.15,
        "critical_spike_delta": 0.25,
    },
    "low_confidence_cluster": {
        "min_actions": 5,
        "low_confidence_threshold": 0.5,
        "warning_ratio": 0.35,
        "critical_ratio": 0.55,
        "warning_count": 3,
        "critical_count": 6,
    },
    "family_specific_degradation": {
        "min_observations": 3,
        "warning_avg_score": -0.25,
        "critical_avg_score": -0.5,
        "warning_regressed_ratio": 0.4,
        "critical_regressed_ratio": 0.6,
    },
    "signature_specific_regression": {
        "min_observations": 3,
        "warning_avg_score": -0.35,
        "critical_avg_score": -0.6,
        "warning_regressed_ratio": 0.5,
        "critical_regressed_ratio": 0.75,
    },
    "high_review_queue_pressure": {
        "warning_pending_reviews": 4,
        "critical_pending_reviews": 8,
        "warning_stale_reviews": 2,
        "critical_stale_reviews": 4,
        "warning_oldest_hours": 24,
        "critical_oldest_hours": 72,
        "warning_high_priority": 2,
        "critical_high_priority": 4,
    },
    "auto_healing_hardening_event": {
        "warning_count": 1,
        "critical_count": 2,
    },
    "repeated_hardening": {
        "warning_count": 2,
        "critical_count": 4,
    },
}

