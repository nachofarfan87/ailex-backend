from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import User
from app.models.learning_action_log import LearningActionLog
from app.services import (
    learning_cycle_service,
    learning_impact_service,
    learning_log_service,
    learning_metrics_service,
    learning_runtime_config,
    self_tuning_service,
)
from app.services.learning_runtime_config_store import LearningRuntimeConfig, _extract_runtime_config, save_runtime_config


router = APIRouter(prefix="/api/learning", tags=["Learning"])


class FeedbackSummaryResponse(BaseModel):
    total_feedback_items: int
    average_feedback_score: float
    success_rate: float
    negative_feedback_rate: float
    strong_signal_rate: float
    domain_correction_rate: float
    strategy_correction_rate: float
    domain_mismatch_rate: float
    strategy_mismatch_rate: float
    positive_confirmation_rate: float
    by_case_domain: dict[str, int] = Field(default_factory=dict)
    by_orchestrator_version: dict[str, int] = Field(default_factory=dict)
    success_rate_by_domain: dict[str, float] = Field(default_factory=dict)
    success_rate_by_orchestrator_version: dict[str, float] = Field(default_factory=dict)
    window_hours: int | None = None


class LearningSummaryResponse(BaseModel):
    total_queries: int
    fallback_rate: float
    low_confidence_rate: float
    average_confidence: float
    average_decision_confidence: float
    average_processing_time_ms: float
    by_retrieval_mode: dict[str, int] = Field(default_factory=dict)
    by_strategy_mode: dict[str, int] = Field(default_factory=dict)
    by_case_domain: dict[str, int] = Field(default_factory=dict)
    by_orchestrator_version: dict[str, int] = Field(default_factory=dict)
    severity_distribution: dict[str, int] = Field(default_factory=dict)
    orchestrator_version_summary: dict = Field(default_factory=dict)
    time_series_severity: list[dict] = Field(default_factory=list)
    feedback_summary: dict = Field(default_factory=dict)
    window_hours: int | None = None


class LearningLogResponse(BaseModel):
    id: str
    request_id: str
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    query: str
    jurisdiction: str | None = None
    forum: str | None = None
    case_domain: str | None = None
    action_slug: str | None = None
    retrieval_mode: str | None = None
    strategy_mode: str | None = None
    pipeline_mode: str | None = None
    decision_confidence: float | None = None
    confidence_score: float | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    documents_considered: int = 0
    warnings_count: int = 0
    processing_time_ms: int = 0
    orchestrator_decision_json: dict = Field(default_factory=dict)
    classification_json: dict = Field(default_factory=dict)
    retrieval_json: dict = Field(default_factory=dict)
    strategy_json: dict = Field(default_factory=dict)
    final_output_json: dict = Field(default_factory=dict)
    timings_json: dict = Field(default_factory=dict)
    quality_flags_json: dict = Field(default_factory=dict)
    severity_score: float = 0.0
    user_feedback_score: int | None = None
    user_feedback_label: str | None = None
    is_user_feedback_positive: bool | None = None
    feedback_submitted_at: str | None = None
    corrected_strategy_mode: str | None = None
    corrected_domain: str | None = None
    feedback_comment: str | None = None
    reviewed_by_user: bool = False
    reviewed_by_admin: bool = False
    review_notes: str | None = None
    review_status: str
    learning_version: str | None = None
    orchestrator_version: str | None = None
    time_bucket: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class LearningLogReviewRequest(BaseModel):
    user_feedback_score: Optional[int] = None
    user_feedback_label: Optional[str] = None
    review_notes: Optional[str] = None
    review_status: Optional[str] = None
    corrected_strategy_mode: Optional[str] = None
    corrected_domain: Optional[str] = None


class LearningLogFeedbackRequest(BaseModel):
    user_feedback_score: Optional[int] = None
    is_user_feedback_positive: Optional[bool] = None
    corrected_domain: Optional[str] = None
    corrected_strategy_mode: Optional[str] = None
    feedback_comment: Optional[str] = None


class LearningCycleResultResponse(BaseModel):
    total_recommendations: int
    applied_count: int
    skipped_count: int
    results: list[dict] = Field(default_factory=list)


class LearningActionAuditResponse(BaseModel):
    id: str
    event_type: str
    recommendation_type: str | None = None
    applied: bool
    reason: str | None = None
    confidence_score: float | None = None
    priority: float | None = None
    impact_status: str | None = None
    applied_at: str | None = None
    created_at: str


class LearningImpactLogResponse(BaseModel):
    id: str
    learning_action_log_id: str
    event_type: str
    status: str
    before_metrics_json: dict = Field(default_factory=dict)
    after_metrics_json: dict = Field(default_factory=dict)
    delta_metrics_json: dict = Field(default_factory=dict)
    evaluation_window_hours: int
    evaluated_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class LearningImpactSummaryResponse(BaseModel):
    total_evaluated: int
    improved: int
    regressed: int
    neutral: int
    insufficient_data: int
    improvement_rate: float
    regression_rate: float
    recent_impacts: list[dict] = Field(default_factory=list)


class SelfTuningRunRequest(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=100, ge=1, le=500)
    persist_trace: bool = True
    aggressiveness_mode: str | None = None


@router.get("/summary", response_model=LearningSummaryResponse)
def get_learning_summary(
    last_hours: int | None = Query(default=None, ge=1, le=720),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LearningSummaryResponse:
    return LearningSummaryResponse(**learning_metrics_service.get_learning_summary(db, last_hours=last_hours))


@router.get("/feedback-summary", response_model=FeedbackSummaryResponse)
def get_feedback_summary(
    last_hours: int | None = Query(default=168, ge=1, le=720),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackSummaryResponse:
    return FeedbackSummaryResponse(**learning_metrics_service.get_feedback_summary(db, last_hours=last_hours))


@router.get("/logs", response_model=list[LearningLogResponse])
def get_learning_logs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[LearningLogResponse]:
    items = learning_metrics_service.get_recent_learning_logs(db, limit=limit)
    return [LearningLogResponse(**item) for item in items]


@router.post("/logs/{log_id}/feedback", response_model=LearningLogResponse)
def submit_learning_feedback(
    log_id: str,
    payload: LearningLogFeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LearningLogResponse:
    try:
        log = learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=payload.user_feedback_score,
            is_user_feedback_positive=payload.is_user_feedback_positive,
            corrected_domain=payload.corrected_domain,
            corrected_strategy_mode=payload.corrected_strategy_mode,
            feedback_comment=payload.feedback_comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learning log no encontrado.")
    return LearningLogResponse(**log.to_dict())


@router.post("/logs/{log_id}/review", response_model=LearningLogResponse)
def review_learning_log(
    log_id: str,
    payload: LearningLogReviewRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LearningLogResponse:
    try:
        log = learning_log_service.update_learning_log_review(
            db,
            log_id=log_id,
            user_feedback_score=payload.user_feedback_score,
            user_feedback_label=payload.user_feedback_label,
            review_notes=payload.review_notes,
            review_status=payload.review_status,
            corrected_strategy_mode=payload.corrected_strategy_mode,
            corrected_domain=payload.corrected_domain,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learning log no encontrado.")
    return LearningLogResponse(**log.to_dict())


@router.post("/run-cycle", response_model=LearningCycleResultResponse)
def run_learning_cycle(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LearningCycleResultResponse:
    return LearningCycleResultResponse(**learning_cycle_service.run_learning_cycle(db))


@router.get("/actions-log", response_model=list[LearningActionAuditResponse])
def get_learning_actions(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[LearningActionAuditResponse]:
    logs = (
        db.query(LearningActionLog)
        .order_by(LearningActionLog.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        LearningActionAuditResponse(
            id=log.id,
            event_type=log.event_type,
            recommendation_type=log.recommendation_type,
            applied=bool(log.applied),
            reason=log.reason,
            confidence_score=log.confidence_score,
            priority=log.priority,
            impact_status=log.impact_status,
            applied_at=log.applied_at.isoformat() if log.applied_at else None,
            created_at=log.created_at.isoformat(),
        )
        for log in logs
    ]


@router.get("/impact-summary", response_model=LearningImpactSummaryResponse)
def get_learning_impact_summary(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LearningImpactSummaryResponse:
    payload = dict(learning_impact_service.get_impact_summary(db))
    payload["recent_impacts"] = [
        {
            "impact_score": item.get("impact_score"),
            "impact_label": item.get("impact_label"),
            "created_at": item.get("created_at"),
        }
        for item in learning_impact_service.get_recent_impact_logs(db, limit=20)
    ]
    return LearningImpactSummaryResponse(**payload)


@router.get("/impact-logs", response_model=list[LearningImpactLogResponse])
def get_learning_impact_logs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[LearningImpactLogResponse]:
    items = learning_impact_service.get_recent_impact_logs(db, limit=limit)
    return [LearningImpactLogResponse(**item) for item in items]


@router.post("/evaluate-impact/{action_log_id}", response_model=LearningImpactLogResponse)
def evaluate_learning_action_impact(
    action_log_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LearningImpactLogResponse:
    try:
        payload = learning_impact_service.evaluate_learning_action_impact(
            db,
            action_log_id=action_log_id,
            window_hours=window_hours,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "learning_action_log_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc
    return LearningImpactLogResponse(**payload)


@router.post("/rollback-last")
def rollback_last(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    logs = (
        db.query(LearningRuntimeConfig)
        .order_by(LearningRuntimeConfig.created_at.desc())
        .limit(2)
        .all()
    )
    if len(logs) < 2:
        raise HTTPException(status_code=400, detail="No hay suficiente historial")

    previous = _extract_runtime_config(json.loads(logs[1].config_json)) or {}
    learning_runtime_config.apply_persisted_runtime_config(previous)

    runtime_config = learning_runtime_config.get_effective_runtime_config()
    save_runtime_config(db, runtime_config)
    db.add(
        LearningActionLog(
            event_type="rollback",
            recommendation_type="manual_rollback",
            applied=True,
            reason="manual_rollback",
            confidence_score=None,
            priority=None,
            impact_status="pending",
            applied_at=None,
            evidence_json=json.dumps(
                {
                    "restored_snapshot_id": logs[1].id,
                }
            ),
            changes_applied_json=json.dumps(runtime_config),
        )
    )
    db.commit()
    return {"status": "rolled_back", "runtime_config": runtime_config}


@router.post("/self-tuning/run")
def run_self_tuning_cycle(
    payload: SelfTuningRunRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return self_tuning_service.run_self_tuning_cycle(
        db,
        dry_run=payload.dry_run,
        limit=payload.limit,
        persist_trace=payload.persist_trace,
        aggressiveness_mode=payload.aggressiveness_mode,
    )


@router.get("/self-tuning/latest")
def get_latest_self_tuning_cycle(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return self_tuning_service.get_latest_self_tuning_cycle(db) or {}


@router.get("/self-tuning/meta-summary")
def get_self_tuning_meta_summary(
    limit: int = Query(default=120, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return self_tuning_service.get_self_tuning_meta_summary(db, limit=limit)


@router.get("/self-tuning/strategy-summary")
def get_self_tuning_strategy_summary(
    limit: int = Query(default=120, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return self_tuning_service.get_self_tuning_strategy_summary(db, limit=limit)
