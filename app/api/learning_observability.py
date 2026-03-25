"""
AILEX - Endpoints read-only de observabilidad del aprendizaje adaptativo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import User
from app.services import learning_insights_service, learning_observability_service


router = APIRouter(
    prefix="/api/learning/observability",
    tags=["Learning Observability"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OverviewResponse(BaseModel):
    total_observations: int
    total_adaptive_decisions: int
    unique_signatures: int
    unique_signature_families: int
    unique_event_types: int
    reinforced_decisions: int
    blocked_decisions: int
    neutral_decisions: int
    avg_impact_score: float
    recency_weighted_avg_score: float


class SignatureMetricResponse(BaseModel):
    signature: str
    signature_family: str
    event_type: str
    observation_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    avg_score: float
    recency_weighted_score: float
    last_seen_at: str | None = None
    status: str


class FamilyMetricResponse(BaseModel):
    signature_family: str
    event_type: str
    observation_count: int
    unique_signatures: int
    positive_count: int
    negative_count: int
    neutral_count: int
    avg_score: float
    recency_weighted_score: float
    last_seen_at: str | None = None
    status: str


class EventTypeMetricResponse(BaseModel):
    event_type: str
    observation_count: int
    unique_signatures: int
    unique_families: int
    positive_count: int
    negative_count: int
    neutral_count: int
    avg_score: float
    recency_weighted_score: float
    last_seen_at: str | None = None
    status: str


class TimelineBucketResponse(BaseModel):
    date: str
    observations: int
    net_score: int
    reinforced_count: int
    blocked_count: int
    neutral_count: int


class DriftWindowResponse(BaseModel):
    start: str | None = None
    end: str | None = None
    days: int
    total_observations: int
    avg_score: float
    block_rate: float
    improved: int
    regressed: int
    neutral: int


class DriftSignalResponse(BaseModel):
    type: str
    description: str
    severity: str
    delta: float | None = None
    recent_value: float | None = None
    previous_value: float | None = None
    signatures: list[str] | None = None


class DriftResponse(BaseModel):
    drift_detected: bool
    drift_level: str
    drift_signals: list[dict] = Field(default_factory=list)
    compared_windows: dict = Field(default_factory=dict)


class ExplanationLayerResponse(BaseModel):
    layer: str
    reference: str
    score: float
    effect: str
    weight: float
    available: bool
    strong_enough: bool
    raw_total: int
    weighted_total: float
    memory_confidence: float


class DominantSignalResponse(BaseModel):
    layer: str
    direction: str
    score: float
    reference: str


class AdaptiveDecisionResponse(BaseModel):
    should_apply: bool = True
    confidence_adjustment: float = 0.0
    risk_level: str = "low"
    reasoning: str = ""
    applied_rules: list[str] = Field(default_factory=list)


class DecisionTraceResponse(BaseModel):
    id: str
    created_at: str | None = None
    event_type: str | None = None
    recommendation_type: str | None = None
    base_decision: str
    final_decision: str
    decision_mode: str
    dominant_signal: DominantSignalResponse = Field(default_factory=lambda: DominantSignalResponse(layer="none", direction="neutral", score=0.0, reference=""))
    explanation_layers: list[dict] = Field(default_factory=list)
    thresholds_used: dict = Field(default_factory=dict)
    impact_decision_reason: str
    impact_score_reference: dict = Field(default_factory=dict)
    adaptive_decision: AdaptiveDecisionResponse | None = None
    confidence_score: float | None = None
    priority: float | None = None
    impact_status: str | None = None


class TopPatternsResponse(BaseModel):
    top_positive_signatures: list[dict] = Field(default_factory=list)
    top_negative_signatures: list[dict] = Field(default_factory=list)
    top_positive_families: list[dict] = Field(default_factory=list)
    top_negative_families: list[dict] = Field(default_factory=list)


class InsightExplanationResponse(BaseModel):
    version: str = "v1"
    source: str = "learning_insights_service"
    summary: str
    conditions: list[str] = Field(default_factory=list)
    thresholds: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)
    interpretation: str = ""


class InsightResponse(BaseModel):
    type: str
    severity: str
    message: str
    human_summary: str = ""
    recommended_target: str = ""
    generated_at: str | None = None
    heuristic_key: str = ""
    insight_key: str = ""
    metrics: dict = Field(default_factory=dict)
    explanation: InsightExplanationResponse | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> OverviewResponse:
    return OverviewResponse(
        **learning_observability_service.get_overview(
            db,
            date_from=_parse_datetime(date_from),
            date_to=_parse_datetime(date_to),
        )
    )


@router.get("/signatures", response_model=list[SignatureMetricResponse])
def get_signatures(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    signature: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[SignatureMetricResponse]:
    items = learning_observability_service.get_metrics_by_signature(
        db,
        date_from=_parse_datetime(date_from),
        date_to=_parse_datetime(date_to),
        signature_filter=signature,
        event_type_filter=event_type,
        limit=limit,
    )
    return [SignatureMetricResponse(**item) for item in items]


@router.get("/families", response_model=list[FamilyMetricResponse])
def get_families(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    signature_family: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[FamilyMetricResponse]:
    items = learning_observability_service.get_metrics_by_family(
        db,
        date_from=_parse_datetime(date_from),
        date_to=_parse_datetime(date_to),
        family_filter=signature_family,
        event_type_filter=event_type,
        limit=limit,
    )
    return [FamilyMetricResponse(**item) for item in items]


@router.get("/events", response_model=list[EventTypeMetricResponse])
def get_event_types(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[EventTypeMetricResponse]:
    items = learning_observability_service.get_metrics_by_event_type(
        db,
        date_from=_parse_datetime(date_from),
        date_to=_parse_datetime(date_to),
        event_type_filter=event_type,
        limit=limit,
    )
    return [EventTypeMetricResponse(**item) for item in items]


@router.get("/timeline", response_model=list[TimelineBucketResponse])
def get_timeline(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    bucket_days: int = Query(default=1, ge=1, le=30),
    signature: str | None = Query(default=None),
    signature_family: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[TimelineBucketResponse]:
    items = learning_observability_service.get_timeline(
        db,
        date_from=_parse_datetime(date_from),
        date_to=_parse_datetime(date_to),
        bucket_days=bucket_days,
        signature_filter=signature,
        family_filter=signature_family,
        event_type_filter=event_type,
    )
    return [TimelineBucketResponse(**item) for item in items]


@router.get("/drift", response_model=DriftResponse)
def get_drift(
    recent_days: int = Query(default=14, ge=1, le=90),
    previous_days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DriftResponse:
    return DriftResponse(
        **learning_observability_service.detect_drift(
            db,
            recent_days=recent_days,
            previous_days=previous_days,
        )
    )


@router.get("/decisions", response_model=list[DecisionTraceResponse])
def get_decisions(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    signature: str | None = Query(default=None),
    signature_family: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[DecisionTraceResponse]:
    items = learning_observability_service.get_recent_decisions(
        db,
        date_from=_parse_datetime(date_from),
        date_to=_parse_datetime(date_to),
        signature_filter=signature,
        family_filter=signature_family,
        event_type_filter=event_type,
        limit=limit,
    )
    return [DecisionTraceResponse(**item) for item in items]


@router.get("/top-patterns", response_model=TopPatternsResponse)
def get_top_patterns(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    top_n: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> TopPatternsResponse:
    return TopPatternsResponse(
        **learning_observability_service.get_top_patterns(
            db,
            date_from=_parse_datetime(date_from),
            date_to=_parse_datetime(date_to),
            top_n=top_n,
        )
    )


@router.get("/insights", response_model=list[InsightResponse])
def get_insights(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[InsightResponse]:
    items = learning_insights_service.generate_insights(
        db,
        date_from=_parse_datetime(date_from),
        date_to=_parse_datetime(date_to),
    )
    return [InsightResponse(**item) for item in items]
