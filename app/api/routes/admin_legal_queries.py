from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import User
from app.services import query_logging_service

router = APIRouter(prefix="/api/admin/legal-queries", tags=["Admin Legal Queries"])


class QueryReviewCreateRequest(BaseModel):
    reviewer: str = ""
    review_status: str = Field(default="reviewed", min_length=1)
    feedback_signal: str = ""
    quality_score: float | None = None
    legal_accuracy_score: float | None = None
    clarity_score: float | None = None
    usefulness_score: float | None = None
    notes: str = ""
    corrected_answer: str = ""
    detected_issue_tags: list[str] = Field(default_factory=list)


class QueryReviewResponse(BaseModel):
    id: str
    query_id: str
    created_at: str | None = None
    reviewer: str
    review_status: str
    feedback_signal: str
    quality_score: float | None = None
    legal_accuracy_score: float | None = None
    clarity_score: float | None = None
    usefulness_score: float | None = None
    notes: str
    corrected_answer: str
    detected_issue_tags_json: list[str] = Field(default_factory=list)


class LegalQueryLogSummaryResponse(BaseModel):
    id: str
    created_at: str | None = None
    updated_at: str | None = None
    request_id: str
    pipeline_version: str
    user_query_original: str
    case_domain: str
    action_slug: str
    source_mode: str
    documents_considered: int
    strategy_mode: str
    dominant_factor: str
    blocking_factor: str
    execution_readiness: str
    fallback_used: bool
    confidence_score: float | None = None
    confidence_label: str
    status: str
    review_status: str
    feedback_signal: str


class LegalQueryLogDetailResponse(LegalQueryLogSummaryResponse):
    user_query_normalized: str
    jurisdiction_requested: str
    forum_requested: str
    facts_json: dict = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)
    action_label: str
    sources_used_json: list[str] = Field(default_factory=list)
    normative_references_json: list[dict] = Field(default_factory=list)
    jurisprudence_references_json: list[dict] = Field(default_factory=list)
    top_retrieval_scores_json: list[float] = Field(default_factory=list)
    response_text: str
    warnings_json: list[str] = Field(default_factory=list)
    fallback_reason: str
    normalization_ms: int
    pipeline_ms: int
    classification_ms: int
    retrieval_ms: int
    strategy_ms: int
    postprocess_ms: int
    final_assembly_ms: int
    total_ms: int
    error_message: str | None = None
    review_notes: str
    reviews: list[QueryReviewResponse] = Field(default_factory=list)


class LegalQueryLogListResponse(BaseModel):
    items: list[LegalQueryLogSummaryResponse]
    total: int


def _to_summary(item) -> LegalQueryLogSummaryResponse:
    payload = item.to_dict(include_reviews=False)
    return LegalQueryLogSummaryResponse(**{
        key: payload[key]
        for key in LegalQueryLogSummaryResponse.model_fields
    })


def _to_detail(item) -> LegalQueryLogDetailResponse:
    payload = item.to_dict(include_reviews=True)
    payload["reviews"] = [QueryReviewResponse(**review) for review in payload.get("reviews", [])]
    return LegalQueryLogDetailResponse(**payload)


@router.get("", response_model=LegalQueryLogListResponse)
def list_legal_queries(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    review_status: Optional[str] = Query(default=None),
    case_domain: Optional[str] = Query(default=None),
    action_slug: Optional[str] = Query(default=None),
    fallback_used: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LegalQueryLogListResponse:
    items, total = query_logging_service.list_logs(
        db,
        skip=skip,
        limit=limit,
        status=status_filter,
        review_status=review_status,
        case_domain=case_domain,
        action_slug=action_slug,
        fallback_used=fallback_used,
    )
    return LegalQueryLogListResponse(items=[_to_summary(item) for item in items], total=total)


@router.get("/{query_id}", response_model=LegalQueryLogDetailResponse)
def get_legal_query_detail(
    query_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LegalQueryLogDetailResponse:
    item = query_logging_service.get_log_detail(db, query_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta no encontrada.")
    return _to_detail(item)


@router.post("/{query_id}/reviews", response_model=QueryReviewResponse, status_code=status.HTTP_201_CREATED)
def create_legal_query_review(
    query_id: str,
    payload: QueryReviewCreateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> QueryReviewResponse:
    review = query_logging_service.create_review(
        db,
        query_id=query_id,
        reviewer=payload.reviewer,
        review_status=payload.review_status,
        feedback_signal=payload.feedback_signal,
        quality_score=payload.quality_score,
        legal_accuracy_score=payload.legal_accuracy_score,
        clarity_score=payload.clarity_score,
        usefulness_score=payload.usefulness_score,
        notes=payload.notes,
        corrected_answer=payload.corrected_answer,
        detected_issue_tags=payload.detected_issue_tags,
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta no encontrada.")
    return QueryReviewResponse(**review.to_dict())
