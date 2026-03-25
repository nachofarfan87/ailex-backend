from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.services.utc import utc_now
from app.models.learning_impact_log import LearningImpactLog
from app.models.learning_log import LearningLog
from app.services import learning_metrics_service


MIN_WINDOW_QUERY_COUNT = 3
IMPACT_IMPROVEMENT_THRESHOLD = 0.05
IMPACT_REGRESSION_THRESHOLD = 0.05


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({}, ensure_ascii=False, default=str)


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _count_logs_in_range(
    db: Session,
    *,
    since: datetime,
    until: datetime,
) -> int:
    return (
        db.query(func.count(LearningLog.id))
        .filter(LearningLog.created_at >= since)
        .filter(LearningLog.created_at < until)
        .scalar()
        or 0
    )


def _compute_delta(before: dict, after: dict) -> dict:
    delta: dict[str, float] = {}
    shared_keys = set(before).intersection(after)
    for key in sorted(shared_keys):
        before_value = _safe_float(before.get(key))
        after_value = _safe_float(after.get(key))
        if before_value is None or after_value is None:
            continue
        delta[key] = round(after_value - before_value, 4)
    return delta


def _classify_impact(before: dict, after: dict, delta: dict) -> str:
    before_queries = int(before.get("total_queries") or 0)
    after_queries = int(after.get("total_queries") or 0)
    if before_queries < MIN_WINDOW_QUERY_COUNT or after_queries < MIN_WINDOW_QUERY_COUNT:
        return "insufficient_data"

    improved = any(
        [
            _safe_float(delta.get("fallback_rate")) is not None and float(delta["fallback_rate"]) <= -IMPACT_IMPROVEMENT_THRESHOLD,
            _safe_float(delta.get("low_confidence_rate")) is not None and float(delta["low_confidence_rate"]) <= -IMPACT_IMPROVEMENT_THRESHOLD,
            _safe_float(delta.get("average_confidence")) is not None and float(delta["average_confidence"]) >= IMPACT_IMPROVEMENT_THRESHOLD,
            _safe_float(delta.get("average_decision_confidence")) is not None and float(delta["average_decision_confidence"]) >= IMPACT_IMPROVEMENT_THRESHOLD,
            _safe_float(delta.get("success_rate")) is not None and float(delta["success_rate"]) >= IMPACT_IMPROVEMENT_THRESHOLD,
            _safe_float(delta.get("negative_feedback_rate")) is not None and float(delta["negative_feedback_rate"]) <= -IMPACT_IMPROVEMENT_THRESHOLD,
        ]
    )
    regressed = any(
        [
            _safe_float(delta.get("fallback_rate")) is not None and float(delta["fallback_rate"]) >= IMPACT_REGRESSION_THRESHOLD,
            _safe_float(delta.get("low_confidence_rate")) is not None and float(delta["low_confidence_rate"]) >= IMPACT_REGRESSION_THRESHOLD,
            _safe_float(delta.get("average_confidence")) is not None and float(delta["average_confidence"]) <= -IMPACT_REGRESSION_THRESHOLD,
            _safe_float(delta.get("average_decision_confidence")) is not None and float(delta["average_decision_confidence"]) <= -IMPACT_REGRESSION_THRESHOLD,
            _safe_float(delta.get("success_rate")) is not None and float(delta["success_rate"]) <= -IMPACT_REGRESSION_THRESHOLD,
            _safe_float(delta.get("negative_feedback_rate")) is not None and float(delta["negative_feedback_rate"]) >= IMPACT_REGRESSION_THRESHOLD,
        ]
    )

    if improved and not regressed:
        return "improved"
    if regressed and not improved:
        return "regressed"
    return "neutral"


def _build_comparable_snapshot(db: Session, *, since: datetime, until: datetime) -> dict[str, Any]:
    snapshot = learning_metrics_service.get_learning_summary_snapshot(db, since=since, until=until)
    feedback_summary = dict(snapshot.get("feedback_summary") or {})
    return {
        "total_queries": int(snapshot.get("total_queries") or 0),
        "fallback_rate": round(float(snapshot.get("fallback_rate") or 0.0), 4),
        "low_confidence_rate": round(float(snapshot.get("low_confidence_rate") or 0.0), 4),
        "average_confidence": round(float(snapshot.get("average_confidence") or 0.0), 4),
        "average_decision_confidence": round(float(snapshot.get("average_decision_confidence") or 0.0), 4),
        "success_rate": round(float(feedback_summary.get("success_rate") or 0.0), 4),
        "negative_feedback_rate": round(float(feedback_summary.get("negative_feedback_rate") or 0.0), 4),
        "feedback_total": int(feedback_summary.get("total_feedback_items") or 0),
    }


def evaluate_learning_action_impact(
    db: Session,
    action_log_id: str,
    window_hours: int = 24,
) -> dict:
    action_log = db.get(LearningActionLog, action_log_id)
    if action_log is None:
        raise ValueError("learning_action_log_not_found")
    if not bool(action_log.applied):
        raise ValueError("learning_action_not_applied")

    evaluated_at = utc_now()
    status = "insufficient_data"
    before_metrics: dict[str, Any] = {}
    after_metrics: dict[str, Any] = {}
    delta_metrics: dict[str, Any] = {}

    if action_log.applied_at is not None:
        before_since = action_log.applied_at - timedelta(hours=int(window_hours))
        before_until = action_log.applied_at
        after_since = action_log.applied_at
        after_until = action_log.applied_at + timedelta(hours=int(window_hours))

        before_metrics = _build_comparable_snapshot(db, since=before_since, until=before_until)
        after_metrics = _build_comparable_snapshot(db, since=after_since, until=after_until)

        before_count = _count_logs_in_range(db, since=before_since, until=before_until)
        after_count = _count_logs_in_range(db, since=after_since, until=after_until)
        before_metrics["window_log_count"] = int(before_count)
        after_metrics["window_log_count"] = int(after_count)

        if before_count >= MIN_WINDOW_QUERY_COUNT and after_count >= MIN_WINDOW_QUERY_COUNT:
            delta_metrics = _compute_delta(before_metrics, after_metrics)
            status = _classify_impact(before_metrics, after_metrics, delta_metrics)

    impact_log = LearningImpactLog(
        learning_action_log_id=action_log.id,
        event_type=str(action_log.event_type or ""),
        status=status,
        before_metrics_json=_safe_json_dumps(before_metrics),
        after_metrics_json=_safe_json_dumps(after_metrics),
        delta_metrics_json=_safe_json_dumps(delta_metrics),
        evaluation_window_hours=int(window_hours),
        evaluated_at=evaluated_at,
    )
    db.add(impact_log)
    action_log.impact_status = status
    db.commit()
    db.refresh(impact_log)
    db.refresh(action_log)
    return impact_log.to_dict()


def get_recent_impact_logs(db: Session, limit: int = 50) -> list[dict]:
    items = (
        db.query(LearningImpactLog)
        .order_by(LearningImpactLog.created_at.desc())
        .limit(max(1, min(int(limit or 50), 200)))
        .all()
    )
    return [item.to_dict() for item in items]


def get_impact_summary(db: Session) -> dict:
    total_evaluated = db.query(func.count(LearningImpactLog.id)).scalar() or 0
    counts = {
        "improved": 0,
        "regressed": 0,
        "neutral": 0,
        "insufficient_data": 0,
        "pending": 0,
    }
    rows = (
        db.query(LearningImpactLog.status, func.count(LearningImpactLog.id))
        .group_by(LearningImpactLog.status)
        .all()
    )
    for status, count in rows:
        normalized = str(status or "").strip() or "pending"
        counts[normalized] = int(count or 0)

    return {
        "total_evaluated": int(total_evaluated),
        "improved": counts["improved"],
        "regressed": counts["regressed"],
        "neutral": counts["neutral"],
        "insufficient_data": counts["insufficient_data"],
        "improvement_rate": round(counts["improved"] / total_evaluated, 4) if total_evaluated else 0.0,
        "regression_rate": round(counts["regressed"] / total_evaluated, 4) if total_evaluated else 0.0,
    }
