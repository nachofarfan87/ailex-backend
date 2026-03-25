# backend/app/api/auto_healing.py
"""
API endpoints para auto-healing.

GET /api/auto-healing/snapshot — snapshot operativo
POST /api/auto-healing/evaluate — ejecuta un ciclo de evaluación
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import User
from app.services.auto_healing_service import (
    get_auto_healing_snapshot,
    run_auto_healing_cycle,
)
from app.services.learning_safety_service import get_safety_snapshot
from app.services.safety_classifier import get_protective_mode_status
from app.services.self_tuning_human_control import get_human_control_snapshot
from app.services.self_tuning_override_service import get_system_mode


router = APIRouter(prefix="/api/auto-healing", tags=["Auto-Healing"])


@router.get("/snapshot")
def auto_healing_snapshot(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    last_hours: int = Query(default=24, ge=1, le=168),
    recent_limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Snapshot operativo del sistema de auto-healing."""
    return get_auto_healing_snapshot(db, last_hours=last_hours, recent_limit=recent_limit)


@router.post("/evaluate")
def auto_healing_evaluate(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Ejecuta un ciclo de evaluación de auto-healing.

    Lee señales actuales, clasifica la situación, decide y aplica
    acciones permitidas. Retorna resultado completo con auditoría.
    """
    safety = get_safety_snapshot(db, last_hours=24, recent_limit=5)
    control = get_human_control_snapshot(db)
    system_mode = get_system_mode()
    pm_status = get_protective_mode_status()

    result = run_auto_healing_cycle(
        db,
        safety_snapshot=safety,
        human_control_snapshot=control,
        system_mode=system_mode,
        protective_mode_status=pm_status,
    )

    return {
        "situation": result["situation"],
        "previous_situation": result["previous_situation"],
        "reason": result["reason"],
        "actions_taken": result.get("actions_taken", []),
        "recovery_counter": result.get("recovery_counter", 0),
        "cooldown_skipped": result.get("cooldown_skipped", False),
    }
