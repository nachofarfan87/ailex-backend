from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.auto_healing_event import AutoHealingEvent
from app.models.learning_action_log import LearningActionLog
from app.services import (
    baseline_service,
    conversation_insights_service,
    drift_policy,
    learning_observability_service,
    live_alert_policy,
    priority_engine,
)
from app.services.auto_healing_service import get_auto_healing_snapshot
from app.services.baseline_constants import (
    BASELINE_DEFAULT_LOOKBACK_DAYS,
    BASELINE_MAX_LOOKBACK_DAYS,
    BASELINE_MIN_LOOKBACK_DAYS,
)
from app.services.conversation_observability_service import CONVERSATION_LOG_PATH
from app.services.learning_safety_service import get_safety_snapshot
from app.services.live_alert_constants import (
    LIVE_ALERT_DEFAULT_EVENT_LIMIT,
    LIVE_ALERT_DEFAULT_WINDOW_HOURS,
    LIVE_ALERT_MAX_EVENT_LIMIT,
    LIVE_ALERT_MAX_WINDOW_HOURS,
    LIVE_ALERT_MIN_EVENT_LIMIT,
    LIVE_ALERT_MIN_WINDOW_HOURS,
    LIVE_ALERT_SOURCE,
)
from app.services.live_alert_registry import ALERT_METRIC_REGISTRY
from app.services.self_tuning_review_service import get_review_snapshot
from app.services.utc import utc_now


def get_live_alert_snapshot(
    db: Session,
    *,
    last_hours: int = LIVE_ALERT_DEFAULT_WINDOW_HOURS,
    event_limit: int = LIVE_ALERT_DEFAULT_EVENT_LIMIT,
    baseline_days: int = BASELINE_DEFAULT_LOOKBACK_DAYS,
    log_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_hours = _normalize_last_hours(last_hours)
    resolved_limit = _normalize_event_limit(event_limit)
    resolved_baseline_days = _normalize_baseline_days(baseline_days)
    now = utc_now()
    recent_start = now - timedelta(hours=resolved_hours)
    previous_start = recent_start - timedelta(hours=resolved_hours)
    baseline_start = recent_start - timedelta(days=resolved_baseline_days)
    log_path_value = Path(log_path) if log_path is not None else CONVERSATION_LOG_PATH

    all_turns = conversation_insights_service.load_conversation_logs(log_path=log_path_value)
    recent_turns = _select_turns(all_turns, since=recent_start, limit=resolved_limit)
    previous_turns = _select_turns(all_turns, since=previous_start, until=recent_start, limit=resolved_limit)
    historical_turns = _select_turns(all_turns, since=baseline_start, until=recent_start, limit=None)

    recent_conversation_metrics = conversation_insights_service.calculate_metrics(recent_turns)
    previous_conversation_metrics = conversation_insights_service.calculate_metrics(previous_turns)
    action_confidence_stats = _get_action_confidence_stats(db, since=recent_start, until=None, limit=resolved_limit)
    previous_action_confidence_stats = _get_action_confidence_stats(db, since=previous_start, until=recent_start, limit=resolved_limit)
    previous_auto_healing_snapshot = _get_auto_healing_snapshot_for_range(
        db,
        since=previous_start,
        until=recent_start,
        recent_limit=min(resolved_limit, 50),
    )
    recent_event_count = max(
        len(recent_turns),
        _safe_int(action_confidence_stats.get("total_actions")),
    )

    context = {
        "window": {
            "mode": "mixed",
            "last_hours": resolved_hours,
            "event_limit": resolved_limit,
            "recent_event_count": recent_event_count,
        },
        "recent_conversation_metrics": recent_conversation_metrics,
        "previous_conversation_metrics": previous_conversation_metrics,
        "recent_safety_snapshot": get_safety_snapshot(db, last_hours=resolved_hours, recent_limit=min(resolved_limit, 50)),
        "previous_safety_snapshot": _get_previous_safety_snapshot(db, previous_start=previous_start, recent_start=recent_start, recent_limit=min(resolved_limit, 50)),
        "review_snapshot": get_review_snapshot(db),
        "auto_healing_snapshot": get_auto_healing_snapshot(db, last_hours=resolved_hours, recent_limit=min(resolved_limit, 50)),
        "previous_auto_healing_snapshot": previous_auto_healing_snapshot,
        "action_confidence_stats": action_confidence_stats,
        "previous_action_confidence_stats": previous_action_confidence_stats,
        "family_metrics_recent": learning_observability_service.get_metrics_by_family(db, date_from=recent_start, date_to=now, limit=min(resolved_limit, 200)),
        "family_metrics_previous": learning_observability_service.get_metrics_by_family(db, date_from=previous_start, date_to=recent_start, limit=min(resolved_limit, 200)),
        "signature_metrics_recent": learning_observability_service.get_metrics_by_signature(db, date_from=recent_start, date_to=now, limit=min(resolved_limit, 200)),
        "signature_metrics_previous": learning_observability_service.get_metrics_by_signature(db, date_from=previous_start, date_to=recent_start, limit=min(resolved_limit, 200)),
    }

    baseline_context = baseline_service.build_operational_baseline(
        db,
        recent_start=recent_start,
        recent_end=now,
        recent_window_hours=resolved_hours,
        event_limit=resolved_limit,
        log_path=log_path_value,
        baseline_days=resolved_baseline_days,
        historical_turns=historical_turns,
    )
    drift_context = drift_policy.build_drift_context(context, baseline_context, detected_at=_to_aware(now))
    alerts = live_alert_policy.evaluate_live_alerts(context, detected_at=_to_aware(now))
    enriched_alerts = _enrich_alerts(alerts, baseline_context=baseline_context, drift_context=drift_context)
    prioritized_alerts = priority_engine.enrich_alert_priorities(enriched_alerts)
    return {
        "generated_at": _to_aware(now).isoformat(),
        "source": LIVE_ALERT_SOURCE,
        "window": context["window"],
        "has_data": bool(recent_event_count),
        "summary": _build_summary(prioritized_alerts, drift_context=drift_context),
        "alerts": prioritized_alerts,
        "baseline_summary": baseline_context.get("summary") or {},
        "drift_summary": drift_context.get("summary") or {},
        "top_prioritized_alerts": prioritized_alerts[:3],
        "sources": {
            "conversation_log_path": str(log_path_value),
            "recent_turn_count": len(recent_turns),
            "recent_action_count": _safe_int(context["action_confidence_stats"].get("total_actions")),
            "recent_family_metric_count": len(context["family_metrics_recent"]),
            "recent_signature_metric_count": len(context["signature_metrics_recent"]),
        },
    }


def _build_summary(alerts: list[dict[str, Any]], *, drift_context: dict[str, Any] | None = None) -> dict[str, Any]:
    severity_counter = Counter()
    category_counter = Counter()
    priority_counter = Counter()
    surfaced = 0
    for alert in alerts:
        severity_counter[_clean_text(alert.get("severity")) or "info"] += 1
        category_counter[_clean_text(alert.get("category")) or "unknown"] += 1
        priority_counter[_clean_text(alert.get("priority_level")) or "low"] += 1
        if bool(alert.get("should_surface_to_ui")):
            surfaced += 1
    return {
        "total_alerts": len(alerts),
        "surfaced_alerts": surfaced,
        "by_severity": dict(severity_counter),
        "by_category": dict(category_counter),
        "by_priority_level": dict(priority_counter),
        "active_categories": sorted(category_counter.keys()),
        "top_prioritized_alert_ids": [str(alert.get("alert_id")) for alert in alerts[:3]],
        "active_drift_count": _safe_int(_as_dict(_as_dict(drift_context).get("summary")).get("total_active_drifts")),
    }


def _select_turns(
    turns: list[dict[str, Any]],
    *,
    since: datetime,
    until: datetime | None = None,
    limit: int | None,
) -> list[dict[str, Any]]:
    since_aware = _to_aware(since)
    until_aware = _to_aware(until) if until is not None else None
    filtered: list[dict[str, Any]] = []
    for turn in turns:
        timestamp = _parse_timestamp(turn.get("timestamp"))
        if timestamp is None:
            continue
        if timestamp < since_aware:
            continue
        if until_aware is not None and timestamp >= until_aware:
            continue
        filtered.append(turn)
    filtered.sort(key=lambda item: _parse_timestamp(item.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
    if limit is not None and len(filtered) > limit:
        filtered = filtered[-limit:]
    return filtered


def _get_previous_safety_snapshot(
    db: Session,
    *,
    previous_start: datetime,
    recent_start: datetime,
    recent_limit: int,
) -> dict[str, Any]:
    # No existe hoy una API de safety por ventana arbitraria; mantenemos una version prudente y backward-compatible.
    return _get_safety_snapshot_for_range(db, since=previous_start, until=recent_start, recent_limit=recent_limit)


def _get_safety_snapshot_for_range(
    db: Session,
    *,
    since: datetime,
    until: datetime,
    recent_limit: int,
) -> dict[str, Any]:
    from app.models.system_safety_event import SystemSafetyEvent

    events = (
        db.query(SystemSafetyEvent)
        .filter(SystemSafetyEvent.created_at >= since)
        .filter(SystemSafetyEvent.created_at < until)
        .order_by(SystemSafetyEvent.created_at.desc())
        .all()
    )
    severity_breakdown = Counter(_clean_text(item.severity) or "info" for item in events)
    fallback_breakdown = Counter(_clean_text(item.fallback_type) for item in events if _clean_text(item.fallback_type))
    reason_breakdown = Counter(
        _clean_text(item.reason or item.reason_category or item.dominant_safety_reason)
        for item in events
        if _clean_text(item.reason or item.reason_category or item.dominant_safety_reason)
    )
    return {
        "total_safety_events": len(events),
        "protective_mode_active": any(bool(item.protective_mode_active) for item in events),
        "severity_breakdown": dict(severity_breakdown),
        "fallback_type_breakdown": dict(fallback_breakdown),
        "recent_safety_events": [item.to_dict() for item in events[: max(recent_limit, 1)]],
        "top_safety_reasons": [{"reason": reason, "count": count} for reason, count in reason_breakdown.most_common(5)],
    }


def _get_action_confidence_stats(
    db: Session,
    *,
    since: datetime,
    until: datetime | None = None,
    limit: int,
) -> dict[str, Any]:
    query = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.created_at >= since)
        .order_by(LearningActionLog.created_at.desc())
    )
    if until is not None:
        query = query.filter(LearningActionLog.created_at < until)
    recent_actions = query.limit(limit).all()
    low_threshold = 0.5
    low_count = 0
    confidence_values: list[float] = []
    output_mode_counter = Counter()
    for action in recent_actions:
        confidence = _safe_float(action.confidence_score)
        if action.confidence_score is not None:
            confidence_values.append(confidence)
        if action.confidence_score is not None and confidence < low_threshold:
            low_count += 1
        payload = _safe_json_loads(action.changes_applied_json)
        output_mode = _clean_text(payload.get("output_mode"))
        if output_mode:
            output_mode_counter[output_mode] += 1
    return {
        "total_actions": len(recent_actions),
        "low_confidence_threshold": low_threshold,
        "low_confidence_count": low_count,
        "low_confidence_ratio": round(low_count / max(len(recent_actions), 1), 4),
        "avg_confidence": round(sum(confidence_values) / max(len(confidence_values), 1), 4) if confidence_values else 0.0,
        "output_modes": dict(output_mode_counter),
    }


def _enrich_alerts(
    alerts: list[dict[str, Any]],
    *,
    baseline_context: dict[str, Any],
    drift_context: dict[str, Any],
) -> list[dict[str, Any]]:
    drifts = list(drift_context.get("drifts") or [])
    enriched: list[dict[str, Any]] = []
    for alert in alerts:
        safe_alert = dict(alert or {})
        baseline_entry = _select_baseline_context_for_alert(safe_alert, baseline_context)
        related_drift = _select_drift_for_alert(safe_alert, drifts)
        if baseline_entry:
            safe_alert["baseline_context"] = baseline_entry
        if related_drift:
            safe_alert["drift"] = related_drift
        enriched.append(safe_alert)
    return enriched


def _select_baseline_context_for_alert(
    alert: dict[str, Any],
    baseline_context: dict[str, Any],
) -> dict[str, Any]:
    category = _clean_text(alert.get("category"))
    registry_entry = _as_dict(ALERT_METRIC_REGISTRY.get(category))
    if not registry_entry:
        return {}

    scope = _clean_text(registry_entry.get("scope")) or "global"
    baseline_metrics = [str(item) for item in list(registry_entry.get("baseline_metrics") or []) if str(item).strip()]
    globals_map = _as_dict(baseline_context.get("global_metrics"))
    families_map = _as_dict(baseline_context.get("family_metrics"))
    signatures_map = _as_dict(baseline_context.get("signature_metrics"))

    if scope == "global":
        for metric_name in baseline_metrics:
            baseline_entry = _as_dict(globals_map.get(metric_name))
            if baseline_entry:
                return baseline_entry
        return {}
    if scope == "family":
        return _as_dict(families_map.get(_clean_text(alert.get("related_family"))))
    if scope == "signature":
        return _as_dict(signatures_map.get(_clean_text(alert.get("related_signature"))))
    return {}


def _select_drift_for_alert(
    alert: dict[str, Any],
    drifts: list[dict[str, Any]],
) -> dict[str, Any]:
    category = _clean_text(alert.get("category"))
    registry_entry = _as_dict(ALERT_METRIC_REGISTRY.get(category))
    if not registry_entry:
        return {}

    target_scope = _clean_text(registry_entry.get("scope")) or "global"
    target_metrics = {str(item) for item in list(registry_entry.get("drift_metrics") or []) if str(item).strip()}
    related_family = _clean_text(alert.get("related_family"))
    related_signature = _clean_text(alert.get("related_signature"))
    matches: list[dict[str, Any]] = []
    for drift in drifts:
        safe_drift = _as_dict(drift)
        if _clean_text(safe_drift.get("scope")) != target_scope:
            continue
        if _clean_text(safe_drift.get("metric_name")) not in target_metrics:
            continue
        if target_scope == "family" and _clean_text(safe_drift.get("related_family")) != related_family:
            continue
        if target_scope == "signature" and _clean_text(safe_drift.get("related_signature")) != related_signature:
            continue
        matches.append(safe_drift)
    if not matches:
        return {}
    matches.sort(key=_drift_match_sort_key)
    return matches[0]


def _get_auto_healing_snapshot_for_range(
    db: Session,
    *,
    since: datetime,
    until: datetime,
    recent_limit: int,
) -> dict[str, Any]:
    events = (
        db.query(AutoHealingEvent)
        .filter(AutoHealingEvent.created_at >= since)
        .filter(AutoHealingEvent.created_at < until)
        .order_by(AutoHealingEvent.created_at.desc())
        .all()
    )
    action_breakdown = Counter(_clean_text(item.action_type) or "unknown" for item in events)
    situation_breakdown = Counter(_clean_text(item.situation) or "unknown" for item in events)
    return {
        "auto_healing_status": _clean_text(events[0].situation) if events else "normal",
        "recovery_counter": 0,
        "system_mode_effective": _clean_text(events[0].system_mode) if events else "auto",
        "protective_mode_active": any(bool(item.protective_mode_active) for item in events),
        "recovery_progress": 0.0,
        "total_events_last_24h": len(events),
        "applied_actions_count": sum(1 for item in events if bool(item.action_applied)),
        "recommended_actions_count": sum(1 for item in events if not bool(item.action_applied)),
        "action_breakdown": dict(action_breakdown),
        "situation_breakdown": dict(situation_breakdown),
        "recent_auto_healing_events": [item.to_dict() for item in events[: max(recent_limit, 1)]],
    }


def _normalize_last_hours(value: int) -> int:
    return max(LIVE_ALERT_MIN_WINDOW_HOURS, min(int(value or LIVE_ALERT_DEFAULT_WINDOW_HOURS), LIVE_ALERT_MAX_WINDOW_HOURS))


def _normalize_event_limit(value: int) -> int:
    return max(LIVE_ALERT_MIN_EVENT_LIMIT, min(int(value or LIVE_ALERT_DEFAULT_EVENT_LIMIT), LIVE_ALERT_MAX_EVENT_LIMIT))


def _normalize_baseline_days(value: int) -> int:
    return max(BASELINE_MIN_LOOKBACK_DAYS, min(int(value or BASELINE_DEFAULT_LOOKBACK_DAYS), BASELINE_MAX_LOOKBACK_DAYS))


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


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


def _drift_match_sort_key(item: dict[str, Any]) -> tuple[int, int, float]:
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    return (
        severity_order.get(_clean_text(item.get("severity")), 9),
        confidence_order.get(_clean_text(item.get("confidence")), 9),
        -_safe_float(item.get("absolute_delta")),
    )
