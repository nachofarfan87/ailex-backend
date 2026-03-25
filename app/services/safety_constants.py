"""
safety_constants.py — Configuracion centralizada de la capa de safety.

Fuente unica de constantes, thresholds y limites para:
- input guardrails
- usage guardrails
- safety classification
- circuit breaker / protective mode
- observability windows

Todos los valores tienen defaults prudentes para operacion beta.
"""

from __future__ import annotations


# ─── Input guardrails ──────────────────────────────────────────────────────────

MIN_QUERY_LENGTH = 4
MAX_QUERY_LENGTH = 3500
HARD_REJECT_QUERY_LENGTH = 12000
MAX_REPEATED_CHAR_RATIO = 0.65
MAX_SINGLE_TOKEN_DOMINANCE = 0.8
MAX_REPEATED_CHAR_RUN = 24

# ─── Usage guardrails / rate limits ────────────────────────────────────────────

USAGE_GUARDRAIL_LIMITS: dict[str, dict[str, int]] = {
    "heavy_query": {
        "limit": 50,
        "window_seconds": 60,
        "burst_limit": 3,
        "burst_window_seconds": 3,
    },
    "read": {
        "limit": 120,
        "window_seconds": 60,
        "burst_limit": 3,
        "burst_window_seconds": 2,
    },
    "control": {
        "limit": 30,
        "window_seconds": 60,
        "burst_limit": 2,
        "burst_window_seconds": 2,
    },
}

# ─── Safety severity classification ───────────────────────────────────────────

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

# event_type → default severity
EVENT_TYPE_SEVERITY: dict[str, str] = {
    "input_rejected": "warning",
    "rate_limited": "warning",
    "request_degraded": "warning",
    "fallback_triggered": "warning",
    "excluded_from_learning": "info",
}

# safety_status overrides (higher priority than event_type)
SAFETY_STATUS_SEVERITY_OVERRIDE: dict[str, str] = {
    "input_rejected": "warning",
    "rate_limited": "warning",
    "degraded": "warning",
}

# fallback_type → severity bump
FALLBACK_TYPE_SEVERITY: dict[str, str] = {
    "internal_error": "critical",
    "timeout": "critical",
    "input_invalid": "warning",
    "rate_limited": "warning",
    "degraded_mode": "warning",
    "insufficient_data": "info",
}

# ─── Safety status priority (lower = more severe) ─────────────────────────────

SAFETY_STATUS_PRIORITY: dict[str, int] = {
    "input_rejected": 0,
    "rate_limited": 1,
    "degraded": 2,
    "fallback": 3,
    "normal": 4,
}

FALLBACK_TYPE_VALUES: set[str] = {
    "input_invalid",
    "rate_limited",
    "insufficient_data",
    "internal_error",
    "degraded_mode",
    "timeout",
}

# ─── Circuit breaker / protective mode ─────────────────────────────────────────

BREAKER_WINDOW_SECONDS = 300          # 5 min sliding window
BREAKER_ERROR_THRESHOLD = 5           # error-like events to trigger
BREAKER_DEGRADED_THRESHOLD = 8        # degraded events to trigger
BREAKER_COOLDOWN_SECONDS = 120        # auto-recovery after this period
BREAKER_INPUT_LENGTH_REDUCTION = 0.7  # reduce MAX_QUERY_LENGTH by this factor

# event_types considered "error-like" for breaker
BREAKER_ERROR_EVENT_TYPES: set[str] = {
    "fallback_triggered",
}

# fallback_types considered "error-like" for breaker
BREAKER_ERROR_FALLBACK_TYPES: set[str] = {
    "internal_error",
    "timeout",
}

# event_types considered "degraded" for breaker
BREAKER_DEGRADED_EVENT_TYPES: set[str] = {
    "request_degraded",
    "fallback_triggered",
    "rate_limited",
}

# ─── Observability windows ─────────────────────────────────────────────────────

RECENT_SAFETY_WINDOW_HOURS = 24
DEFAULT_RECENT_LIMIT = 10
