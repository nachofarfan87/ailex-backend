from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.system_safety_event import SystemSafetyEvent
from app.services.safety_classifier import classify_severity, get_protective_mode_status, record_breaker_event
from app.services.safety_constants import (
    FALLBACK_TYPE_VALUES,
    RECENT_SAFETY_WINDOW_HOURS,
    SAFETY_STATUS_PRIORITY,
)
from app.services.utc import utc_now


def record_safety_event(
    db: Session,
    *,
    event_type: str,
    safety_status: str,
    dominant_safety_reason: str | None = None,
    fallback_type: str | None = None,
    request_id: str | None = None,
    user_id: str | None = None,
    source_ip: str | None = None,
    route_path: str | None = None,
    reason: str | None = None,
    reason_category: str | None = None,
    excluded_from_learning: bool = False,
    detail: dict[str, Any] | None = None,
    severity: str | None = None,
    protective_mode_active: bool | None = None,
) -> SystemSafetyEvent:
    normalized_ft = normalize_fallback_type(fallback_type)
    resolved_severity = severity or classify_severity(
        event_type=str(event_type or ""),
        safety_status=str(safety_status or "normal"),
        fallback_type=normalized_ft,
    )
    if protective_mode_active is None:
        pm = get_protective_mode_status()
        protective_mode_active = pm["protective_mode_active"]

    # Feed circuit breaker
    record_breaker_event(event_type=str(event_type or ""), fallback_type=normalized_ft)

    event = SystemSafetyEvent(
        request_id=str(request_id or "").strip() or None,
        user_id=str(user_id or "").strip() or None,
        source_ip=str(source_ip or "").strip() or None,
        route_path=str(route_path or "").strip() or None,
        event_type=str(event_type or "").strip(),
        safety_status=str(safety_status or "normal").strip(),
        dominant_safety_reason=str(dominant_safety_reason or "").strip(),
        fallback_type=normalized_ft,
        reason=str(reason or "").strip(),
        reason_category=str(reason_category or "").strip(),
        excluded_from_learning=bool(excluded_from_learning),
        severity=resolved_severity,
        protective_mode_active=bool(protective_mode_active),
        detail_json=json.dumps(detail or {}, default=str),
    )
    if not all(hasattr(db, attr) for attr in ("add", "commit", "refresh")):
        return event
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_safety_snapshot(
    db: Session,
    *,
    last_hours: int = RECENT_SAFETY_WINDOW_HOURS,
    recent_limit: int = 10,
) -> dict[str, Any]:
    since = utc_now() - timedelta(hours=max(last_hours, 1))
    query = (
        db.query(SystemSafetyEvent)
        .filter(SystemSafetyEvent.created_at >= since)
        .order_by(SystemSafetyEvent.created_at.desc())
    )
    recent_events = query.limit(max(recent_limit, 1)).all()
    all_recent_events = query.all()
    reason_counts = Counter(
        str(item.reason or item.reason_category or "unknown")
        for item in all_recent_events
        if str(item.reason or item.reason_category or "").strip()
    )
    status_counts = Counter(str(item.safety_status or "normal") for item in all_recent_events)
    active_safety_status = _resolve_active_safety_status(status_counts)

    # Severity breakdown
    severity_counts = Counter(str(getattr(item, "severity", None) or "info") for item in all_recent_events)

    # Fallback type breakdown
    fallback_counts = Counter(
        str(item.fallback_type)
        for item in all_recent_events
        if item.fallback_type
    )

    # Error-like events (internal_error, timeout)
    error_like_count = sum(
        1 for item in all_recent_events
        if item.fallback_type in {"internal_error", "timeout"}
    )

    # Fallback triggered count
    fallback_triggered_count = sum(
        1 for item in all_recent_events
        if item.event_type == "fallback_triggered"
    )

    total_events = len(all_recent_events)
    excluded_count = sum(1 for item in all_recent_events if item.excluded_from_learning)

    # Protective mode status
    pm_status = get_protective_mode_status()

    return {
        "rejected_inputs_count": sum(1 for item in all_recent_events if item.event_type == "input_rejected"),
        "degraded_requests_count": sum(
            1 for item in all_recent_events if item.event_type in {"request_degraded", "fallback_triggered"}
        ),
        "rate_limited_requests_count": sum(1 for item in all_recent_events if item.event_type == "rate_limited"),
        "excluded_from_learning_count": excluded_count,
        "error_like_events_count": error_like_count,
        "fallback_triggered_count": fallback_triggered_count,
        "total_safety_events": total_events,
        "active_safety_status": active_safety_status,
        "dominant_safety_reason": next(
            (
                item.dominant_safety_reason or item.reason
                for item in all_recent_events
                if str(item.dominant_safety_reason or item.reason or "").strip()
            ),
            None,
        ),
        "severity_breakdown": dict(severity_counts),
        "fallback_type_breakdown": dict(fallback_counts),
        "excluded_from_learning_rate": round(excluded_count / total_events, 4) if total_events else 0.0,
        "protective_mode_active": pm_status["protective_mode_active"],
        "protective_mode_reason": pm_status["protective_mode_reason"],
        "recent_safety_events": [item.to_dict() for item in recent_events],
        "top_safety_reasons": [{"reason": reason, "count": count} for reason, count in reason_counts.most_common(5)],
    }


def should_exclude_from_learning(
    *,
    input_guardrail: dict[str, Any],
    rate_limit_guardrail: dict[str, Any],
    response_payload: dict[str, Any] | None = None,
) -> bool:
    if input_guardrail.get("excluded_from_learning"):
        return True
    if not rate_limit_guardrail.get("allowed", True):
        return True
    payload = dict(response_payload or {})
    return bool(payload.get("fallback_used", False))


def resolve_safety_outcome(*signals: dict[str, Any]) -> dict[str, Any]:
    normalized_signals: list[dict[str, Any]] = []
    for raw_signal in signals:
        signal = dict(raw_signal or {})
        safety_status = str(signal.get("safety_status") or "normal").strip() or "normal"
        reasons = list(dict.fromkeys(signal.get("reasons") or []))
        normalized_signals.append(
            {
                "safety_status": safety_status,
                "reasons": reasons,
                "dominant_safety_reason": signal.get("dominant_safety_reason") or (reasons[0] if reasons else None),
                "fallback_type": normalize_fallback_type(signal.get("fallback_type")),
            }
        )
    if not normalized_signals:
        normalized_signals.append(
            {
                "safety_status": "normal",
                "reasons": [],
                "dominant_safety_reason": None,
                "fallback_type": None,
            }
        )
    sorted_signals = sorted(
        normalized_signals,
        key=lambda item: SAFETY_STATUS_PRIORITY.get(item["safety_status"], SAFETY_STATUS_PRIORITY["normal"]),
    )
    dominant_signal = sorted_signals[0]
    combined_reasons: list[str] = []
    for signal in sorted_signals:
        combined_reasons.extend(signal["reasons"])
    fallback_type = dominant_signal["fallback_type"]
    if not fallback_type:
        fallback_type = next((item["fallback_type"] for item in sorted_signals if item["fallback_type"]), None)
    return {
        "safety_status": dominant_signal["safety_status"],
        "dominant_safety_reason": dominant_signal["dominant_safety_reason"],
        "fallback_type": fallback_type,
        "safety_reasons": list(dict.fromkeys(combined_reasons)),
    }


def normalize_fallback_type(fallback_type: str | None) -> str | None:
    normalized = str(fallback_type or "").strip().lower()
    if not normalized:
        return None
    if normalized in FALLBACK_TYPE_VALUES:
        return normalized
    return "degraded_mode"


def infer_fallback_type(*, fallback_reason: str | None = None, safety_status: str | None = None) -> str | None:
    normalized_reason = str(fallback_reason or "").strip().lower()
    normalized_status = str(safety_status or "").strip().lower()
    if normalized_status == "input_rejected":
        return "input_invalid"
    if normalized_status == "rate_limited":
        return "rate_limited"
    if "timeout" in normalized_reason:
        return "timeout"
    if any(term in normalized_reason for term in ("insufficient", "no_evidence", "low_evidence", "insufficient_data")):
        return "insufficient_data"
    if any(term in normalized_reason for term in ("internal", "orchestrator_error", "processing_error", "controlled_orchestrator_error")):
        return "internal_error"
    if normalized_reason:
        return "degraded_mode"
    return None


def _resolve_active_safety_status(status_counts: Counter[str]) -> str:
    resolved = resolve_safety_outcome(
        *({"safety_status": status, "reasons": []} for status, count in status_counts.items() if count > 0)
    )
    return resolved["safety_status"]
