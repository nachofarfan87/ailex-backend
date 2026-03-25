from __future__ import annotations


SELF_TUNING_EVENT_TYPE = "self_tuning"
SELF_TUNING_RECOMMENDATION_TYPE = "self_tuning_cycle"

MIN_EVIDENCE_SAMPLE_SIZE = 24
PREFERRED_TUNING_SAMPLE_SIZE = 40
MIN_STABLE_AUDITS = 16
MAX_ADJUSTMENTS_PER_CYCLE = 2
DEFAULT_COOLDOWN_HOURS = 24
ANTI_OSCILLATION_WINDOW_HOURS = 72
INEFFECTIVE_TUNING_LOOKBACK_HOURS = 168
TREND_STABILITY_MIN = 0.45
ROLLBACK_PRESSURE_BLOCK_RATIO = 0.08
ROLLBACK_PRESSURE_BLOCK_COUNT = 2

THRESHOLD_MIN = 0.0
THRESHOLD_MAX = 1.0
MIN_SAMPLE_DELTA_MIN = -2
MIN_SAMPLE_DELTA_MAX = 4

# ---------------------------------------------------------------------------
# FASE 8.1B — Safety Envelope & Control Layer
# ---------------------------------------------------------------------------

SELF_TUNING_SAFETY_LIMITS = {
    "max_total_delta_per_cycle": 0.08,
    "max_parameters_changed_per_cycle": 2,
    "max_delta_per_parameter_per_day": 0.12,
    "max_changes_per_window": 3,
}

SELF_TUNING_MODES: dict[str, dict] = {
    "conservative": {
        "confidence_multiplier": 0.9,
        "max_adjustments": 1,
    },
    "balanced": {
        "confidence_multiplier": 1.0,
        "max_adjustments": 2,
    },
    "aggressive": {
        "confidence_multiplier": 1.1,
        "max_adjustments": 3,
    },
}

DEFAULT_SELF_TUNING_MODE = "balanced"

TUNING_BUDGET_WINDOW_HOURS_24 = 24
TUNING_BUDGET_WINDOW_HOURS_7D = 168

GLOBAL_BLOCK_RISK_FLAGS = {
    "insufficient_data",
    "insufficient_data_for_tuning",
    "cold_start_tuning_block",
    "strong_drift",
    "mixed_evidence",
    "unstable_trend",
    "contradictory_recent_evidence",
    "rollback_pressure",
}

TUNABLE_PARAMETER_SPECS: dict[str, dict] = {
    "apply_confidence_delta": {
        "kind": "float",
        "default": 0.0,
        "min_value": -0.1,
        "max_value": 0.2,
        "step": 0.02,
        "cooldown_hours": DEFAULT_COOLDOWN_HOURS,
        "priority_weight": 1.0,
        "guardrails": {
            "max_daily_shift": 0.06,
            "max_weekly_shift": 0.12,
            "safe_zone": (-0.05, 0.12),
        },
    },
    "min_sample_size_delta": {
        "kind": "int",
        "default": 0,
        "min_value": MIN_SAMPLE_DELTA_MIN,
        "max_value": MIN_SAMPLE_DELTA_MAX,
        "step": 1,
        "cooldown_hours": DEFAULT_COOLDOWN_HOURS * 2,
        "priority_weight": 0.75,
        "guardrails": {
            "max_daily_shift": 2.0,
            "max_weekly_shift": 3.0,
            "safe_zone": (-1, 3),
        },
    },
    "uncertain_apply_confidence_min": {
        "kind": "float",
        "default": 0.15,
        "min_value": 0.1,
        "max_value": 0.35,
        "step": 0.02,
        "cooldown_hours": DEFAULT_COOLDOWN_HOURS,
        "priority_weight": 0.95,
        "guardrails": {
            "max_daily_shift": 0.06,
            "max_weekly_shift": 0.12,
            "safe_zone": (0.1, 0.3),
        },
    },
    "uncertain_apply_max_simulation_risk": {
        "kind": "float",
        "default": 0.45,
        "min_value": 0.25,
        "max_value": 0.6,
        "step": 0.03,
        "cooldown_hours": DEFAULT_COOLDOWN_HOURS,
        "priority_weight": 0.9,
        "guardrails": {
            "max_daily_shift": 0.09,
            "max_weekly_shift": 0.15,
            "safe_zone": (0.3, 0.55),
        },
    },
}
