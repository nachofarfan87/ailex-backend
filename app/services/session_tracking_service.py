from __future__ import annotations

import json
from collections import Counter
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.session_analytics import AnalyticsSession, AnalyticsSessionEvent
from app.services.analytics_insight_service import generate_analytics_insights
from app.services.auto_healing_service import build_recommended_actions, get_primary_action
from app.services.utc import utc_now


TRACKED_EVENT_TYPES = {
    "session_started",
    "user_query_submitted",
    "assistant_response_rendered",
    "clarification_entered",
    "clarification_answer_received",
    "clarification_exited",
    "advice_rendered",
    "quick_reply_clicked",
    "quick_reply_submitted",
    "closure_reached",
    "session_reset",
    "history_restored",
    "error_backend",
    "error_validation",
}

_MAX_TEXT_LENGTH = 240


def ensure_session_id(session_id: str | None = None) -> str:
    normalized = str(session_id or "").strip()
    return normalized or str(uuid4())


def ensure_session(
    db: Session,
    *,
    session_id: str,
    user_id: str | None = None,
    case_domain: str | None = None,
    jurisdiction: str | None = None,
) -> tuple[AnalyticsSession, bool]:
    session = db.get(AnalyticsSession, session_id)
    created = session is None
    now = utc_now()
    if session is None:
        session = AnalyticsSession(
            session_id=session_id,
            user_id=_clean_text(user_id) or None,
            started_at=now,
            last_activity_at=now,
            status="active",
            first_case_domain=_clean_text(case_domain),
            latest_case_domain=_clean_text(case_domain),
            first_jurisdiction=_clean_text(jurisdiction),
            latest_jurisdiction=_clean_text(jurisdiction),
        )
        db.add(session)
        db.flush()
        return session, created

    session.last_activity_at = now
    if not session.user_id and _clean_text(user_id):
        session.user_id = _clean_text(user_id)
    if _clean_text(case_domain):
        if not _clean_text(session.first_case_domain):
            session.first_case_domain = _clean_text(case_domain)
        session.latest_case_domain = _clean_text(case_domain)
    if _clean_text(jurisdiction):
        if not _clean_text(session.first_jurisdiction):
            session.first_jurisdiction = _clean_text(jurisdiction)
        session.latest_jurisdiction = _clean_text(jurisdiction)
    db.flush()
    return session, created


def record_event(
    db: Session,
    *,
    session_id: str,
    event_type: str,
    user_id: str | None = None,
    turn_index: int | None = None,
    case_domain: str | None = None,
    jurisdiction: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AnalyticsSessionEvent:
    if event_type not in TRACKED_EVENT_TYPES:
        raise ValueError(f"Unsupported tracking event: {event_type}")

    session, created = ensure_session(
        db,
        session_id=session_id,
        user_id=user_id,
        case_domain=case_domain,
        jurisdiction=jurisdiction,
    )
    if created:
        _create_event(
            db,
            session_id=session.session_id,
            user_id=session.user_id,
            event_type="session_started",
            turn_index=None,
            case_domain=session.first_case_domain,
            jurisdiction=session.first_jurisdiction,
            payload={"created_by": "tracking_service"},
        )

    event = _create_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        turn_index=turn_index,
        case_domain=case_domain,
        jurisdiction=jurisdiction,
        payload=payload,
    )
    _apply_session_side_effects(
        session,
        event_type=event_type,
        payload=payload or {},
        case_domain=case_domain,
        jurisdiction=jurisdiction,
    )
    db.commit()
    db.refresh(session)
    db.refresh(event)
    return event


def track_legal_query_cycle(
    db: Session,
    *,
    session_id: str,
    user_id: str | None,
    query: str,
    jurisdiction: str | None,
    case_domain: str | None,
    conversational: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> None:
    safe_conversational = conversational or {}
    safe_metadata = metadata or {}
    session, created = ensure_session(
        db,
        session_id=session_id,
        user_id=user_id,
        case_domain=case_domain,
        jurisdiction=jurisdiction,
    )
    if created:
        _create_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event_type="session_started",
            case_domain=case_domain,
            jurisdiction=jurisdiction,
            payload={"created_by": "legal_query"},
        )

    turn_index = session.total_user_turns + 1
    known_facts = _as_dict(safe_conversational.get("known_facts"))
    completeness = _as_dict(safe_conversational.get("case_completeness"))
    used_quick_reply = bool(_as_dict(safe_metadata.get("quick_reply")))
    user_payload = {
        "query_length": len(_clean_text(query)),
        "used_quick_reply": used_quick_reply,
        "known_facts_count": len(known_facts),
        "missing_critical_count": len(_as_str_list(completeness.get("missing_critical"))),
        "missing_optional_count": len(_as_str_list(completeness.get("missing_optional"))),
    }
    _create_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="user_query_submitted",
        turn_index=turn_index,
        case_domain=case_domain,
        jurisdiction=jurisdiction,
        payload=user_payload,
    )
    session.total_turns += 1
    session.total_user_turns += 1

    if _as_dict(safe_metadata.get("clarification_context")):
        _create_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event_type="clarification_answer_received",
            turn_index=turn_index,
            case_domain=case_domain,
            jurisdiction=jurisdiction,
            payload={
                "known_facts_count": len(known_facts),
            },
        )

    if used_quick_reply:
        quick_reply = _as_dict(safe_metadata.get("quick_reply"))
        _create_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event_type="quick_reply_submitted",
            turn_index=turn_index,
            case_domain=case_domain,
            jurisdiction=jurisdiction,
            payload={
                "selected_option": _clean_text(quick_reply.get("selected_option")),
                "submitted_text": _clean_text(quick_reply.get("submitted_text")),
            },
        )

    assistant_mode = "clarification" if bool(safe_conversational.get("should_ask_first")) else "advice"
    assistant_payload = {
        "mode": assistant_mode,
        "question_text": _clean_text(safe_conversational.get("question")),
        "closure_reached": _is_closure_reached(safe_conversational),
        "known_facts_count": len(known_facts),
        "missing_critical_count": len(_as_str_list(completeness.get("missing_critical"))),
        "missing_optional_count": len(_as_str_list(completeness.get("missing_optional"))),
    }
    _create_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type="assistant_response_rendered",
        turn_index=turn_index,
        case_domain=case_domain,
        jurisdiction=jurisdiction,
        payload=assistant_payload,
    )
    session.total_turns += 1
    session.total_assistant_turns += 1

    if assistant_mode == "clarification":
        session.clarification_turns += 1
        _create_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event_type="clarification_entered",
            turn_index=turn_index,
            case_domain=case_domain,
            jurisdiction=jurisdiction,
            payload={"question_text": _clean_text(safe_conversational.get("question"))},
        )
    else:
        session.advice_turns += 1
        if session.first_advice_at is None:
            session.first_advice_at = utc_now()
        _create_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event_type="advice_rendered",
            turn_index=turn_index,
            case_domain=case_domain,
            jurisdiction=jurisdiction,
            payload={"closure_reached": _is_closure_reached(safe_conversational)},
        )
        if _as_dict(safe_metadata.get("clarification_context")):
            _create_event(
                db,
                session_id=session_id,
                user_id=user_id,
                event_type="clarification_exited",
                turn_index=turn_index,
                case_domain=case_domain,
                jurisdiction=jurisdiction,
                payload={"known_facts_count": len(known_facts)},
            )

    if _is_closure_reached(safe_conversational):
        session.closure_reached = True
        session.status = "completed"
        session.ended_at = utc_now()
        _create_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event_type="closure_reached",
            turn_index=turn_index,
            case_domain=case_domain,
            jurisdiction=jurisdiction,
            payload={"message": _clean_text(safe_conversational.get("message"))},
        )

    session.last_activity_at = utc_now()
    if _clean_text(case_domain):
        if not _clean_text(session.first_case_domain):
            session.first_case_domain = _clean_text(case_domain)
        session.latest_case_domain = _clean_text(case_domain)
    if _clean_text(jurisdiction):
        if not _clean_text(session.first_jurisdiction):
            session.first_jurisdiction = _clean_text(jurisdiction)
        session.latest_jurisdiction = _clean_text(jurisdiction)
    db.commit()


def track_backend_error(
    db: Session,
    *,
    session_id: str,
    user_id: str | None,
    error_type: str,
    message: str,
    jurisdiction: str | None = None,
) -> None:
    record_event(
        db,
        session_id=session_id,
        user_id=user_id,
        event_type=error_type,
        jurisdiction=jurisdiction,
        payload={"message": _clean_text(message)},
    )


def build_summary(db: Session) -> dict[str, Any]:
    sessions = db.query(AnalyticsSession).all()
    events = db.query(AnalyticsSessionEvent).all()
    total_sessions = len(sessions)
    active_sessions = sum(1 for session in sessions if session.status == "active")
    completed_sessions = sum(1 for session in sessions if session.status == "completed")
    abandoned_sessions = sum(1 for session in sessions if session.status == "abandoned")
    effective_sessions = sum(
        1
        for session in sessions
        if session.closure_reached and int(session.advice_turns or 0) > 0
    )
    avg_turns = round(sum(session.total_turns for session in sessions) / total_sessions, 2) if total_sessions else 0.0
    clarification_sessions = sum(1 for session in sessions if session.clarification_turns > 0)
    closure_sessions = sum(1 for session in sessions if session.closure_reached)
    quick_reply_sessions = len(
        {
            event.session_id
            for event in events
            if event.event_type == "quick_reply_submitted"
        }
    )

    advice_durations: list[float] = []
    for session in sessions:
        if session.started_at and session.first_advice_at:
            delta = session.first_advice_at - session.started_at
            advice_durations.append(max(delta.total_seconds(), 0.0))

    domain_counter = Counter()
    question_counter = Counter()
    quick_reply_counter = Counter()
    dropoff_counter = Counter()
    for session in sessions:
        domain = _clean_text(session.latest_case_domain or session.first_case_domain)
        if domain:
            domain_counter[domain] += 1
        if session.status == "abandoned":
            dropoff_turn = int(session.total_user_turns or 0)
            if dropoff_turn > 0:
                dropoff_counter[dropoff_turn] += 1
    for event in events:
        payload = _safe_json_loads(event.payload_json, {})
        if event.event_type == "clarification_entered":
            question = _clean_text(payload.get("question_text"))
            if question:
                question_counter[question] += 1
        if event.event_type == "quick_reply_submitted":
            selected_option = _clean_text(payload.get("selected_option"))
            if selected_option:
                quick_reply_counter[selected_option] += 1

    summary = {
        "total_sessions": total_sessions,
        "active_sessions": active_sessions,
        "completed_sessions": completed_sessions,
        "abandoned_sessions": abandoned_sessions,
        "avg_turns_per_session": avg_turns,
        "clarification_rate": _safe_rate(clarification_sessions, total_sessions),
        "closure_rate": _safe_rate(closure_sessions, total_sessions),
        "quick_reply_rate": _safe_rate(quick_reply_sessions, total_sessions),
        "effective_sessions_rate": _safe_rate(effective_sessions, total_sessions),
        "avg_time_to_advice_seconds": round(sum(advice_durations) / len(advice_durations), 2) if advice_durations else None,
        "top_case_domains": _top_counter(domain_counter),
        "top_clarification_questions": _top_counter(question_counter),
        "top_quick_replies": _top_counter(quick_reply_counter),
        "dropoff_by_turn": _dropoff_by_turn(dropoff_counter, total_sessions),
    }
    summary["insights"] = generate_analytics_insights(summary)
    summary["recommended_actions"] = build_recommended_actions(summary["insights"])
    summary["primary_action"] = get_primary_action(summary["insights"])
    return summary


def _create_event(
    db: Session,
    *,
    session_id: str,
    user_id: str | None = None,
    event_type: str,
    turn_index: int | None = None,
    case_domain: str | None = None,
    jurisdiction: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AnalyticsSessionEvent:
    event = AnalyticsSessionEvent(
        session_id=session_id,
        user_id=_clean_text(user_id) or None,
        event_type=event_type,
        turn_index=turn_index,
        case_domain=_clean_text(case_domain),
        jurisdiction=_clean_text(jurisdiction),
        payload_json=json.dumps(_sanitize_payload(payload or {}), ensure_ascii=False),
    )
    db.add(event)
    db.flush()
    return event


def _apply_session_side_effects(
    session: AnalyticsSession,
    *,
    event_type: str,
    payload: dict[str, Any],
    case_domain: str | None,
    jurisdiction: str | None,
) -> None:
    now = utc_now()
    session.last_activity_at = now
    if _clean_text(case_domain):
        if not _clean_text(session.first_case_domain):
            session.first_case_domain = _clean_text(case_domain)
        session.latest_case_domain = _clean_text(case_domain)
    if _clean_text(jurisdiction):
        if not _clean_text(session.first_jurisdiction):
            session.first_jurisdiction = _clean_text(jurisdiction)
        session.latest_jurisdiction = _clean_text(jurisdiction)

    if event_type == "session_reset" and session.status == "active" and not session.closure_reached:
        session.status = "abandoned"
        session.ended_at = now
    if event_type == "closure_reached":
        session.closure_reached = True
        session.status = "completed"
        session.ended_at = now
    if event_type == "advice_rendered" and session.first_advice_at is None:
        session.first_advice_at = now
    if event_type == "quick_reply_submitted":
        session.last_activity_at = now


def _is_closure_reached(conversational: dict[str, Any]) -> bool:
    message = _clean_text(conversational.get("message"))
    return message.startswith("Con esto ya tengo una base clara para orientarte.")


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        normalized = _sanitize_value(value)
        if normalized in (None, "", [], {}):
            continue
        sanitized[_clean_text(key)] = normalized
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value[:10] if _sanitize_value(item) not in (None, "", [], {})]
    if isinstance(value, dict):
        nested: dict[str, Any] = {}
        for key, nested_value in list(value.items())[:12]:
            normalized = _sanitize_value(nested_value)
            if normalized in (None, "", [], {}):
                continue
            nested[_clean_text(key)] = normalized
        return nested
    return _truncate_text(str(value))


def _truncate_text(value: str) -> str:
    text = _clean_text(value)
    if len(text) <= _MAX_TEXT_LENGTH:
        return text
    return f"{text[:_MAX_TEXT_LENGTH - 3].rstrip()}..."


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _top_counter(counter: Counter[str], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"value": value, "count": count}
        for value, count in counter.most_common(limit)
    ]


def _dropoff_by_turn(counter: Counter[int], total_sessions: int, limit: int = 5) -> list[dict[str, Any]]:
    if total_sessions <= 0:
        return []
    return [
        {"turn": turn, "count": count, "rate": _safe_rate(count, total_sessions)}
        for turn, count in counter.most_common(limit)
    ]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())
