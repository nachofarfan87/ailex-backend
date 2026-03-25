"""
safety_classifier.py — Clasificacion de severidad y circuit breaker prudente.

Responsabilidades:
1. Clasificar severity (info/warning/critical) para cada evento/outcome
2. Evaluar condicion de protective mode (circuit breaker)
3. Aplicar endurecimiento liviano cuando protective mode esta activo

Principios:
- Prudente, no destructivo
- Reversible automaticamente
- Explicable y auditable
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from threading import Lock
from typing import Any

from app.services.safety_constants import (
    BREAKER_COOLDOWN_SECONDS,
    BREAKER_DEGRADED_EVENT_TYPES,
    BREAKER_DEGRADED_THRESHOLD,
    BREAKER_ERROR_EVENT_TYPES,
    BREAKER_ERROR_FALLBACK_TYPES,
    BREAKER_ERROR_THRESHOLD,
    BREAKER_INPUT_LENGTH_REDUCTION,
    BREAKER_WINDOW_SECONDS,
    EVENT_TYPE_SEVERITY,
    FALLBACK_TYPE_SEVERITY,
    MAX_QUERY_LENGTH,
    SAFETY_STATUS_SEVERITY_OVERRIDE,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from app.services.utc import utc_now


# ─── Severity classification ──────────────────────────────────────────────────

_SEVERITY_RANK = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_CRITICAL: 2}


def classify_severity(
    *,
    event_type: str,
    safety_status: str,
    fallback_type: str | None = None,
) -> str:
    """
    Clasifica la severidad de un evento de safety.

    Prioridad de evaluacion (de menor a mayor):
    1. event_type → default severity
    2. safety_status → override si es mas severo
    3. fallback_type → override si es mas severo
    """
    base = EVENT_TYPE_SEVERITY.get(event_type, SEVERITY_INFO)
    status_override = SAFETY_STATUS_SEVERITY_OVERRIDE.get(safety_status, SEVERITY_INFO)
    fallback_override = FALLBACK_TYPE_SEVERITY.get(str(fallback_type or ""), SEVERITY_INFO)

    candidates = [base, status_override, fallback_override]
    return max(candidates, key=lambda s: _SEVERITY_RANK.get(s, 0))


# ─── Circuit breaker / protective mode ─────────────────────────────────────────

_breaker_lock = Lock()
_breaker_events: list[dict[str, Any]] = []
_protective_mode_activated_at: float | None = None


def reset_breaker_state() -> None:
    """Reset breaker state — primarily for tests."""
    global _protective_mode_activated_at
    with _breaker_lock:
        _breaker_events.clear()
        _protective_mode_activated_at = None


def record_breaker_event(
    *,
    event_type: str,
    fallback_type: str | None = None,
) -> None:
    """Record a safety event for circuit breaker evaluation."""
    now = utc_now()
    with _breaker_lock:
        _breaker_events.append({
            "event_type": event_type,
            "fallback_type": fallback_type,
            "timestamp": now,
        })
        # Prune old events outside window
        cutoff = now - timedelta(seconds=BREAKER_WINDOW_SECONDS)
        _breaker_events[:] = [
            ev for ev in _breaker_events
            if ev["timestamp"] >= cutoff
        ]


def evaluate_protective_mode() -> dict[str, Any]:
    """
    Evalua si el circuit breaker debe activarse.

    Returns dict con:
    - protective_mode_active: bool
    - protective_mode_reason: str | None
    - protective_mode_recommended: bool
    - error_count: int
    - degraded_count: int
    - effective_max_query_length: int
    """
    global _protective_mode_activated_at
    now = utc_now()

    with _breaker_lock:
        cutoff = now - timedelta(seconds=BREAKER_WINDOW_SECONDS)
        recent = [ev for ev in _breaker_events if ev["timestamp"] >= cutoff]

        error_count = sum(
            1 for ev in recent
            if ev["event_type"] in BREAKER_ERROR_EVENT_TYPES
            and str(ev.get("fallback_type") or "") in BREAKER_ERROR_FALLBACK_TYPES
        )
        degraded_count = sum(
            1 for ev in recent
            if ev["event_type"] in BREAKER_DEGRADED_EVENT_TYPES
        )

        # Check auto-recovery
        if _protective_mode_activated_at is not None:
            elapsed = (now - _protective_mode_activated_at).total_seconds()
            if elapsed >= BREAKER_COOLDOWN_SECONDS and error_count == 0 and degraded_count < BREAKER_DEGRADED_THRESHOLD:
                _protective_mode_activated_at = None

        # Evaluate activation
        reason = None
        should_activate = False

        if error_count >= BREAKER_ERROR_THRESHOLD:
            reason = f"error_like_events_exceeded ({error_count}/{BREAKER_ERROR_THRESHOLD} in {BREAKER_WINDOW_SECONDS}s)"
            should_activate = True
        elif degraded_count >= BREAKER_DEGRADED_THRESHOLD:
            reason = f"degraded_events_exceeded ({degraded_count}/{BREAKER_DEGRADED_THRESHOLD} in {BREAKER_WINDOW_SECONDS}s)"
            should_activate = True

        if should_activate and _protective_mode_activated_at is None:
            _protective_mode_activated_at = now

        is_active = _protective_mode_activated_at is not None

        effective_max = int(MAX_QUERY_LENGTH * BREAKER_INPUT_LENGTH_REDUCTION) if is_active else MAX_QUERY_LENGTH

    return {
        "protective_mode_active": is_active,
        "protective_mode_reason": reason if is_active else None,
        "protective_mode_recommended": should_activate and not is_active,
        "error_count": error_count,
        "degraded_count": degraded_count,
        "effective_max_query_length": effective_max,
    }


def get_protective_mode_status() -> dict[str, Any]:
    """Read-only snapshot of protective mode — for observability."""
    return evaluate_protective_mode()
