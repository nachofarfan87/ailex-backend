"""
GET /api/monitoring/beta-dashboard

Endpoint agregador liviano para el dashboard de monitoreo beta.
Reune health, safety, human-control y review-queue en un solo payload
con alertas computadas listas para UI.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config import settings
from app.db.database import get_db
from app.db.user_models import User
from app.services.learning_safety_service import get_safety_snapshot
from app.services.safety_classifier import get_protective_mode_status
from app.services.self_tuning_human_control import get_human_control_snapshot
from app.services.auto_healing_service import get_auto_healing_snapshot
from app.services.self_tuning_override_service import get_active_overrides, get_system_mode
from app.services.self_tuning_review_service import get_review_queue


router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])

REVIEW_PREVIEW_LIMIT = 10


def _build_alerts(
    *,
    safety: dict[str, Any],
    control: dict[str, Any],
    system_mode: str,
) -> list[dict[str, str]]:
    """Genera alertas rapidas a partir del estado actual."""
    alerts: list[dict[str, str]] = []

    if system_mode == "frozen":
        alerts.append({"level": "critical", "message": "Sistema FROZEN — no se ejecutan ajustes"})
    elif system_mode == "manual_only":
        alerts.append({"level": "warning", "message": "Sistema en modo MANUAL ONLY"})

    active_status = str(safety.get("active_safety_status") or "normal")
    if active_status == "input_rejected":
        alerts.append({"level": "critical", "message": "Safety: inputs rechazados detectados"})
    elif active_status == "rate_limited":
        alerts.append({"level": "warning", "message": "Safety: rate limiting activo"})
    elif active_status == "degraded":
        alerts.append({"level": "warning", "message": "Safety: modo degradado activo"})

    high_priority = int((control.get("pending_reviews_by_priority") or {}).get("high", 0))
    if high_priority > 0:
        alerts.append({"level": "critical", "message": f"{high_priority} review(s) HIGH priority pendiente(s)"})

    stale = int(control.get("stale_reviews_count", 0))
    if stale > 0:
        alerts.append({"level": "warning", "message": f"{stale} review(s) stale — requieren atencion"})

    overrides_active = int(control.get("overrides_active", 0))
    if overrides_active > 0:
        alerts.append({"level": "info", "message": f"{overrides_active} override(s) activo(s)"})

    rejected = int(safety.get("rejected_inputs_count", 0))
    if rejected > 0 and active_status != "input_rejected":
        alerts.append({"level": "warning", "message": f"{rejected} input(s) rechazado(s) en las ultimas 24h"})

    if safety.get("protective_mode_active"):
        alerts.append({"level": "critical", "message": f"Protective mode activo: {safety.get('protective_mode_reason', 'threshold exceeded')}"})

    return alerts


def _compute_health_status(
    *,
    safety_status: str,
    system_mode: str,
    pending_reviews: int,
    stale_reviews: int,
    protective_mode_active: bool = False,
) -> str:
    """Resuelve el estado de salud general del sistema."""
    if system_mode == "frozen":
        return "frozen"
    if protective_mode_active:
        return "degraded"
    if safety_status in ("input_rejected", "rate_limited"):
        return "degraded"
    if stale_reviews > 0 or system_mode == "manual_only":
        return "review_required"
    if pending_reviews > 0 or system_mode == "review_required":
        return "review_required"
    if safety_status == "degraded":
        return "degraded"
    return "healthy"


@router.get("/beta-dashboard")
def get_beta_dashboard(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    safety = get_safety_snapshot(db, last_hours=24, recent_limit=5)
    control = get_human_control_snapshot(db)
    system_mode = get_system_mode()
    overrides = get_active_overrides()
    review_items = get_review_queue(db, review_status="pending", limit=REVIEW_PREVIEW_LIMIT)
    pm_status = get_protective_mode_status()

    safety_status = str(safety.get("active_safety_status") or "normal")
    pending_reviews = int(control.get("pending_reviews", 0))
    stale_reviews = int(control.get("stale_reviews_count", 0))
    pm_active = pm_status["protective_mode_active"]

    health_status = _compute_health_status(
        safety_status=safety_status,
        system_mode=system_mode,
        pending_reviews=pending_reviews,
        stale_reviews=stale_reviews,
        protective_mode_active=pm_active,
    )

    alerts = _build_alerts(safety=safety, control=control, system_mode=system_mode)

    return {
        "system_status": {
            "health_status": health_status,
            "system_mode": system_mode,
            "active_safety_status": safety_status,
            "protective_mode_active": pm_active,
            "app_version": settings.app_version,
            "human_interventions_last_24h": control.get("human_interventions_last_24h", 0),
            "review_queue_size": control.get("review_queue_size", 0),
            "pending_reviews": pending_reviews,
            "overrides_active": control.get("overrides_active", 0),
        },
        "safety_summary": {
            "rejected_inputs_count": safety.get("rejected_inputs_count", 0),
            "degraded_requests_count": safety.get("degraded_requests_count", 0),
            "rate_limited_requests_count": safety.get("rate_limited_requests_count", 0),
            "excluded_from_learning_count": safety.get("excluded_from_learning_count", 0),
            "error_like_events_count": safety.get("error_like_events_count", 0),
            "fallback_triggered_count": safety.get("fallback_triggered_count", 0),
            "total_safety_events": safety.get("total_safety_events", 0),
            "excluded_from_learning_rate": safety.get("excluded_from_learning_rate", 0.0),
            "severity_breakdown": safety.get("severity_breakdown", {}),
            "fallback_type_breakdown": safety.get("fallback_type_breakdown", {}),
            "protective_mode_active": pm_active,
            "protective_mode_reason": pm_status.get("protective_mode_reason"),
            "dominant_safety_reason": safety.get("dominant_safety_reason"),
            "top_safety_reasons": safety.get("top_safety_reasons", []),
            "recent_safety_events": safety.get("recent_safety_events", []),
        },
        "human_control": {
            "system_mode": system_mode,
            "pending_reviews_by_priority": control.get("pending_reviews_by_priority", {}),
            "stale_reviews_count": stale_reviews,
            "oldest_pending_review_hours": control.get("oldest_pending_review_hours", 0),
            "approval_rate": control.get("approval_rate", 0),
            "rejection_rate": control.get("rejection_rate", 0),
            "override_rate": control.get("override_rate", 0),
            "active_override_summary": control.get("active_override_summary", {}),
            "overrides": overrides,
        },
        "review_queue_preview": review_items,
        "alerts": alerts,
        "auto_healing": get_auto_healing_snapshot(db, last_hours=24, recent_limit=5),
    }
