from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.auto_healing_event import AutoHealingEvent
from app.models.learning_action_log import LearningActionLog
from app.models.system_safety_event import SystemSafetyEvent
from app.services import conversation_insights_service, learning_observability_service
from app.services.baseline_constants import (
    BASELINE_DEFAULT_LOOKBACK_DAYS,
    BASELINE_HIGH_CONFIDENCE_SEGMENT_OBSERVATIONS,
    BASELINE_MAX_LOOKBACK_DAYS,
    BASELINE_MIN_LOOKBACK_DAYS,
    BASELINE_MIN_SEGMENT_OBSERVATIONS,
    BASELINE_SOURCE,
)


def build_operational_baseline(
    db: Session,
    *,
    recent_start: datetime,
    recent_end: datetime,
    recent_window_hours: int,
    event_limit: int,
    log_path: str | Path,
    baseline_days: int = BASELINE_DEFAULT_LOOKBACK_DAYS,
    historical_turns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_baseline_days = _normalize_baseline_days(baseline_days)
    baseline_start = recent_start - timedelta(days=resolved_baseline_days)

    turns = list(historical_turns or _load_historical_turns(log_path=Path(log_path), since=baseline_start, until=recent_start))
    conversation_metrics = conversation_insights_service.calculate_metrics(turns)

    historical_actions = _load_actions(db, since=baseline_start, until=recent_start)
    historical_safety_events = _load_safety_events(db, since=baseline_start, until=recent_start)
    historical_auto_healing_events = _load_auto_healing_events(db, since=baseline_start, until=recent_start)

    global_metrics = _build_global_metrics(
        conversation_metrics=conversation_metrics,
        action_logs=historical_actions,
        safety_events=historical_safety_events,
        auto_healing_events=historical_auto_healing_events,
    )
    family_baselines = _build_family_baselines(
        db,
        baseline_start=baseline_start,
        baseline_end=recent_start,
        limit=max(min(event_limit * 4, 500), 100),
    )
    signature_baselines = _build_signature_baselines(
        db,
        baseline_start=baseline_start,
        baseline_end=recent_start,
        limit=max(min(event_limit * 4, 500), 100),
    )

    return {
        "source": BASELINE_SOURCE,
        "baseline_window": {
            "mode": "aggregate",
            "baseline_days": resolved_baseline_days,
            "bucket_hours": max(recent_window_hours, 1),
            "start": _to_aware(baseline_start).isoformat(),
            "end": _to_aware(recent_start).isoformat(),
            "recent_window_start": _to_aware(recent_start).isoformat(),
            "recent_window_end": _to_aware(recent_end).isoformat(),
            "event_limit": event_limit,
        },
        "global_metrics": global_metrics,
        "family_metrics": family_baselines,
        "signature_metrics": signature_baselines,
        "summary": {
            "global_metrics_available": sum(1 for item in global_metrics.values() if bool(item.get("available"))),
            "global_metrics_low_sample": sum(1 for item in global_metrics.values() if bool(item.get("low_sample"))),
            "family_baselines_available": sum(1 for item in family_baselines.values() if bool(item.get("available"))),
            "family_baselines_low_sample": sum(1 for item in family_baselines.values() if bool(item.get("low_sample"))),
            "signature_baselines_available": sum(1 for item in signature_baselines.values() if bool(item.get("available"))),
            "signature_baselines_low_sample": sum(1 for item in signature_baselines.values() if bool(item.get("low_sample"))),
        },
    }


def _build_global_metrics(
    *,
    conversation_metrics: dict[str, Any],
    action_logs: list[LearningActionLog],
    safety_events: list[SystemSafetyEvent],
    auto_healing_events: list[AutoHealingEvent],
) -> dict[str, dict[str, Any]]:
    volume = _as_dict(conversation_metrics.get("volume"))
    progress = _as_dict(conversation_metrics.get("progress"))
    output_modes = _as_dict(conversation_metrics.get("output_modes"))
    friction = _as_dict(conversation_metrics.get("friction"))

    total_conversations = _safe_int(volume.get("total_conversations"))
    total_turns = _safe_int(volume.get("total_turns"))
    safety_total = len(safety_events)
    action_total = len(action_logs)
    auto_healing_total = len(auto_healing_events)

    low_confidence_count = sum(
        1 for item in action_logs
        if item.confidence_score is not None and _safe_float(item.confidence_score) < 0.5
    )
    protective_count = sum(
        1 for item in safety_events
        if bool(item.protective_mode_active)
        or _clean_text(item.event_type) == "fallback_triggered"
        or _clean_text(item.fallback_type) in {"internal_error", "timeout", "degraded_mode"}
    )
    hardening_related = sum(
        1 for item in auto_healing_events
        if _clean_text(item.action_type) in {"harden_protective_mode", "activate_protective_mode"}
    )

    return {
        "resolution_rate": _build_global_entry(
            metric_name="resolution_rate",
            value=_safe_div(_safe_int(progress.get("conversations_with_progress")), total_conversations),
            sample_count=total_conversations,
        ),
        "clarification_ratio": _build_global_entry(
            metric_name="clarification_ratio",
            value=_safe_float(output_modes.get("clarification_ratio")),
            sample_count=total_turns,
        ),
        "loop_rate": _build_global_entry(
            metric_name="loop_rate",
            value=_safe_div(len(list(friction.get("loop_conversations") or [])), total_conversations),
            sample_count=total_conversations,
        ),
        "protective_mode_ratio": _build_global_entry(
            metric_name="protective_mode_ratio",
            value=_safe_div(protective_count, safety_total),
            sample_count=safety_total,
        ),
        "low_confidence_ratio": _build_global_entry(
            metric_name="low_confidence_ratio",
            value=_safe_div(low_confidence_count, action_total),
            sample_count=action_total,
        ),
        "hardening_rate": _build_global_entry(
            metric_name="hardening_rate",
            value=_safe_div(hardening_related, auto_healing_total),
            sample_count=auto_healing_total,
        ),
    }


def _build_global_entry(
    *,
    metric_name: str,
    value: float,
    sample_count: int,
) -> dict[str, Any]:
    available = sample_count >= BASELINE_MIN_SEGMENT_OBSERVATIONS
    return {
        "metric_name": metric_name,
        "available": available,
        "low_sample": not available,
        "status": "ok" if available else "low_sample",
        "confidence": _resolve_segment_confidence(sample_count),
        "baseline_value": round(value, 4) if available else None,
        "sample_count": sample_count,
        "min_sample_count": BASELINE_MIN_SEGMENT_OBSERVATIONS,
    }


def _build_family_baselines(
    db: Session,
    *,
    baseline_start: datetime,
    baseline_end: datetime,
    limit: int,
) -> dict[str, dict[str, Any]]:
    items = learning_observability_service.get_metrics_by_family(
        db,
        date_from=baseline_start,
        date_to=baseline_end,
        limit=limit,
    )
    baselines: dict[str, dict[str, Any]] = {}
    for item in items:
        safe_item = _as_dict(item)
        family = _clean_text(safe_item.get("signature_family"))
        if not family:
            continue
        observation_count = _safe_int(safe_item.get("observation_count"))
        baselines[family] = {
            "scope": "family",
            "related_family": family,
            "event_type": _clean_text(safe_item.get("event_type")) or None,
            "available": observation_count >= BASELINE_MIN_SEGMENT_OBSERVATIONS,
            "low_sample": observation_count < BASELINE_MIN_SEGMENT_OBSERVATIONS,
            "status": _resolve_segment_status(observation_count),
            "confidence": _resolve_segment_confidence(observation_count),
            "observation_count": observation_count,
            "avg_score": _safe_float(safe_item.get("avg_score")),
            "regressed_ratio": _safe_div(_safe_int(safe_item.get("negative_count")), observation_count),
            "positive_count": _safe_int(safe_item.get("positive_count")),
            "negative_count": _safe_int(safe_item.get("negative_count")),
            "neutral_count": _safe_int(safe_item.get("neutral_count")),
        }
    return baselines


def _build_signature_baselines(
    db: Session,
    *,
    baseline_start: datetime,
    baseline_end: datetime,
    limit: int,
) -> dict[str, dict[str, Any]]:
    items = learning_observability_service.get_metrics_by_signature(
        db,
        date_from=baseline_start,
        date_to=baseline_end,
        limit=limit,
    )
    baselines: dict[str, dict[str, Any]] = {}
    for item in items:
        safe_item = _as_dict(item)
        signature = _clean_text(safe_item.get("signature"))
        if not signature:
            continue
        observation_count = _safe_int(safe_item.get("observation_count"))
        baselines[signature] = {
            "scope": "signature",
            "related_signature": signature,
            "related_family": _clean_text(safe_item.get("signature_family")) or None,
            "event_type": _clean_text(safe_item.get("event_type")) or None,
            "available": observation_count >= BASELINE_MIN_SEGMENT_OBSERVATIONS,
            "low_sample": observation_count < BASELINE_MIN_SEGMENT_OBSERVATIONS,
            "status": _resolve_segment_status(observation_count),
            "confidence": _resolve_segment_confidence(observation_count),
            "observation_count": observation_count,
            "avg_score": _safe_float(safe_item.get("avg_score")),
            "regressed_ratio": _safe_div(_safe_int(safe_item.get("negative_count")), observation_count),
            "positive_count": _safe_int(safe_item.get("positive_count")),
            "negative_count": _safe_int(safe_item.get("negative_count")),
            "neutral_count": _safe_int(safe_item.get("neutral_count")),
        }
    return baselines


def _load_historical_turns(
    *,
    log_path: Path,
    since: datetime,
    until: datetime,
) -> list[dict[str, Any]]:
    turns = conversation_insights_service.load_conversation_logs(log_path=log_path)
    since_aware = _to_aware(since)
    until_aware = _to_aware(until)
    return [
        turn
        for turn in turns
        if (timestamp := _parse_timestamp(turn.get("timestamp"))) is not None
        and since_aware <= timestamp < until_aware
    ]


def _load_actions(
    db: Session,
    *,
    since: datetime,
    until: datetime,
) -> list[LearningActionLog]:
    return (
        db.query(LearningActionLog)
        .filter(LearningActionLog.created_at >= since)
        .filter(LearningActionLog.created_at < until)
        .all()
    )


def _load_safety_events(
    db: Session,
    *,
    since: datetime,
    until: datetime,
) -> list[SystemSafetyEvent]:
    return (
        db.query(SystemSafetyEvent)
        .filter(SystemSafetyEvent.created_at >= since)
        .filter(SystemSafetyEvent.created_at < until)
        .all()
    )


def _load_auto_healing_events(
    db: Session,
    *,
    since: datetime,
    until: datetime,
) -> list[AutoHealingEvent]:
    return (
        db.query(AutoHealingEvent)
        .filter(AutoHealingEvent.created_at >= since)
        .filter(AutoHealingEvent.created_at < until)
        .all()
    )


def _normalize_baseline_days(value: int) -> int:
    return max(BASELINE_MIN_LOOKBACK_DAYS, min(int(value or BASELINE_DEFAULT_LOOKBACK_DAYS), BASELINE_MAX_LOOKBACK_DAYS))


def _resolve_segment_confidence(observation_count: int) -> str:
    if observation_count >= BASELINE_HIGH_CONFIDENCE_SEGMENT_OBSERVATIONS:
        return "high"
    if observation_count >= BASELINE_MIN_SEGMENT_OBSERVATIONS:
        return "medium"
    return "low"


def _resolve_segment_status(observation_count: int) -> str:
    return "ok" if observation_count >= BASELINE_MIN_SEGMENT_OBSERVATIONS else "low_sample"


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _to_aware(parsed)


def _to_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_div(numerator: float | int, denominator: float | int) -> float:
    try:
        denominator_value = float(denominator)
        if denominator_value <= 0:
            return 0.0
        return round(float(numerator) / denominator_value, 4)
    except (TypeError, ValueError):
        return 0.0
