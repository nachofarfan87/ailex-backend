from __future__ import annotations


SELF_TUNING_STRATEGY_PROFILES: dict[str, dict[str, float | int | str]] = {
    "observe_only_strategy": {
        "effective_step_multiplier": 0.0,
        "effective_cooldown_multiplier": 2.0,
        "effective_budget_multiplier": 0.0,
        "effective_max_adjustments": 0,
        "effective_confidence_floor": 1.0,
        "effective_meta_strictness": "maximum",
    },
    "restricted_adjustment": {
        "effective_step_multiplier": 0.4,
        "effective_cooldown_multiplier": 2.0,
        "effective_budget_multiplier": 0.45,
        "effective_max_adjustments": 1,
        "effective_confidence_floor": 0.78,
        "effective_meta_strictness": "high",
    },
    "micro_adjustment": {
        "effective_step_multiplier": 0.5,
        "effective_cooldown_multiplier": 1.5,
        "effective_budget_multiplier": 0.6,
        "effective_max_adjustments": 1,
        "effective_confidence_floor": 0.72,
        "effective_meta_strictness": "medium_high",
    },
    "standard_adjustment": {
        "effective_step_multiplier": 1.0,
        "effective_cooldown_multiplier": 1.0,
        "effective_budget_multiplier": 1.0,
        "effective_max_adjustments": 2,
        "effective_confidence_floor": 0.66,
        "effective_meta_strictness": "baseline",
    },
}

DEFAULT_SELF_TUNING_STRATEGY_PROFILE = "micro_adjustment"

STRATEGY_CONTROL_ALLOWLIST = {
    "effective_step_multiplier",
    "effective_cooldown_multiplier",
    "effective_priority_multiplier",
    "effective_budget_multiplier",
    "effective_max_adjustments",
    "effective_confidence_floor",
    "effective_meta_strictness",
}

STRATEGY_PROFILE_ORDER = {
    "observe_only_strategy": 0,
    "restricted_adjustment": 1,
    "micro_adjustment": 2,
    "standard_adjustment": 3,
}

STRATEGY_FLOAT_MIN_RESOLUTION_RATIO = 0.25
STRATEGY_FLOAT_MAX_STEP_RATIO = 1.0
STRATEGY_INT_MIN_RESOLUTION = 1

STRATEGY_MIN_COOLDOWN_HOURS = 12
STRATEGY_MAX_COOLDOWN_HOURS = 96

STRATEGY_HYSTERESIS_WINDOW = 3
STRATEGY_RELAXATION_MIN_META_CONFIDENCE = 0.82
