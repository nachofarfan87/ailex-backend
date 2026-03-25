from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import User
from app.services import adaptive_learning_service, learning_metrics_service, orchestrator_config_service


router = APIRouter(prefix="/api/adaptive-learning", tags=["Adaptive Learning"])


class TuningEventSummaryResponse(BaseModel):
    id: str
    event_type: str
    status: str
    title: str
    priority: float
    effective_priority: float = 0.0
    confidence_score: float
    evaluation_status: str


class AdaptiveDriftSummaryResponse(BaseModel):
    applied_events: int = 0
    evaluation_counts: dict[str, int] = Field(default_factory=dict)
    improvement_rate: float = 0.0
    regression_rate: float = 0.0


class AdaptiveStatusResponse(BaseModel):
    orchestrator_config: dict = Field(default_factory=dict)
    latest_summary: dict = Field(default_factory=dict)
    proposed_events_count: int = 0
    top_priority_events_count: int = 0
    drift_summary: AdaptiveDriftSummaryResponse = Field(default_factory=AdaptiveDriftSummaryResponse)
    top_events: list[TuningEventSummaryResponse] = Field(default_factory=list)


class TuningEventResponse(BaseModel):
    id: str
    event_type: str
    status: str
    title: str
    description: str
    evidence_json: dict = Field(default_factory=dict)
    proposed_changes_json: dict = Field(default_factory=dict)
    confidence_score: float
    priority: float
    effective_priority: float = 0.0
    evaluation_status: str
    observed_effect_json: dict = Field(default_factory=dict)
    source_version: str | None = None
    target_version: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.get("/status", response_model=AdaptiveStatusResponse)
def get_adaptive_learning_status(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> AdaptiveStatusResponse:
    config = orchestrator_config_service.load_orchestrator_config().to_dict()
    summary = learning_metrics_service.get_learning_summary(db, last_hours=168)
    events = adaptive_learning_service.list_tuning_events(db, limit=100)
    drift_summary = adaptive_learning_service.get_adaptive_drift_summary(db)
    proposed_events = [item for item in events if item.get("status") == "proposed"]
    top_priority_events = [
        item
        for item in events
        if item.get("status") in {"proposed", "approved", "applied"} and float(item.get("effective_priority") or 0.0) >= 0.5
    ]
    top_events = [
        TuningEventSummaryResponse(
            id=item["id"],
            event_type=item["event_type"],
            status=item["status"],
            title=item["title"],
            priority=float(item.get("priority") or 0.0),
            effective_priority=float(item.get("effective_priority") or 0.0),
            confidence_score=float(item.get("confidence_score") or 0.0),
            evaluation_status=str(item.get("evaluation_status") or "pending"),
        )
        for item in events[:5]
    ]
    return AdaptiveStatusResponse(
        orchestrator_config=config,
        latest_summary=summary,
        proposed_events_count=len(proposed_events),
        top_priority_events_count=len(top_priority_events),
        drift_summary=AdaptiveDriftSummaryResponse(**drift_summary),
        top_events=top_events,
    )


@router.post("/analyze", response_model=list[TuningEventResponse])
def analyze_adaptive_learning(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[TuningEventResponse]:
    items = adaptive_learning_service.analyze_learning_system(db)
    return [TuningEventResponse(**item.to_dict()) for item in items]


@router.get("/events", response_model=list[TuningEventResponse])
def get_tuning_events(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[TuningEventResponse]:
    items = adaptive_learning_service.list_tuning_events(db, limit=limit)
    return [TuningEventResponse(**item) for item in items]


@router.post("/events/{event_id}/approve", response_model=TuningEventResponse)
def approve_tuning_event(
    event_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> TuningEventResponse:
    try:
        item = adaptive_learning_service.approve_tuning_event(db, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TuningEventResponse(**item)


@router.post("/events/{event_id}/reject", response_model=TuningEventResponse)
def reject_tuning_event(
    event_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> TuningEventResponse:
    try:
        item = adaptive_learning_service.reject_tuning_event(db, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TuningEventResponse(**item)


@router.post("/events/{event_id}/apply")
def apply_tuning_event(
    event_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    try:
        return adaptive_learning_service.apply_tuning_event(db, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/events/{event_id}/rollback")
def rollback_tuning_event(
    event_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    try:
        return adaptive_learning_service.rollback_tuning_event(db, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/events/{event_id}/evaluate", response_model=TuningEventResponse)
def evaluate_tuning_event(
    event_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> TuningEventResponse:
    try:
        item = adaptive_learning_service.evaluate_tuning_event_effect(db, event_id, window_hours=window_hours)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TuningEventResponse(**item)
