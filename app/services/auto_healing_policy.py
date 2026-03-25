# backend/app/services/auto_healing_policy.py
"""
Política de auto-healing: lectura de señales, clasificación de situación
y decisión de acciones.

Responsabilidades:
1. Recoger señales operativas del sistema
2. Clasificar la situación actual (normal/degraded/unstable/critical/recovering)
3. Decidir qué acciones recomendar o aplicar
4. Respetar precedencia: hard_safety > human_control > auto_healing

Principios:
- Conservador por defecto
- Endurecer es fácil, relajar cuesta más
- Toda decisión es explicable
- Acciones fuera de allowlist se rechazan
"""

from __future__ import annotations

from datetime import timedelta
from threading import Lock
from typing import Any

from app.services.auto_healing_constants import (
    ACTION_ACTIVATE_PROTECTIVE,
    ACTION_ENFORCE_REVIEW_REQUIRED,
    ACTION_HARDEN_PROTECTIVE,
    ACTION_RECOMMEND_AUTO,
    ACTION_RECOMMEND_MANUAL_ONLY,
    ACTION_RECOMMEND_REVIEW_REQUIRED,
    ACTION_RELAX_PROTECTIVE,
    ACTION_SUSPEND_AUTO_TUNING,
    ALLOWED_ACTIONS,
    AUTO_APPLY_ACTIONS,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CRITICAL_ERROR_COUNT,
    CRITICAL_FALLBACK_COUNT,
    CRITICAL_REJECTED_COUNT,
    DEGRADED_ERROR_COUNT,
    DEGRADED_FALLBACK_COUNT,
    DEGRADED_REJECTED_COUNT,
    DEGRADED_STALE_REVIEWS,
    EVALUATION_COOLDOWN_SECONDS,
    MODES_THAT_BLOCK_AUTO_HEALING,
    MODES_THAT_BLOCK_RELAXATION,
    RECOVERY_CONSECUTIVE_EVALUATIONS,
    RECOVERY_MAX_ERROR_COUNT,
    RECOVERY_MAX_FALLBACK_COUNT,
    RECOVERY_MAX_STALE_REVIEWS,
    SITUATION_ACTION_MAP,
    SITUATION_CRITICAL,
    SITUATION_DEGRADED,
    SITUATION_NORMAL,
    SITUATION_RECOVERING,
    SITUATION_SEVERITY_RANK,
    SITUATION_UNSTABLE,
    UNSTABLE_ERROR_COUNT,
    UNSTABLE_FALLBACK_COUNT,
    UNSTABLE_HIGH_PRIORITY_REVIEWS,
    UNSTABLE_REJECTED_COUNT,
    UNSTABLE_STALE_REVIEWS,
)
from app.services.utc import utc_now


# ─── Estado interno de recuperación ──────────────────────────────────────────

_state_lock = Lock()
_previous_situation: str = SITUATION_NORMAL
_recovery_counter: int = 0
_last_evaluation_at: float | None = None


def reset_policy_state() -> None:
    """Reset estado interno — para tests."""
    global _previous_situation, _recovery_counter, _last_evaluation_at
    with _state_lock:
        _previous_situation = SITUATION_NORMAL
        _recovery_counter = 0
        _last_evaluation_at = None


# ─── Recolección de señales ──────────────────────────────────────────────────

def collect_signals(
    *,
    safety_snapshot: dict[str, Any],
    human_control_snapshot: dict[str, Any],
    system_mode: str,
    protective_mode_status: dict[str, Any],
) -> dict[str, Any]:
    """
    Recolecta y normaliza señales operativas del sistema.

    Todas las señales son numéricas o booleanas para facilitar
    la clasificación determinística.
    """
    pending_by_priority = human_control_snapshot.get("pending_reviews_by_priority") or {}
    return {
        # Safety signals
        "fallback_triggered_count": int(safety_snapshot.get("fallback_triggered_count", 0)),
        "error_like_events_count": int(safety_snapshot.get("error_like_events_count", 0)),
        "degraded_requests_count": int(safety_snapshot.get("degraded_requests_count", 0)),
        "rate_limited_requests_count": int(safety_snapshot.get("rate_limited_requests_count", 0)),
        "rejected_inputs_count": int(safety_snapshot.get("rejected_inputs_count", 0)),
        "total_safety_events": int(safety_snapshot.get("total_safety_events", 0)),
        "active_safety_status": str(safety_snapshot.get("active_safety_status") or "normal"),
        # Human control signals
        "stale_reviews_count": int(human_control_snapshot.get("stale_reviews_count", 0)),
        "high_priority_reviews": int(pending_by_priority.get("high", 0)),
        "pending_reviews": int(human_control_snapshot.get("pending_reviews", 0)),
        "overrides_active": int(human_control_snapshot.get("overrides_active", 0)),
        "human_interventions_last_24h": int(human_control_snapshot.get("human_interventions_last_24h", 0)),
        # System state
        "system_mode": str(system_mode),
        "protective_mode_active": bool(protective_mode_status.get("protective_mode_active", False)),
        "breaker_error_count": int(protective_mode_status.get("error_count", 0)),
        "breaker_degraded_count": int(protective_mode_status.get("degraded_count", 0)),
    }


# ─── Clasificación de situación ──────────────────────────────────────────────

def classify_situation(signals: dict[str, Any]) -> tuple[str, str]:
    """
    Clasifica la situación actual del sistema.

    Returns:
        (situation, reason) — e.g. ("critical", "error_like_events_count=8 >= 7")
    """
    errors = signals["error_like_events_count"]
    fallbacks = signals["fallback_triggered_count"]
    rejected = signals["rejected_inputs_count"]
    stale = signals["stale_reviews_count"]
    high_reviews = signals["high_priority_reviews"]
    protective = signals["protective_mode_active"]

    # Critical: umbrales altos
    if errors >= CRITICAL_ERROR_COUNT:
        return SITUATION_CRITICAL, f"error_like_events_count={errors} >= {CRITICAL_ERROR_COUNT}"
    if fallbacks >= CRITICAL_FALLBACK_COUNT:
        return SITUATION_CRITICAL, f"fallback_triggered_count={fallbacks} >= {CRITICAL_FALLBACK_COUNT}"
    if rejected >= CRITICAL_REJECTED_COUNT:
        return SITUATION_CRITICAL, f"rejected_inputs_count={rejected} >= {CRITICAL_REJECTED_COUNT}"

    # Unstable: umbrales medios
    if errors >= UNSTABLE_ERROR_COUNT:
        return SITUATION_UNSTABLE, f"error_like_events_count={errors} >= {UNSTABLE_ERROR_COUNT}"
    if fallbacks >= UNSTABLE_FALLBACK_COUNT:
        return SITUATION_UNSTABLE, f"fallback_triggered_count={fallbacks} >= {UNSTABLE_FALLBACK_COUNT}"
    if rejected >= UNSTABLE_REJECTED_COUNT:
        return SITUATION_UNSTABLE, f"rejected_inputs_count={rejected} >= {UNSTABLE_REJECTED_COUNT}"
    if high_reviews >= UNSTABLE_HIGH_PRIORITY_REVIEWS:
        return SITUATION_UNSTABLE, f"high_priority_reviews={high_reviews} >= {UNSTABLE_HIGH_PRIORITY_REVIEWS}"
    if stale >= UNSTABLE_STALE_REVIEWS:
        return SITUATION_UNSTABLE, f"stale_reviews_count={stale} >= {UNSTABLE_STALE_REVIEWS}"

    # Degraded: umbrales bajos
    if errors >= DEGRADED_ERROR_COUNT:
        return SITUATION_DEGRADED, f"error_like_events_count={errors} >= {DEGRADED_ERROR_COUNT}"
    if fallbacks >= DEGRADED_FALLBACK_COUNT:
        return SITUATION_DEGRADED, f"fallback_triggered_count={fallbacks} >= {DEGRADED_FALLBACK_COUNT}"
    if rejected >= DEGRADED_REJECTED_COUNT:
        return SITUATION_DEGRADED, f"rejected_inputs_count={rejected} >= {DEGRADED_REJECTED_COUNT}"
    if stale >= DEGRADED_STALE_REVIEWS:
        return SITUATION_DEGRADED, f"stale_reviews_count={stale} >= {DEGRADED_STALE_REVIEWS}"
    if protective:
        return SITUATION_DEGRADED, "protective_mode still active"

    return SITUATION_NORMAL, "all signals within normal range"


def _check_recovery(
    raw_situation: str,
    signals: dict[str, Any],
) -> tuple[str, str, int]:
    """
    Evalúa si el sistema está en recuperación sostenida.

    La recuperación se detecta cuando:
    1. La situación previa era peor que la actual
    2. Las señales actuales están por debajo de los umbrales de recuperación
    3. Se ha mantenido esta mejora por RECOVERY_CONSECUTIVE_EVALUATIONS

    Returns:
        (final_situation, reason, recovery_counter)
    """
    global _previous_situation, _recovery_counter

    prev_rank = SITUATION_SEVERITY_RANK.get(_previous_situation, 0)
    current_rank = SITUATION_SEVERITY_RANK.get(raw_situation, 0)

    # ¿Mejoró respecto a la evaluación anterior?
    is_improving = current_rank < prev_rank and prev_rank >= SITUATION_SEVERITY_RANK[SITUATION_DEGRADED]

    # ¿Las señales están lo suficientemente bajas para considerarlo recuperación?
    signals_low = (
        signals["error_like_events_count"] <= RECOVERY_MAX_ERROR_COUNT
        and signals["fallback_triggered_count"] <= RECOVERY_MAX_FALLBACK_COUNT
        and signals["stale_reviews_count"] <= RECOVERY_MAX_STALE_REVIEWS
    )

    if is_improving and signals_low:
        new_counter = _recovery_counter + 1
    elif raw_situation == SITUATION_NORMAL and _recovery_counter > 0 and signals_low:
        # Sigue normal y con señales bajas, mantiene el counter
        new_counter = _recovery_counter + 1
    else:
        new_counter = 0

    if new_counter >= RECOVERY_CONSECUTIVE_EVALUATIONS and raw_situation == SITUATION_NORMAL:
        reason = (
            f"sustained recovery for {new_counter} consecutive evaluations "
            f"(previous: {_previous_situation})"
        )
        return SITUATION_RECOVERING, reason, new_counter

    return raw_situation, "", new_counter


# ─── Decisión de acciones ────────────────────────────────────────────────────

def decide_actions(
    *,
    situation: str,
    signals: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Decide qué acciones tomar según la situación y señales.

    Returns:
        Lista de acciones con: action_type, confidence, reason, rollback_plan, should_apply
    """
    system_mode = signals["system_mode"]
    protective_active = signals["protective_mode_active"]
    overrides_active = signals["overrides_active"]

    # Frozen bloquea todo auto-healing
    if system_mode in MODES_THAT_BLOCK_AUTO_HEALING:
        return []

    candidate_actions = SITUATION_ACTION_MAP.get(situation, [])
    if not candidate_actions:
        return []

    actions: list[dict[str, Any]] = []

    for action_type in candidate_actions:
        if action_type not in ALLOWED_ACTIONS:
            continue

        action = _evaluate_single_action(
            action_type=action_type,
            situation=situation,
            signals=signals,
            system_mode=system_mode,
            protective_active=protective_active,
            overrides_active=overrides_active,
        )
        if action is not None:
            actions.append(action)

    return actions


def _evaluate_single_action(
    *,
    action_type: str,
    situation: str,
    signals: dict[str, Any],
    system_mode: str,
    protective_active: bool,
    overrides_active: int,
) -> dict[str, Any] | None:
    """Evalúa si una acción individual es pertinente."""

    # ── Acciones de endurecimiento ──

    if action_type == ACTION_ACTIVATE_PROTECTIVE:
        if protective_active:
            return None  # ya activo
        return {
            "action_type": action_type,
            "confidence": CONFIDENCE_HIGH if situation == SITUATION_UNSTABLE else CONFIDENCE_MEDIUM,
            "reason": f"activating protective mode due to {situation} situation",
            "rollback_plan": "protective mode auto-recovers via breaker cooldown",
            "should_apply": situation in (SITUATION_UNSTABLE, SITUATION_CRITICAL),
        }

    if action_type == ACTION_HARDEN_PROTECTIVE:
        if not protective_active:
            return None  # no tiene sentido endurecer si no está activo
        return {
            "action_type": action_type,
            "confidence": CONFIDENCE_HIGH if situation == SITUATION_CRITICAL else CONFIDENCE_MEDIUM,
            "reason": f"hardening protective mode: {situation} with protective already active",
            "rollback_plan": "protective mode returns to normal after breaker cooldown",
            "should_apply": situation == SITUATION_CRITICAL,
        }

    if action_type == ACTION_ENFORCE_REVIEW_REQUIRED:
        if system_mode in ("review_required", "manual_only", "frozen"):
            return None  # ya igual o más estricto
        return {
            "action_type": action_type,
            "confidence": CONFIDENCE_HIGH,
            "reason": f"enforcing review_required: system is {situation}",
            "rollback_plan": "system_mode can be changed back to auto via human control",
            "should_apply": True,
        }

    if action_type == ACTION_RECOMMEND_REVIEW_REQUIRED:
        if system_mode in ("review_required", "manual_only", "frozen"):
            return None
        return {
            "action_type": action_type,
            "confidence": CONFIDENCE_MEDIUM,
            "reason": f"recommending review_required: {situation} signals detected",
            "rollback_plan": "recommendation only, no automatic change",
            "should_apply": False,  # siempre recomendación
        }

    if action_type == ACTION_RECOMMEND_MANUAL_ONLY:
        if system_mode in ("manual_only", "frozen"):
            return None
        has_conflicts = overrides_active >= 3
        reason_parts = [f"situation={situation}"]
        if has_conflicts:
            reason_parts.append(f"overrides_active={overrides_active}")
        return {
            "action_type": action_type,
            "confidence": CONFIDENCE_MEDIUM if has_conflicts else CONFIDENCE_LOW,
            "reason": f"recommending manual_only: {', '.join(reason_parts)}",
            "rollback_plan": "recommendation only, no automatic change",
            "should_apply": False,  # nunca auto-apply
        }

    if action_type == ACTION_SUSPEND_AUTO_TUNING:
        if system_mode in ("manual_only", "frozen"):
            return None  # ya suspendido de facto
        return {
            "action_type": action_type,
            "confidence": CONFIDENCE_HIGH if situation == SITUATION_CRITICAL else CONFIDENCE_MEDIUM,
            "reason": f"suspending auto-tuning: {situation} situation detected",
            "rollback_plan": "override expires after configured cycles",
            "should_apply": situation in (SITUATION_UNSTABLE, SITUATION_CRITICAL),
        }

    # ── Acciones de relajación ──

    if action_type == ACTION_RELAX_PROTECTIVE:
        if not protective_active:
            return None  # nada que relajar
        if system_mode in MODES_THAT_BLOCK_RELAXATION:
            return None  # no relajar en frozen/manual_only
        return {
            "action_type": action_type,
            "confidence": CONFIDENCE_HIGH,
            "reason": "sustained recovery detected, relaxing protective mode",
            "rollback_plan": "protective mode re-activates if conditions worsen",
            "should_apply": True,
        }

    if action_type == ACTION_RECOMMEND_AUTO:
        if system_mode in MODES_THAT_BLOCK_RELAXATION:
            return None
        if system_mode == "auto":
            return None  # ya en auto
        return {
            "action_type": action_type,
            "confidence": CONFIDENCE_LOW,  # siempre baja, siempre recomendación
            "reason": "sustained recovery, auto mode may be appropriate",
            "rollback_plan": "recommendation only, human decides",
            "should_apply": False,
        }

    return None


# ─── Evaluación principal ────────────────────────────────────────────────────

def evaluate_auto_healing(
    *,
    safety_snapshot: dict[str, Any],
    human_control_snapshot: dict[str, Any],
    system_mode: str,
    protective_mode_status: dict[str, Any],
) -> dict[str, Any]:
    """
    Punto de entrada principal de la política de auto-healing.

    1. Recolecta señales
    2. Clasifica situación
    3. Detecta recuperación
    4. Decide acciones
    5. Actualiza estado interno

    Returns dict con:
        - situation, previous_situation, reason
        - actions (list)
        - signals (dict)
        - recovery_counter
        - cooldown_skipped (bool)
    """
    global _previous_situation, _recovery_counter, _last_evaluation_at
    now = utc_now()

    # Cooldown check
    with _state_lock:
        if _last_evaluation_at is not None:
            elapsed = (now - _last_evaluation_at).total_seconds()
            if elapsed < EVALUATION_COOLDOWN_SECONDS:
                return {
                    "situation": _previous_situation,
                    "previous_situation": _previous_situation,
                    "reason": f"cooldown active ({elapsed:.0f}s < {EVALUATION_COOLDOWN_SECONDS}s)",
                    "actions": [],
                    "signals": {},
                    "recovery_counter": _recovery_counter,
                    "cooldown_skipped": True,
                }

    signals = collect_signals(
        safety_snapshot=safety_snapshot,
        human_control_snapshot=human_control_snapshot,
        system_mode=system_mode,
        protective_mode_status=protective_mode_status,
    )

    raw_situation, raw_reason = classify_situation(signals)

    with _state_lock:
        previous = _previous_situation
        final_situation, recovery_reason, new_counter = _check_recovery(raw_situation, signals)
        _recovery_counter = new_counter

        if final_situation == SITUATION_RECOVERING and recovery_reason:
            reason = recovery_reason
        else:
            reason = raw_reason

        actions = decide_actions(situation=final_situation, signals=signals)

        _previous_situation = final_situation
        _last_evaluation_at = now

    return {
        "situation": final_situation,
        "previous_situation": previous,
        "reason": reason,
        "actions": actions,
        "signals": signals,
        "recovery_counter": new_counter,
        "cooldown_skipped": False,
    }
