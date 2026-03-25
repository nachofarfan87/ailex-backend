from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import User
from app.services import self_tuning_service
from app.services.self_tuning_human_control import get_human_control_snapshot
from app.services.self_tuning_override_service import (
    clear_override,
    create_override,
    get_active_overrides,
    get_system_mode,
    set_system_mode,
)
from app.services.self_tuning_review_service import (
    approve_review,
    get_review_queue,
    override_review,
    reject_review,
)


router = APIRouter(prefix="/api/learning", tags=["Learning Control"])


class ReviewDecisionRequest(BaseModel):
    notes: str | None = None


class ReviewOverrideRequest(BaseModel):
    forced_action: str | None = None
    forced_delta: float | None = None
    block_completely: bool = False
    notes: str | None = None


class SystemModeRequest(BaseModel):
    mode: str = Field(pattern="^(auto|review_required|manual_only|frozen)$")
    notes: str | None = None


class ActiveOverrideRequest(BaseModel):
    override_type: str = Field(pattern="^(freeze_parameter|block_parameter|force_action)$")
    parameter_name: str | None = None
    forced_action: str | None = None
    duration_cycles: int | None = Field(default=None, ge=1, le=50)
    reason: str | None = None


@router.get("/review-queue")
def get_learning_review_queue(
    review_status: str = Query(default="pending"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return {
        "items": get_review_queue(db, review_status=review_status, limit=limit),
        "control_summary": get_human_control_snapshot(db),
    }


@router.post("/review/{review_id}/approve")
def approve_learning_review(
    review_id: str,
    payload: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return approve_review(db, review_id=review_id, actor=user, notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/review/{review_id}/reject")
def reject_learning_review(
    review_id: str,
    payload: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return reject_review(db, review_id=review_id, actor=user, notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/review/{review_id}/override")
def override_learning_review(
    review_id: str,
    payload: ReviewOverrideRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return override_review(
            db,
            review_id=review_id,
            actor=user,
            forced_action=payload.forced_action,
            forced_delta=payload.forced_delta,
            block_completely=payload.block_completely,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/self-tuning/control")
def get_self_tuning_control_state(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return {
        **get_human_control_snapshot(db),
        "system_mode": get_system_mode(),
        "overrides": get_active_overrides(),
        "latest_cycle": self_tuning_service.get_latest_self_tuning_cycle(db) or {},
    }


@router.post("/self-tuning/system-mode")
def update_self_tuning_system_mode(
    payload: SystemModeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        state = set_system_mode(db, mode=payload.mode, actor=user, notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "status": "updated",
        "system_mode": state.get("system_mode"),
        "control_summary": get_human_control_snapshot(db),
    }


@router.post("/self-tuning/overrides")
def create_self_tuning_override(
    payload: ActiveOverrideRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        override = create_override(
            db,
            override_type=payload.override_type,
            parameter_name=payload.parameter_name,
            forced_action=payload.forced_action,
            duration_cycles=payload.duration_cycles,
            reason=payload.reason,
            actor=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "status": "created",
        "override": override,
        "control_summary": get_human_control_snapshot(db),
    }


@router.post("/self-tuning/overrides/{override_id}/clear")
def clear_self_tuning_override(
    override_id: str,
    payload: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        state = clear_override(db, override_id=override_id, actor=user, notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "status": "cleared",
        "system_mode": state.get("system_mode"),
        "overrides": state.get("active_overrides") or [],
        "control_summary": get_human_control_snapshot(db),
    }
