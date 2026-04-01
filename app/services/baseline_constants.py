from __future__ import annotations

BASELINE_SOURCE = "baseline_service"

BASELINE_DEFAULT_LOOKBACK_DAYS = 14
BASELINE_MIN_LOOKBACK_DAYS = 3
BASELINE_MAX_LOOKBACK_DAYS = 90

BASELINE_MIN_GLOBAL_BUCKET_SAMPLES = 3
BASELINE_HIGH_CONFIDENCE_BUCKET_SAMPLES = 6

BASELINE_MIN_SEGMENT_OBSERVATIONS = 5
BASELINE_HIGH_CONFIDENCE_SEGMENT_OBSERVATIONS = 12

BASELINE_METRIC_DIRECTIONS: dict[str, str] = {
    "resolution_rate": "down",
    "clarification_ratio": "up",
    "loop_rate": "up",
    "protective_mode_ratio": "up",
    "low_confidence_ratio": "up",
    "hardening_rate": "up",
    "family_avg_score": "down",
    "family_regressed_ratio": "up",
    "signature_avg_score": "down",
    "signature_regressed_ratio": "up",
}

DRIFT_METRIC_THRESHOLDS: dict[str, dict[str, float | int]] = {
    "resolution_rate": {
        "min_recent_sample": 3,
        "warning_abs_delta": 0.15,
        "critical_abs_delta": 0.3,
        "warning_rel_delta": 0.25,
        "critical_rel_delta": 0.45,
    },
    "clarification_ratio": {
        "min_recent_sample": 6,
        "warning_abs_delta": 0.12,
        "critical_abs_delta": 0.22,
        "warning_rel_delta": 0.2,
        "critical_rel_delta": 0.35,
    },
    "loop_rate": {
        "min_recent_sample": 3,
        "warning_abs_delta": 0.15,
        "critical_abs_delta": 0.3,
        "warning_rel_delta": 0.3,
        "critical_rel_delta": 0.5,
    },
    "protective_mode_ratio": {
        "min_recent_sample": 2,
        "warning_abs_delta": 0.12,
        "critical_abs_delta": 0.22,
        "warning_rel_delta": 0.3,
        "critical_rel_delta": 0.5,
    },
    "low_confidence_ratio": {
        "min_recent_sample": 5,
        "warning_abs_delta": 0.1,
        "critical_abs_delta": 0.2,
        "warning_rel_delta": 0.25,
        "critical_rel_delta": 0.45,
    },
    "hardening_rate": {
        "min_recent_sample": 1,
        "warning_abs_delta": 0.08,
        "critical_abs_delta": 0.18,
        "warning_rel_delta": 0.35,
        "critical_rel_delta": 0.6,
    },
    "family_avg_score": {
        "min_recent_sample": 3,
        "warning_abs_delta": 0.2,
        "critical_abs_delta": 0.35,
        "warning_rel_delta": 0.25,
        "critical_rel_delta": 0.45,
    },
    "family_regressed_ratio": {
        "min_recent_sample": 3,
        "warning_abs_delta": 0.12,
        "critical_abs_delta": 0.22,
        "warning_rel_delta": 0.25,
        "critical_rel_delta": 0.4,
    },
    "signature_avg_score": {
        "min_recent_sample": 3,
        "warning_abs_delta": 0.2,
        "critical_abs_delta": 0.35,
        "warning_rel_delta": 0.25,
        "critical_rel_delta": 0.45,
    },
    "signature_regressed_ratio": {
        "min_recent_sample": 3,
        "warning_abs_delta": 0.15,
        "critical_abs_delta": 0.25,
        "warning_rel_delta": 0.25,
        "critical_rel_delta": 0.45,
    },
}
