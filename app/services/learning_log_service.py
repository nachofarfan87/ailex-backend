from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_log import LearningLog
from app.services.utc import utc_now


LEARNING_VERSION = "v1"
_REASON_WEIGHTS = {
    "low_confidence": 0.3,
    "low_decision_confidence": 0.3,
    "ambiguous_query": 0.2,
    "used_fallback": 0.2,
    "empty_retrieval": 0.2,
    "high_warning_count": 0.1,
}
_FEEDBACK_SCORE_RANGE = (1, 5)


def _json_dumps(value: Any, fallback: Any) -> str:
    try:
        return json.dumps(value if value is not None else fallback, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(fallback, ensure_ascii=False, default=str)


def _json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


def _safe_str(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or default


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            converted = value.to_dict()
            return converted if isinstance(converted, dict) else {}
        except Exception:
            return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _warning_count(orchestrator_result: Any, final_output_payload: dict[str, Any]) -> int:
    final_output = _get_attr(orchestrator_result, "final_output")
    warnings = _get_attr(final_output, "warnings", None)
    if isinstance(warnings, list):
        return len(warnings)
    payload_warnings = final_output_payload.get("warnings")
    if isinstance(payload_warnings, list):
        return len(payload_warnings)
    return 0


def _resolve_time_bucket(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.strftime("%Y-%m-%d-%H")


def _has_ambiguity_signal(raw_strategy: dict[str, Any]) -> bool:
    if bool(raw_strategy.get("ambiguity_risk")) or bool(raw_strategy.get("ambiguous_query")):
        return True

    notes = raw_strategy.get("ambiguity_notes") or raw_strategy.get("notes") or raw_strategy.get("warnings")
    if isinstance(notes, str):
        return "ambigu" in notes.lower()
    if isinstance(notes, list):
        return any(isinstance(item, str) and "ambigu" in item.lower() for item in notes)
    return False


def _active_review_reasons(flags: dict[str, bool]) -> list[str]:
    return [reason for reason in _REASON_WEIGHTS if flags.get(reason, False)]


def _compute_severity_score(review_reasons: list[str]) -> float:
    severity_score = sum(_REASON_WEIGHTS.get(reason, 0.0) for reason in review_reasons)
    return round(min(severity_score, 1.0), 4)


def _sort_review_reasons(review_reasons: list[str]) -> list[str]:
    return sorted(
        review_reasons,
        key=lambda reason: (-_REASON_WEIGHTS.get(reason, 0.0), list(_REASON_WEIGHTS).index(reason) if reason in _REASON_WEIGHTS else 999),
    )


def _validate_feedback_score(score: int | None) -> None:
    if score is None:
        return
    minimum, maximum = _FEEDBACK_SCORE_RANGE
    if int(score) < minimum or int(score) > maximum:
        raise ValueError(f"user_feedback_score debe estar entre {minimum} y {maximum}.")


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _safe_str(value)
    return normalized or None


def _has_feedback_payload(
    *,
    user_feedback_score: int | None = None,
    is_user_feedback_positive: bool | None = None,
    corrected_domain: str | None = None,
    corrected_strategy_mode: str | None = None,
    feedback_comment: str | None = None,
) -> bool:
    return any(
        [
            user_feedback_score is not None,
            is_user_feedback_positive is not None,
            _normalize_optional_text(corrected_domain) is not None,
            _normalize_optional_text(corrected_strategy_mode) is not None,
            _normalize_optional_text(feedback_comment) is not None,
        ]
    )


def _build_feedback_derived_signals(
    log: LearningLog,
    *,
    user_feedback_score: int | None = None,
    is_user_feedback_positive: bool | None = None,
    corrected_domain: str | None = None,
    corrected_strategy_mode: str | None = None,
) -> dict[str, bool]:
    effective_score = user_feedback_score if user_feedback_score is not None else log.user_feedback_score
    effective_positive = (
        bool(is_user_feedback_positive)
        if is_user_feedback_positive is not None
        else log.is_user_feedback_positive
    )
    effective_domain = _normalize_optional_text(corrected_domain) if corrected_domain is not None else _normalize_optional_text(log.corrected_domain)
    effective_strategy = _normalize_optional_text(corrected_strategy_mode) if corrected_strategy_mode is not None else _normalize_optional_text(log.corrected_strategy_mode)
    current_domain = _normalize_optional_text(log.case_domain)
    current_strategy = _normalize_optional_text(log.strategy_mode)

    feedback_has_domain_correction = bool(
        effective_domain and current_domain and effective_domain.casefold() != current_domain.casefold()
    )
    feedback_has_strategy_correction = bool(
        effective_strategy and current_strategy and effective_strategy.casefold() != current_strategy.casefold()
    )
    feedback_is_negative = bool(
        (effective_score is not None and int(effective_score) <= 2)
        or effective_positive is False
    )
    feedback_is_positive_confirmation = bool(
        (
            (effective_score is not None and int(effective_score) >= 4)
            or effective_positive is True
        )
        and not feedback_has_domain_correction
        and not feedback_has_strategy_correction
    )
    feedback_is_strong_signal = bool(
        feedback_is_negative
        or feedback_has_domain_correction
        or feedback_has_strategy_correction
    )

    return {
        "feedback_is_negative": feedback_is_negative,
        "feedback_has_domain_correction": feedback_has_domain_correction,
        "feedback_has_strategy_correction": feedback_has_strategy_correction,
        "feedback_is_strong_signal": feedback_is_strong_signal,
        "feedback_is_positive_confirmation": feedback_is_positive_confirmation,
    }


def _update_review_feedback_payload(
    log: LearningLog,
    *,
    user_feedback_score: int | None = None,
    is_user_feedback_positive: bool | None = None,
    corrected_domain: str | None = None,
    corrected_strategy_mode: str | None = None,
    feedback_comment: str | None = None,
    reviewed_by_user: bool | None = None,
    reviewed_by_admin: bool | None = None,
) -> None:
    quality_flags = _json_loads(log.quality_flags_json, {})
    review_payload = dict(quality_flags.get("review_feedback") or {})

    if user_feedback_score is not None:
        review_payload["user_feedback_score"] = int(user_feedback_score)
    if is_user_feedback_positive is not None:
        review_payload["is_user_feedback_positive"] = bool(is_user_feedback_positive)
    if corrected_strategy_mode is not None:
        review_payload["corrected_strategy_mode"] = _normalize_optional_text(corrected_strategy_mode)
    if corrected_domain is not None:
        review_payload["corrected_domain"] = _normalize_optional_text(corrected_domain)
    if feedback_comment is not None:
        review_payload["feedback_comment"] = _normalize_optional_text(feedback_comment)
    if reviewed_by_user is not None:
        review_payload["reviewed_by_user"] = bool(reviewed_by_user)
    if reviewed_by_admin is not None:
        review_payload["reviewed_by_admin"] = bool(reviewed_by_admin)
    if log.feedback_submitted_at is not None:
        review_payload["feedback_submitted_at"] = log.feedback_submitted_at.isoformat()

    review_payload.update(
        _build_feedback_derived_signals(
            log,
            user_feedback_score=user_feedback_score,
            is_user_feedback_positive=is_user_feedback_positive,
            corrected_domain=corrected_domain,
            corrected_strategy_mode=corrected_strategy_mode,
        )
    )

    if review_payload:
        quality_flags["review_feedback"] = review_payload
        log.quality_flags_json = _json_dumps(quality_flags, {})


def build_quality_flags(orchestrator_result: Any) -> dict[str, Any]:
    decision = _get_attr(orchestrator_result, "decision")
    retrieval = _get_attr(orchestrator_result, "retrieval")
    strategy = _get_attr(orchestrator_result, "strategy")
    final_output = _get_attr(orchestrator_result, "final_output")

    decision_dict = _as_dict(decision)
    retrieval_dict = _as_dict(retrieval)
    strategy_dict = _as_dict(strategy)
    final_output_dict = _as_dict(final_output)

    confidence_score = _safe_float(
        final_output_dict.get("confidence_score", strategy_dict.get("confidence_score"))
    )
    decision_confidence = _safe_float(decision_dict.get("decision_confidence"))
    fallback_used = bool(final_output_dict.get("fallback_used", strategy_dict.get("fallback_used")))
    documents_considered = _safe_int(
        final_output_dict.get("documents_considered", retrieval_dict.get("documents_considered"))
    )
    warnings_count = _warning_count(orchestrator_result, final_output_dict)
    pipeline_mode = _safe_str(decision_dict.get("pipeline_mode"))

    raw_strategy = strategy_dict.get("raw") if isinstance(strategy_dict.get("raw"), dict) else {}
    ambiguous_query = _has_ambiguity_signal(raw_strategy)

    flags = {
        "low_confidence": bool(confidence_score is not None and confidence_score < 0.5),
        "low_decision_confidence": bool(decision_confidence is not None and decision_confidence < 0.5),
        "used_fallback": fallback_used,
        "ambiguous_query": ambiguous_query,
        "light_mode_used": pipeline_mode == "light",
        "empty_retrieval": documents_considered == 0,
        "high_warning_count": warnings_count >= 3,
    }
    review_reasons = _active_review_reasons(flags)
    flags["severity_score"] = _compute_severity_score(review_reasons)
    flags["manual_review_recommended"] = (
        flags["severity_score"] >= 0.5
        or (flags["ambiguous_query"] and flags["low_confidence"])
    )
    flags["review_reasons"] = _sort_review_reasons(review_reasons)
    flags["warnings_count"] = warnings_count
    return flags


def save_learning_log(
    db: Session,
    *,
    user_id: str | None,
    session_id: str | None,
    conversation_id: str | None,
    payload: Any,
    orchestrator_result: Any,
    response_time_ms: int,
    orchestrator_version: str,
) -> LearningLog:
    normalized_input = _get_attr(orchestrator_result, "normalized_input")
    decision = _get_attr(orchestrator_result, "decision")
    classification = _get_attr(orchestrator_result, "classification")
    retrieval = _get_attr(orchestrator_result, "retrieval")
    strategy = _get_attr(orchestrator_result, "strategy")
    final_output = _get_attr(orchestrator_result, "final_output")
    timings = _get_attr(orchestrator_result, "timings")

    payload_query = _safe_str(_get_attr(payload, "query", ""))
    payload_jurisdiction = _safe_str(_get_attr(payload, "jurisdiction", ""))
    payload_forum = _safe_str(_get_attr(payload, "forum", ""))

    normalized_dict = _as_dict(normalized_input)
    decision_dict = _as_dict(decision)
    classification_dict = _as_dict(classification)
    retrieval_dict = _as_dict(retrieval)
    strategy_dict = _as_dict(strategy)
    final_output_dict = _as_dict(final_output)
    timings_dict = _as_dict(timings)

    quality_flags = build_quality_flags(orchestrator_result)
    severity_score = _safe_float(quality_flags.get("severity_score")) or 0.0

    learning_log = LearningLog(
        request_id=_safe_str(
            normalized_dict.get("request_id", final_output_dict.get("request_id"))
        ),
        user_id=_safe_str(user_id) or None,
        session_id=_safe_str(session_id) or None,
        conversation_id=_safe_str(conversation_id) or None,
        query=_safe_str(normalized_dict.get("query", payload_query)),
        jurisdiction=_safe_str(normalized_dict.get("jurisdiction", payload_jurisdiction)) or None,
        forum=_safe_str(normalized_dict.get("forum", payload_forum)) or None,
        case_domain=_safe_str(
            classification_dict.get("case_domain", final_output_dict.get("case_domain"))
        ) or None,
        action_slug=_safe_str(
            classification_dict.get("action_slug", final_output_dict.get("action_slug"))
        ) or None,
        retrieval_mode=_safe_str(
            decision_dict.get("retrieval_mode", retrieval_dict.get("source_mode"))
        ) or None,
        strategy_mode=_safe_str(
            decision_dict.get("strategy_mode", strategy_dict.get("strategy_mode"))
        ) or None,
        pipeline_mode=_safe_str(decision_dict.get("pipeline_mode")) or None,
        decision_confidence=_safe_float(decision_dict.get("decision_confidence")),
        confidence_score=_safe_float(
            final_output_dict.get("confidence_score", strategy_dict.get("confidence_score"))
        ),
        fallback_used=bool(
            final_output_dict.get("fallback_used", strategy_dict.get("fallback_used"))
        ),
        fallback_reason=_safe_str(
            final_output_dict.get("fallback_reason", strategy_dict.get("fallback_reason"))
        ) or None,
        documents_considered=_safe_int(
            final_output_dict.get("documents_considered", retrieval_dict.get("documents_considered"))
        ),
        warnings_count=_safe_int(quality_flags.get("warnings_count")),
        processing_time_ms=_safe_int(response_time_ms),
        orchestrator_decision_json=_json_dumps(decision_dict, {}),
        classification_json=_json_dumps(classification_dict, {}),
        retrieval_json=_json_dumps(retrieval_dict, {}),
        strategy_json=_json_dumps(strategy_dict, {}),
        final_output_json=_json_dumps(final_output_dict, {}),
        timings_json=_json_dumps(timings_dict, {}),
        quality_flags_json=_json_dumps(quality_flags, {}),
        severity_score=severity_score,
        reviewed_by_user=False,
        reviewed_by_admin=False,
        learning_version=LEARNING_VERSION,
        orchestrator_version=_safe_str(orchestrator_version, "unknown"),
        time_bucket=_resolve_time_bucket(),
    )

    db.add(learning_log)
    return learning_log


def submit_learning_feedback(
    db: Session,
    *,
    log_id: str,
    user_feedback_score: int | None = None,
    is_user_feedback_positive: bool | None = None,
    corrected_domain: str | None = None,
    corrected_strategy_mode: str | None = None,
    feedback_comment: str | None = None,
    reviewed_by_user: bool = True,
    reviewed_by_admin: bool = False,
) -> LearningLog | None:
    _validate_feedback_score(user_feedback_score)
    if not _has_feedback_payload(
        user_feedback_score=user_feedback_score,
        is_user_feedback_positive=is_user_feedback_positive,
        corrected_domain=corrected_domain,
        corrected_strategy_mode=corrected_strategy_mode,
        feedback_comment=feedback_comment,
    ):
        raise ValueError("Debe enviarse al menos un campo de feedback.")

    log = db.get(LearningLog, log_id)
    if log is None:
        return None

    if user_feedback_score is not None:
        log.user_feedback_score = int(user_feedback_score)
    if is_user_feedback_positive is not None:
        log.is_user_feedback_positive = bool(is_user_feedback_positive)

    normalized_domain = _normalize_optional_text(corrected_domain)
    if corrected_domain is not None and normalized_domain is not None:
        log.corrected_domain = normalized_domain

    normalized_strategy = _normalize_optional_text(corrected_strategy_mode)
    if corrected_strategy_mode is not None and normalized_strategy is not None:
        log.corrected_strategy_mode = normalized_strategy

    normalized_comment = _normalize_optional_text(feedback_comment)
    if feedback_comment is not None and normalized_comment is not None:
        log.feedback_comment = normalized_comment

    log.reviewed_by_user = bool(reviewed_by_user)
    log.reviewed_by_admin = bool(reviewed_by_admin)
    log.feedback_submitted_at = utc_now()

    _update_review_feedback_payload(
        log,
        user_feedback_score=user_feedback_score,
        is_user_feedback_positive=is_user_feedback_positive,
        corrected_domain=corrected_domain,
        corrected_strategy_mode=corrected_strategy_mode,
        feedback_comment=feedback_comment,
        reviewed_by_user=reviewed_by_user,
        reviewed_by_admin=reviewed_by_admin,
    )

    db.commit()
    db.refresh(log)
    return log


def update_learning_log_review(
    db: Session,
    *,
    log_id: str,
    user_feedback_score: int | None = None,
    user_feedback_label: str | None = None,
    review_notes: str | None = None,
    review_status: str | None = None,
    corrected_strategy_mode: str | None = None,
    corrected_domain: str | None = None,
) -> LearningLog | None:
    _validate_feedback_score(user_feedback_score)

    log = db.get(LearningLog, log_id)
    if log is None:
        return None

    if user_feedback_score is not None:
        log.user_feedback_score = int(user_feedback_score)
    if user_feedback_label is not None:
        log.user_feedback_label = _safe_str(user_feedback_label)
    if review_notes is not None:
        log.review_notes = _safe_str(review_notes)
    if review_status is not None:
        log.review_status = _safe_str(review_status, "pending")
    if corrected_strategy_mode is not None:
        normalized_strategy = _normalize_optional_text(corrected_strategy_mode)
        if normalized_strategy is not None:
            log.corrected_strategy_mode = normalized_strategy
    if corrected_domain is not None:
        normalized_domain = _normalize_optional_text(corrected_domain)
        if normalized_domain is not None:
            log.corrected_domain = normalized_domain

    _update_review_feedback_payload(
        log,
        user_feedback_score=user_feedback_score,
        corrected_strategy_mode=corrected_strategy_mode,
        corrected_domain=corrected_domain,
    )

    db.commit()
    db.refresh(log)
    return log
