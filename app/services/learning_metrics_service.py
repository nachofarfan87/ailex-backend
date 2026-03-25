from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.models.learning_log import LearningLog
from app.services.utc import utc_now


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(tz=None).replace(tzinfo=None)
    return value


def _resolve_since(last_hours: int | None) -> datetime | None:
    if last_hours is None or last_hours <= 0:
        return None
    return utc_now() - timedelta(hours=int(last_hours))


def _apply_range_filter(query, *, since: datetime | None = None, until: datetime | None = None):
    normalized_since = _normalize_dt(since)
    normalized_until = _normalize_dt(until)
    if normalized_since is not None:
        query = query.filter(LearningLog.created_at >= normalized_since)
    if normalized_until is not None:
        query = query.filter(LearningLog.created_at < normalized_until)
    return query


def _apply_time_filter(query, *, since: datetime | None):
    return _apply_range_filter(query, since=since, until=None)


def _bucket_counts(
    db: Session,
    field,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, int]:
    query = db.query(field, func.count(LearningLog.id))
    query = _apply_range_filter(query, since=since, until=until)
    rows = query.group_by(field).all()
    result: dict[str, int] = {}
    for key, count in rows:
        normalized = str(key or "unknown").strip() or "unknown"
        result[normalized] = int(count or 0)
    return result


def _feedback_filter_expression():
    return or_(
        LearningLog.feedback_submitted_at.isnot(None),
        LearningLog.user_feedback_score.isnot(None),
        LearningLog.is_user_feedback_positive.isnot(None),
        and_(LearningLog.corrected_domain.isnot(None), func.trim(LearningLog.corrected_domain) != ""),
        and_(LearningLog.corrected_strategy_mode.isnot(None), func.trim(LearningLog.corrected_strategy_mode) != ""),
        and_(LearningLog.feedback_comment.isnot(None), func.trim(LearningLog.feedback_comment) != ""),
        LearningLog.reviewed_by_user.is_(True),
        LearningLog.reviewed_by_admin.is_(True),
    )


def _feedback_base_query(
    db: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
):
    query = db.query(LearningLog).filter(_feedback_filter_expression())
    return _apply_range_filter(query, since=since, until=until)


def _review_feedback_extract(field_name: str):
    return func.json_extract(LearningLog.quality_flags_json, f"$.review_feedback.{field_name}")


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _success_rate_by_bucket(db: Session, field, *, since: datetime | None = None) -> dict[str, float]:
    feedback_query = _feedback_base_query(db, since=since)
    rows = (
        feedback_query.with_entities(
            field,
            func.count(LearningLog.id),
            func.sum(
                case(
                    (_review_feedback_extract("feedback_is_positive_confirmation") == 1, 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        or_(
                            LearningLog.user_feedback_score.isnot(None),
                            LearningLog.is_user_feedback_positive.isnot(None),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .group_by(field)
        .all()
    )
    result: dict[str, float] = {}
    for key, _count, positive_confirmations, usable_total in rows:
        normalized = str(key or "unknown").strip() or "unknown"
        result[normalized] = _rate(int(positive_confirmations or 0), int(usable_total or 0))
    return result


def get_severity_distribution(db: Session, *, since: datetime | None = None) -> dict[str, int]:
    low_query = db.query(func.count(LearningLog.id)).filter(LearningLog.severity_score < 0.3)
    medium_query = (
        db.query(func.count(LearningLog.id))
        .filter(LearningLog.severity_score >= 0.3)
        .filter(LearningLog.severity_score < 0.6)
    )
    high_query = db.query(func.count(LearningLog.id)).filter(LearningLog.severity_score >= 0.6)

    low = _apply_time_filter(low_query, since=since).scalar() or 0
    medium = _apply_time_filter(medium_query, since=since).scalar() or 0
    high = _apply_time_filter(high_query, since=since).scalar() or 0

    return {
        "low": int(low),
        "medium": int(medium),
        "high": int(high),
    }


def get_feedback_summary(db: Session, *, last_hours: int | None = None) -> dict[str, Any]:
    since = _resolve_since(last_hours)
    feedback_query = _feedback_base_query(db, since=since)
    total_feedback_items = feedback_query.count()

    if total_feedback_items == 0:
        return {
            "total_feedback_items": 0,
            "average_feedback_score": 0.0,
            "success_rate": 0.0,
            "negative_feedback_rate": 0.0,
            "strong_signal_rate": 0.0,
            "domain_correction_rate": 0.0,
            "strategy_correction_rate": 0.0,
            "domain_mismatch_rate": 0.0,
            "strategy_mismatch_rate": 0.0,
            "positive_confirmation_rate": 0.0,
            "by_case_domain": {},
            "by_orchestrator_version": {},
            "success_rate_by_domain": {},
            "success_rate_by_orchestrator_version": {},
            "window_hours": last_hours,
        }

    average_feedback_score = (
        feedback_query.with_entities(func.avg(LearningLog.user_feedback_score))
        .filter(LearningLog.user_feedback_score.isnot(None))
        .scalar()
    )
    positive_feedback_total = (
        feedback_query.with_entities(func.count(LearningLog.id))
        .filter(
            or_(
                LearningLog.user_feedback_score.isnot(None),
                LearningLog.is_user_feedback_positive.isnot(None),
            )
        )
        .scalar()
        or 0
    )
    positive_confirmation_count = (
        feedback_query.with_entities(func.count(LearningLog.id))
        .filter(_review_feedback_extract("feedback_is_positive_confirmation") == 1)
        .scalar()
        or 0
    )
    negative_feedback_count = (
        feedback_query.with_entities(func.count(LearningLog.id))
        .filter(_review_feedback_extract("feedback_is_negative") == 1)
        .scalar()
        or 0
    )
    strong_signal_count = (
        feedback_query.with_entities(func.count(LearningLog.id))
        .filter(_review_feedback_extract("feedback_is_strong_signal") == 1)
        .scalar()
        or 0
    )
    domain_corrections = (
        feedback_query.with_entities(func.count(LearningLog.id))
        .filter(_review_feedback_extract("feedback_has_domain_correction") == 1)
        .scalar()
        or 0
    )
    strategy_corrections = (
        feedback_query.with_entities(func.count(LearningLog.id))
        .filter(_review_feedback_extract("feedback_has_strategy_correction") == 1)
        .scalar()
        or 0
    )

    by_case_domain_rows = (
        feedback_query.with_entities(LearningLog.case_domain, func.count(LearningLog.id))
        .group_by(LearningLog.case_domain)
        .all()
    )
    by_orchestrator_version_rows = (
        feedback_query.with_entities(LearningLog.orchestrator_version, func.count(LearningLog.id))
        .group_by(LearningLog.orchestrator_version)
        .all()
    )

    by_case_domain = {
        (str(domain or "unknown").strip() or "unknown"): int(count or 0)
        for domain, count in by_case_domain_rows
    }
    by_orchestrator_version = {
        (str(version or "unknown").strip() or "unknown"): int(count or 0)
        for version, count in by_orchestrator_version_rows
    }

    success_rate = _rate(int(positive_confirmation_count), int(positive_feedback_total))

    return {
        "total_feedback_items": int(total_feedback_items),
        "average_feedback_score": round(_safe_float(average_feedback_score), 4),
        "success_rate": success_rate,
        "negative_feedback_rate": _rate(int(negative_feedback_count), int(total_feedback_items)),
        "strong_signal_rate": _rate(int(strong_signal_count), int(total_feedback_items)),
        "domain_correction_rate": _rate(int(domain_corrections), int(total_feedback_items)),
        "strategy_correction_rate": _rate(int(strategy_corrections), int(total_feedback_items)),
        "domain_mismatch_rate": _rate(int(domain_corrections), int(total_feedback_items)),
        "strategy_mismatch_rate": _rate(int(strategy_corrections), int(total_feedback_items)),
        "positive_confirmation_rate": _rate(int(positive_confirmation_count), int(total_feedback_items)),
        "by_case_domain": by_case_domain,
        "by_orchestrator_version": by_orchestrator_version,
        "success_rate_by_domain": _success_rate_by_bucket(db, LearningLog.case_domain, since=since),
        "success_rate_by_orchestrator_version": _success_rate_by_bucket(db, LearningLog.orchestrator_version, since=since),
        "window_hours": last_hours,
    }


def get_orchestrator_version_summary(db: Session, last_hours: int | None = None) -> dict[str, Any]:
    since = _resolve_since(last_hours)

    version_counts = _bucket_counts(db, LearningLog.orchestrator_version, since=since)
    avg_query = db.query(
        LearningLog.orchestrator_version,
        func.avg(LearningLog.severity_score),
    )
    avg_query = _apply_time_filter(avg_query, since=since)
    avg_rows = avg_query.group_by(LearningLog.orchestrator_version).all()

    average_severity_by_version: dict[str, float] = {}
    version_counts_for_ranking: dict[str, int] = {}
    for version, average in avg_rows:
        normalized = str(version or "unknown").strip() or "unknown"
        average_severity_by_version[normalized] = round(_safe_float(average), 4)
        version_counts_for_ranking[normalized] = version_counts.get(normalized, 0)

    total_versions_in_window = sum(version_counts.values())
    version_share = {}
    if total_versions_in_window > 0:
        version_share = {
            version: round(count / total_versions_in_window, 4)
            for version, count in version_counts.items()
        }

    severity_ranking = sorted(
        [
            {
                "version": version,
                "average_severity": average_severity_by_version.get(version, 0.0),
                "count": version_counts_for_ranking.get(version, version_counts.get(version, 0)),
            }
            for version in version_counts
        ],
        key=lambda item: (-item["average_severity"], -item["count"], item["version"]),
    )

    return {
        "versions": version_counts,
        "average_severity_by_version": average_severity_by_version,
        "version_share": version_share,
        "severity_ranking": severity_ranking,
        "window_hours": last_hours,
    }


def get_time_series_severity(db: Session, *, last_hours: int | None = None) -> list[dict[str, Any]]:
    since = _resolve_since(last_hours)
    rows = get_time_series_severity_range(db, since=since, until=None)
    return [
        {
            "time_bucket": row["time_bucket"],
            "count": row["count"],
            "average_severity": row["average_severity"],
            "fallback_rate": row["fallback_rate"],
        }
        for row in rows
    ]


def get_time_series_severity_range(
    db: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    query = db.query(
        LearningLog.time_bucket,
        func.count(LearningLog.id),
        func.avg(LearningLog.severity_score),
        func.avg(case((LearningLog.fallback_used.is_(True), 1.0), else_=0.0)),
        func.avg(case((LearningLog.confidence_score < 0.5, 1.0), else_=0.0)),
    )
    query = _apply_range_filter(query, since=since, until=until)
    rows = (
        query.group_by(LearningLog.time_bucket)
        .order_by(LearningLog.time_bucket.asc())
        .all()
    )

    results: list[dict[str, Any]] = []
    for time_bucket, count, average_severity, fallback_rate, low_confidence_rate in rows:
        results.append(
            {
                "time_bucket": str(time_bucket or "").strip(),
                "count": int(count or 0),
                "average_severity": round(_safe_float(average_severity), 4),
                "fallback_rate": round(_safe_float(fallback_rate), 4),
                "low_confidence_rate": round(_safe_float(low_confidence_rate), 4),
            }
        )
    return results


def get_compact_time_series_excerpt(
    db: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    rows = get_time_series_severity_range(db, since=since, until=until)
    if limit <= 0:
        return []
    return rows[-limit:]


def get_learning_summary_snapshot(
    db: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    total_queries = (
        _apply_range_filter(db.query(func.count(LearningLog.id)), since=since, until=until).scalar()
        or 0
    )
    if total_queries == 0:
        return {
            "total_queries": 0,
            "average_severity": 0.0,
            "fallback_rate": 0.0,
            "low_confidence_rate": 0.0,
            "average_confidence": 0.0,
            "average_decision_confidence": 0.0,
            "feedback_summary": {
                "success_rate": 0.0,
                "negative_feedback_rate": 0.0,
                "total_feedback_items": 0,
            },
        }

    average_severity = _apply_range_filter(
        db.query(func.avg(LearningLog.severity_score)),
        since=since,
        until=until,
    ).scalar()
    fallback_count = _apply_range_filter(
        db.query(func.count(LearningLog.id)).filter(LearningLog.fallback_used.is_(True)),
        since=since,
        until=until,
    ).scalar() or 0
    low_confidence_count = _apply_range_filter(
        db.query(func.count(LearningLog.id))
        .filter(LearningLog.confidence_score.isnot(None))
        .filter(LearningLog.confidence_score < 0.5),
        since=since,
        until=until,
    ).scalar() or 0
    average_confidence = _apply_range_filter(
        db.query(func.avg(LearningLog.confidence_score)),
        since=since,
        until=until,
    ).scalar()
    average_decision_confidence = _apply_range_filter(
        db.query(func.avg(LearningLog.decision_confidence)),
        since=since,
        until=until,
    ).scalar()
    feedback_query = _feedback_base_query(db, since=since, until=until)
    feedback_total = feedback_query.count()
    feedback_summary = {
        "success_rate": 0.0,
        "negative_feedback_rate": 0.0,
        "total_feedback_items": int(feedback_total),
    }
    if feedback_total > 0:
        positive_feedback_total = (
            _feedback_base_query(db, since=since, until=until)
            .with_entities(func.count(LearningLog.id))
            .filter(
                or_(
                    LearningLog.user_feedback_score.isnot(None),
                    LearningLog.is_user_feedback_positive.isnot(None),
                )
            )
            .scalar()
            or 0
        )
        positive_confirmation_count = (
            _feedback_base_query(db, since=since, until=until)
            .with_entities(func.count(LearningLog.id))
            .filter(_review_feedback_extract("feedback_is_positive_confirmation") == 1)
            .scalar()
            or 0
        )
        negative_feedback_count = (
            _feedback_base_query(db, since=since, until=until)
            .with_entities(func.count(LearningLog.id))
            .filter(_review_feedback_extract("feedback_is_negative") == 1)
            .scalar()
            or 0
        )
        feedback_summary = {
            "success_rate": _rate(int(positive_confirmation_count), int(positive_feedback_total)),
            "negative_feedback_rate": _rate(int(negative_feedback_count), int(feedback_total)),
            "total_feedback_items": int(feedback_total),
        }

    return {
        "total_queries": int(total_queries),
        "average_severity": round(_safe_float(average_severity), 4),
        "fallback_rate": round(fallback_count / total_queries, 4),
        "low_confidence_rate": round(low_confidence_count / total_queries, 4),
        "average_confidence": round(_safe_float(average_confidence), 4),
        "average_decision_confidence": round(_safe_float(average_decision_confidence), 4),
        "feedback_summary": feedback_summary,
    }


def get_learning_summary(db: Session, *, last_hours: int | None = None) -> dict[str, Any]:
    since = _resolve_since(last_hours)

    total_query = db.query(func.count(LearningLog.id))
    total_queries = _apply_time_filter(total_query, since=since).scalar() or 0
    feedback_summary = get_feedback_summary(db, last_hours=last_hours)
    if total_queries == 0:
        return {
            "total_queries": 0,
            "fallback_rate": 0.0,
            "low_confidence_rate": 0.0,
            "average_confidence": 0.0,
            "average_decision_confidence": 0.0,
            "average_processing_time_ms": 0.0,
            "by_retrieval_mode": {},
            "by_strategy_mode": {},
            "by_case_domain": {},
            "by_orchestrator_version": {},
            "severity_distribution": {"low": 0, "medium": 0, "high": 0},
            "orchestrator_version_summary": {
                "versions": {},
                "average_severity_by_version": {},
                "version_share": {},
                "severity_ranking": [],
                "window_hours": last_hours,
            },
            "time_series_severity": [],
            "feedback_summary": feedback_summary,
            "window_hours": last_hours,
        }

    fallback_count = _apply_time_filter(
        db.query(func.count(LearningLog.id)).filter(LearningLog.fallback_used.is_(True)),
        since=since,
    ).scalar() or 0
    low_confidence_count = _apply_time_filter(
        db.query(func.count(LearningLog.id))
        .filter(LearningLog.confidence_score.isnot(None))
        .filter(LearningLog.confidence_score < 0.5),
        since=since,
    ).scalar() or 0
    average_confidence = _apply_time_filter(
        db.query(func.avg(LearningLog.confidence_score)),
        since=since,
    ).scalar()
    average_decision_confidence = _apply_time_filter(
        db.query(func.avg(LearningLog.decision_confidence)),
        since=since,
    ).scalar()
    average_processing_time_ms = _apply_time_filter(
        db.query(func.avg(LearningLog.processing_time_ms)),
        since=since,
    ).scalar()

    return {
        "total_queries": int(total_queries),
        "fallback_rate": round(fallback_count / total_queries, 4),
        "low_confidence_rate": round(low_confidence_count / total_queries, 4),
        "average_confidence": round(_safe_float(average_confidence), 4),
        "average_decision_confidence": round(_safe_float(average_decision_confidence), 4),
        "average_processing_time_ms": round(_safe_float(average_processing_time_ms), 2),
        "by_retrieval_mode": _bucket_counts(db, LearningLog.retrieval_mode, since=since),
        "by_strategy_mode": _bucket_counts(db, LearningLog.strategy_mode, since=since),
        "by_case_domain": _bucket_counts(db, LearningLog.case_domain, since=since),
        "by_orchestrator_version": _bucket_counts(db, LearningLog.orchestrator_version, since=since),
        "severity_distribution": get_severity_distribution(db, since=since),
        "orchestrator_version_summary": get_orchestrator_version_summary(db, last_hours=last_hours),
        "time_series_severity": get_time_series_severity(db, last_hours=last_hours),
        "feedback_summary": feedback_summary,
        "window_hours": last_hours,
    }


def get_recent_learning_logs(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    items = (
        db.query(LearningLog)
        .order_by(LearningLog.created_at.desc())
        .limit(max(1, min(int(limit or 50), 200)))
        .all()
    )
    return [item.to_dict() for item in items]
