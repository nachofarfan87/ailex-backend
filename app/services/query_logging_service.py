from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.legal_query_log_models import LegalQueryLog, QueryReview


def _json_dumps(value: Any, fallback: Any) -> str:
    try:
        return json.dumps(value if value is not None else fallback, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(fallback, ensure_ascii=False, default=str)


def _safe_str(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or default


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _get_log(db: Session, log_id: str | None = None, request_id: str | None = None) -> LegalQueryLog | None:
    if log_id:
        existing = db.get(LegalQueryLog, log_id)
        if existing is not None:
            return existing
    if request_id:
        return db.query(LegalQueryLog).filter(LegalQueryLog.request_id == request_id).one_or_none()
    return None


def create_processing_log(
    db: Session,
    *,
    request_id: str,
    pipeline_version: str,
    user_query_original: str,
    user_query_normalized: str,
    jurisdiction_requested: str | None = None,
    forum_requested: str | None = None,
    facts: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> LegalQueryLog:
    log = _get_log(db, request_id=request_id)
    if log is None:
        log = LegalQueryLog(request_id=request_id)
        db.add(log)
    else:
        log.request_id = _safe_str(request_id, log.request_id)

    log.pipeline_version = _safe_str(pipeline_version, "unknown")
    log.user_query_original = _safe_str(user_query_original)
    log.user_query_normalized = _safe_str(user_query_normalized)
    log.jurisdiction_requested = _safe_str(jurisdiction_requested)
    log.forum_requested = _safe_str(forum_requested)
    log.facts_json = _json_dumps(facts, {})
    log.metadata_json = _json_dumps(metadata, {})
    log.status = "processing"
    log.error_message = None

    db.commit()
    db.refresh(log)
    return log


def _apply_result_to_log(log: LegalQueryLog, result: Any) -> None:
    normalized = result.normalized_input
    classification = result.classification
    retrieval = result.retrieval
    strategy = result.strategy
    final_output = result.final_output
    timings = result.timings

    log.request_id = _safe_str(normalized.request_id, log.request_id)
    log.pipeline_version = _safe_str(result.pipeline_version, "unknown")
    log.user_query_original = _safe_str(getattr(result, "pipeline_payload", {}).get("query"), normalized.query)
    log.user_query_normalized = _safe_str(normalized.query)
    log.jurisdiction_requested = _safe_str(normalized.jurisdiction)
    log.forum_requested = _safe_str(normalized.forum)
    log.facts_json = _json_dumps(normalized.facts, {})
    log.metadata_json = _json_dumps(normalized.metadata, {})

    log.case_domain = _safe_str(classification.case_domain)
    log.action_slug = _safe_str(classification.action_slug)
    log.action_label = _safe_str(classification.action_label)

    log.source_mode = _safe_str(retrieval.source_mode)
    log.documents_considered = _safe_int(retrieval.documents_considered)
    log.sources_used_json = _json_dumps(retrieval.sources_used, [])
    log.normative_references_json = _json_dumps(retrieval.normative_references, [])
    log.jurisprudence_references_json = _json_dumps(retrieval.jurisprudence_references, [])
    log.top_retrieval_scores_json = _json_dumps(retrieval.top_retrieval_scores, [])

    log.strategy_mode = _safe_str(strategy.strategy_mode)
    log.dominant_factor = _safe_str(strategy.dominant_factor)
    log.blocking_factor = _safe_str(strategy.blocking_factor)
    log.execution_readiness = _safe_str(strategy.execution_readiness)

    log.response_text = _safe_str(final_output.response_text)
    log.warnings_json = _json_dumps(final_output.warnings, [])
    log.fallback_used = bool(strategy.fallback_used)
    log.fallback_reason = _safe_str(strategy.fallback_reason)
    log.confidence_score = _safe_float(strategy.confidence_score or final_output.confidence_score)
    log.confidence_label = _safe_str(strategy.confidence_label or final_output.confidence_label)

    log.normalization_ms = _safe_int(timings.normalization_ms)
    log.pipeline_ms = _safe_int(timings.pipeline_ms)
    log.classification_ms = _safe_int(timings.classification_ms)
    log.retrieval_ms = _safe_int(timings.retrieval_ms)
    log.strategy_ms = _safe_int(timings.strategy_ms)
    log.postprocess_ms = _safe_int(timings.postprocess_ms)
    log.final_assembly_ms = _safe_int(timings.final_assembly_ms)
    log.total_ms = _safe_int(timings.total_ms)

    log.status = "completed"
    log.error_message = None


def complete_log(
    db: Session,
    *,
    result: Any,
    log_id: str | None = None,
    request_id: str | None = None,
) -> LegalQueryLog:
    normalized = result.normalized_input
    log = _get_log(db, log_id=log_id, request_id=request_id or normalized.request_id)
    if log is None:
        log = LegalQueryLog(request_id=normalized.request_id)
        db.add(log)

    _apply_result_to_log(log, result)
    db.commit()
    db.refresh(log)
    return log


def fail_log(
    db: Session,
    *,
    request_id: str,
    error_message: str,
    pipeline_version: str = "unknown",
    log_id: str | None = None,
    user_query_original: str = "",
    user_query_normalized: str = "",
    jurisdiction_requested: str | None = None,
    forum_requested: str | None = None,
    facts: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> LegalQueryLog:
    log = _get_log(db, log_id=log_id, request_id=request_id)
    if log is None:
        log = LegalQueryLog(request_id=request_id)
        db.add(log)

    log.request_id = _safe_str(request_id, log.request_id)
    log.pipeline_version = _safe_str(pipeline_version, "unknown")
    log.user_query_original = _safe_str(user_query_original)
    log.user_query_normalized = _safe_str(user_query_normalized)
    log.jurisdiction_requested = _safe_str(jurisdiction_requested)
    log.forum_requested = _safe_str(forum_requested)
    log.facts_json = _json_dumps(facts, {})
    log.metadata_json = _json_dumps(metadata, {})
    log.status = "failed"
    log.error_message = _safe_str(error_message)

    db.commit()
    db.refresh(log)
    return log


def list_logs(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    review_status: str | None = None,
    case_domain: str | None = None,
    action_slug: str | None = None,
    fallback_used: bool | None = None,
) -> tuple[list[LegalQueryLog], int]:
    query = db.query(LegalQueryLog)
    if status:
        query = query.filter(LegalQueryLog.status == status)
    if review_status:
        query = query.filter(LegalQueryLog.review_status == review_status)
    if case_domain:
        query = query.filter(LegalQueryLog.case_domain == case_domain)
    if action_slug:
        query = query.filter(LegalQueryLog.action_slug == action_slug)
    if fallback_used is not None:
        query = query.filter(LegalQueryLog.fallback_used == fallback_used)

    total = query.count()
    items = (
        query.order_by(LegalQueryLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return items, total


def get_log_detail(db: Session, query_id: str) -> LegalQueryLog | None:
    return db.get(LegalQueryLog, query_id)


def create_review(
    db: Session,
    *,
    query_id: str,
    reviewer: str = "",
    review_status: str,
    feedback_signal: str = "",
    quality_score: float | None = None,
    legal_accuracy_score: float | None = None,
    clarity_score: float | None = None,
    usefulness_score: float | None = None,
    notes: str = "",
    corrected_answer: str = "",
    detected_issue_tags: list[str] | None = None,
) -> QueryReview | None:
    log = db.get(LegalQueryLog, query_id)
    if log is None:
        return None

    review = QueryReview(
        query_id=query_id,
        reviewer=_safe_str(reviewer),
        review_status=_safe_str(review_status, "reviewed"),
        feedback_signal=_safe_str(feedback_signal),
        quality_score=_safe_float(quality_score),
        legal_accuracy_score=_safe_float(legal_accuracy_score),
        clarity_score=_safe_float(clarity_score),
        usefulness_score=_safe_float(usefulness_score),
        notes=_safe_str(notes),
        corrected_answer=_safe_str(corrected_answer),
        detected_issue_tags_json=_json_dumps(detected_issue_tags, []),
    )
    db.add(review)
    log.review_status = review.review_status
    log.feedback_signal = review.feedback_signal
    log.review_notes = review.notes

    db.commit()
    db.refresh(review)
    return review
