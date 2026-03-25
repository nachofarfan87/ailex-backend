from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_decision_audit_log import LearningDecisionAuditLog


CRITICAL_FLAGS = {"applied_then_regressed", "high_risk_failure"}


def get_learning_governance_summary(
    db: Session,
    limit: int = 100,
) -> dict[str, Any]:
    effective_limit = max(0, int(limit or 0))
    if effective_limit == 0:
        return _empty_summary()

    audit_logs = (
        db.query(LearningDecisionAuditLog)
        .order_by(LearningDecisionAuditLog.created_at.desc())
        .limit(effective_limit)
        .all()
    )

    if not audit_logs:
        return _empty_summary()

    audited_count = len(audit_logs)
    confirmed_count = sum(1 for log in audit_logs if str(log.audit_status or "") == "confirmed")
    questionable_count = sum(1 for log in audit_logs if str(log.audit_status or "") == "questionable")
    failed_count = sum(1 for log in audit_logs if str(log.audit_status or "") == "failed")
    rollback_candidates = sum(1 for log in audit_logs if str(log.recommended_action or "") == "rollback_candidate")
    review_candidates = sum(1 for log in audit_logs if str(log.recommended_action or "") == "review")

    flag_counter: Counter[str] = Counter()
    for log in audit_logs:
        for flag in _safe_json_loads(log.audit_flags_json):
            normalized_flag = str(flag or "").strip()
            if normalized_flag:
                flag_counter[normalized_flag] += 1

    top_flags = [
        {"flag": flag, "count": count}
        for flag, count in sorted(flag_counter.items(), key=lambda item: (-item[1], item[0]))[:10]
    ]

    status = _resolve_governance_status(
        audited_count=audited_count,
        questionable_count=questionable_count,
        failed_count=failed_count,
        rollback_candidates=rollback_candidates,
        critical_flag_count=sum(flag_counter.get(flag, 0) for flag in CRITICAL_FLAGS),
    )

    return {
        "audited_count": audited_count,
        "confirmed_count": confirmed_count,
        "questionable_count": questionable_count,
        "failed_count": failed_count,
        "rollback_candidates": rollback_candidates,
        "review_candidates": review_candidates,
        "status": status,
        "top_flags": top_flags,
    }


def _resolve_governance_status(
    *,
    audited_count: int,
    questionable_count: int,
    failed_count: int,
    rollback_candidates: int,
    critical_flag_count: int,
) -> str:
    if audited_count <= 0:
        return "healthy"

    failed_ratio = failed_count / audited_count
    questionable_ratio = questionable_count / audited_count
    rollback_ratio = rollback_candidates / audited_count
    critical_ratio = critical_flag_count / audited_count

    if (
        failed_ratio > 0.25
        or rollback_ratio >= 0.10
        or critical_ratio >= 0.15
    ):
        return "degraded"

    if failed_ratio >= 0.10 or questionable_ratio >= 0.35:
        return "watch"

    return "healthy"


def _safe_json_loads(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if isinstance(value, list):
        return value
    return []


def _empty_summary() -> dict[str, Any]:
    return {
        "audited_count": 0,
        "confirmed_count": 0,
        "questionable_count": 0,
        "failed_count": 0,
        "rollback_candidates": 0,
        "review_candidates": 0,
        "status": "healthy",
        "top_flags": [],
    }
