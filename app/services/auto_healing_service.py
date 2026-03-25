# backend/app/services/auto_healing_service.py
"""
Servicio de auto-healing: aplicación de acciones, auditoría y snapshot.

Responsabilidades:
1. Ejecutar el ciclo de auto-healing (evaluar → decidir → aplicar → auditar)
2. Aplicar acciones automáticas respetando allowlist y precedencia
3. Persistir cada decisión como AutoHealingEvent
4. Exponer snapshot operativo para monitoreo

Principios:
- hard_safety > human_control > auto_healing
- frozen nunca se levanta automáticamente
- human override nunca se pisa
- toda acción queda auditada
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.auto_healing_event import AutoHealingEvent
from app.services.auto_healing_constants import (
    ACTION_ACTIVATE_PROTECTIVE,
    ACTION_ENFORCE_REVIEW_REQUIRED,
    ACTION_HARDEN_PROTECTIVE,
    ACTION_RELAX_PROTECTIVE,
    ACTION_SUSPEND_AUTO_TUNING,
    ALLOWED_ACTIONS,
    AUTO_APPLY_ACTIONS,
    AUTO_HEALING_ACTOR_TAG,
    AUTO_HEALING_OVERRIDE_DURATION_CYCLES,
    CONFIDENCE_HIGH,
    FORBIDDEN_AUTO_ACTIONS,
    SITUATION_NORMAL,
)
from app.services.auto_healing_policy import (
    evaluate_auto_healing,
    reset_policy_state,
)
from app.services.safety_classifier import (
    get_protective_mode_status,
    record_breaker_event,
    reset_breaker_state,
)
from app.services.utc import utc_now


# ─── Aplicación de acciones ──────────────────────────────────────────────────

def _apply_action(
    db: Session,
    action: dict[str, Any],
    signals: dict[str, Any],
) -> dict[str, Any]:
    """
    Aplica una acción auto-healing concreta al sistema.

    Solo aplica si:
    1. La acción está en ALLOWED_ACTIONS
    2. La acción está en AUTO_APPLY_ACTIONS
    3. La acción NO está en FORBIDDEN_AUTO_ACTIONS
    4. should_apply es True
    5. confidence es suficiente

    Returns dict con resultado de la aplicación.
    """
    action_type = action["action_type"]
    should_apply = action.get("should_apply", False)
    confidence = action.get("confidence", "low")

    # Validaciones de seguridad
    if action_type in FORBIDDEN_AUTO_ACTIONS:
        return {"applied": False, "reason": "action is in FORBIDDEN_AUTO_ACTIONS"}
    if action_type not in ALLOWED_ACTIONS:
        return {"applied": False, "reason": "action not in ALLOWED_ACTIONS"}
    if not should_apply:
        return {"applied": False, "reason": "action is recommendation only"}
    if action_type in AUTO_APPLY_ACTIONS and confidence != CONFIDENCE_HIGH:
        # Para auto-apply, requerir alta confianza
        if action_type not in (ACTION_ENFORCE_REVIEW_REQUIRED,):
            return {"applied": False, "reason": f"confidence={confidence}, need high for auto-apply"}

    # Aplicar según tipo
    if action_type == ACTION_ACTIVATE_PROTECTIVE:
        return _apply_activate_protective()

    if action_type == ACTION_HARDEN_PROTECTIVE:
        return _apply_harden_protective()

    if action_type == ACTION_ENFORCE_REVIEW_REQUIRED:
        return _apply_enforce_review_required(db)

    if action_type == ACTION_SUSPEND_AUTO_TUNING:
        return _apply_suspend_auto_tuning(db)

    if action_type == ACTION_RELAX_PROTECTIVE:
        return _apply_relax_protective()

    return {"applied": False, "reason": f"no handler for action_type={action_type}"}


def _apply_activate_protective() -> dict[str, Any]:
    """Activa protective mode alimentando errores al breaker."""
    # Alimentar el breaker con eventos sintéticos para activar protective mode
    for _ in range(6):
        record_breaker_event(event_type="fallback_triggered", fallback_type="internal_error")
    pm = get_protective_mode_status()
    return {
        "applied": pm["protective_mode_active"],
        "reason": "fed breaker events to trigger protective mode",
        "protective_mode_active": pm["protective_mode_active"],
    }


def _apply_harden_protective() -> dict[str, Any]:
    """Refuerza protective mode alimentando más eventos al breaker."""
    for _ in range(3):
        record_breaker_event(event_type="fallback_triggered", fallback_type="internal_error")
    pm = get_protective_mode_status()
    return {
        "applied": True,
        "reason": "fed additional breaker events to maintain/harden protective mode",
        "protective_mode_active": pm["protective_mode_active"],
        "effective_max_query_length": pm["effective_max_query_length"],
    }


def _apply_enforce_review_required(db: Session) -> dict[str, Any]:
    """Cambia system_mode a review_required."""
    from app.services.self_tuning_override_service import get_system_mode, set_system_mode

    current = get_system_mode()
    if current in ("review_required", "manual_only", "frozen"):
        return {"applied": False, "reason": f"system_mode already {current}, no change needed"}

    result = set_system_mode(
        db,
        mode="review_required",
        actor=None,
        notes=f"[{AUTO_HEALING_ACTOR_TAG}] auto-healing enforced review_required",
    )
    return {
        "applied": True,
        "reason": f"changed system_mode from {current} to review_required",
        "previous_mode": current,
        "new_mode": result.get("system_mode", "review_required"),
    }


def _apply_suspend_auto_tuning(db: Session) -> dict[str, Any]:
    """Crea un override para suspender auto-tuning."""
    from app.services.self_tuning_override_service import create_override, get_active_overrides

    # Verificar si ya hay un override de auto-healing activo
    existing = get_active_overrides()
    for ov in existing:
        if str(ov.get("reason") or "").startswith(f"[{AUTO_HEALING_ACTOR_TAG}]"):
            return {"applied": False, "reason": "auto-healing override already active"}

    result = create_override(
        db,
        override_type="freeze_parameter",
        parameter_name="apply_confidence_delta",
        forced_action="block",
        duration_cycles=AUTO_HEALING_OVERRIDE_DURATION_CYCLES,
        reason=f"[{AUTO_HEALING_ACTOR_TAG}] auto-tuning suspended due to system instability",
        actor=None,
    )
    return {
        "applied": True,
        "reason": "created freeze override on apply_confidence_delta",
        "override_id": result.get("override", {}).get("id"),
    }


def _apply_relax_protective() -> dict[str, Any]:
    """Relaja protective mode reseteando el estado del breaker."""
    reset_breaker_state()
    pm = get_protective_mode_status()
    return {
        "applied": not pm["protective_mode_active"],
        "reason": "reset breaker state to relax protective mode",
        "protective_mode_active": pm["protective_mode_active"],
    }


# ─── Ciclo principal ─────────────────────────────────────────────────────────

def run_auto_healing_cycle(
    db: Session,
    *,
    safety_snapshot: dict[str, Any],
    human_control_snapshot: dict[str, Any],
    system_mode: str,
    protective_mode_status: dict[str, Any],
) -> dict[str, Any]:
    """
    Ejecuta un ciclo completo de auto-healing:
    1. Evalúa la política
    2. Aplica acciones permitidas
    3. Audita cada decisión
    4. Retorna resultado completo

    Returns dict con:
        - situation, previous_situation, reason
        - actions_taken (list con resultado por acción)
        - signals
        - recovery_counter
        - cooldown_skipped
    """
    evaluation = evaluate_auto_healing(
        safety_snapshot=safety_snapshot,
        human_control_snapshot=human_control_snapshot,
        system_mode=system_mode,
        protective_mode_status=protective_mode_status,
    )

    if evaluation["cooldown_skipped"]:
        return evaluation

    actions_taken: list[dict[str, Any]] = []

    for action in evaluation.get("actions", []):
        action_type = action["action_type"]
        should_apply = action.get("should_apply", False) and action_type in AUTO_APPLY_ACTIONS

        if should_apply:
            result = _apply_action(db, action, evaluation["signals"])
        else:
            result = {"applied": False, "reason": "recommendation only"}

        action_record = {
            **action,
            "result": result,
            "applied": result.get("applied", False),
        }
        actions_taken.append(action_record)

        # Auditar cada acción
        _persist_healing_event(
            db,
            situation=evaluation["situation"],
            previous_situation=evaluation["previous_situation"],
            action=action_record,
            signals=evaluation["signals"],
            system_mode=system_mode,
            protective_mode_active=evaluation["signals"].get("protective_mode_active", False),
        )

    evaluation["actions_taken"] = actions_taken
    return evaluation


def _persist_healing_event(
    db: Session,
    *,
    situation: str,
    previous_situation: str,
    action: dict[str, Any],
    signals: dict[str, Any],
    system_mode: str,
    protective_mode_active: bool,
) -> AutoHealingEvent | None:
    """Persiste un evento de auto-healing a la DB."""
    if not all(hasattr(db, attr) for attr in ("add", "commit", "refresh")):
        return None

    event = AutoHealingEvent(
        situation=situation,
        previous_situation=previous_situation,
        action_type=action["action_type"],
        action_applied=action.get("applied", False),
        confidence=action.get("confidence", "low"),
        reason=action.get("reason", ""),
        rollback_plan=action.get("rollback_plan", ""),
        signals_json=json.dumps(signals, default=str),
        result_json=json.dumps(action.get("result", {}), default=str),
        system_mode=system_mode,
        protective_mode_active=protective_mode_active,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ─── Snapshot para monitoreo ─────────────────────────────────────────────────

def get_auto_healing_snapshot(
    db: Session,
    *,
    last_hours: int = 24,
    recent_limit: int = 10,
) -> dict[str, Any]:
    """
    Genera un snapshot operativo de auto-healing.

    Incluye:
    - Estado actual del sistema auto-healing
    - Eventos recientes
    - Estadísticas de acciones
    - Estado de recuperación
    """
    from app.services.auto_healing_policy import (
        _previous_situation,
        _recovery_counter,
    )
    from app.services.self_tuning_override_service import get_system_mode

    since = utc_now() - timedelta(hours=max(last_hours, 1))

    recent_events = (
        db.query(AutoHealingEvent)
        .filter(AutoHealingEvent.created_at >= since)
        .order_by(AutoHealingEvent.created_at.desc())
        .limit(max(recent_limit, 1))
        .all()
    )

    all_events = (
        db.query(AutoHealingEvent)
        .filter(AutoHealingEvent.created_at >= since)
        .all()
    )

    total_events = len(all_events)
    applied_count = sum(1 for ev in all_events if ev.action_applied)
    recommended_count = total_events - applied_count

    # Breakdown por acción
    action_breakdown: dict[str, int] = {}
    for ev in all_events:
        action_breakdown[ev.action_type] = action_breakdown.get(ev.action_type, 0) + 1

    # Breakdown por situación
    situation_breakdown: dict[str, int] = {}
    for ev in all_events:
        situation_breakdown[ev.situation] = situation_breakdown.get(ev.situation, 0) + 1

    pm_status = get_protective_mode_status()
    current_mode = get_system_mode()

    return {
        "auto_healing_status": _previous_situation,
        "recovery_counter": _recovery_counter,
        "system_mode_effective": current_mode,
        "protective_mode_active": pm_status["protective_mode_active"],
        "recovery_progress": min(_recovery_counter / 3.0, 1.0) if _recovery_counter > 0 else 0.0,
        "total_events_last_24h": total_events,
        "applied_actions_count": applied_count,
        "recommended_actions_count": recommended_count,
        "action_breakdown": action_breakdown,
        "situation_breakdown": situation_breakdown,
        "recent_auto_healing_events": [ev.to_dict() for ev in recent_events],
    }
