from __future__ import annotations

import copy
import json
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.user_models import User
from app.models.learning_human_audit import LearningHumanAuditLog
from app.models.learning_review import LearningReview, build_review_aging_snapshot
from app.services.self_tuning_override_service import apply_manual_delta_override, json_dumps
from app.services.utc import utc_now


REVIEW_STATUS_VALUES = {"pending", "approved", "rejected", "auto"}
REVIEW_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
RECENT_HUMAN_ACTIONS_WINDOW_HOURS = 24


def should_enqueue_review(
    *,
    system_mode: str,
    final_action: str,
    meta_confidence: float,
    strategy_conflict_resolved: bool,
    strategy_override_applied: bool,
    actionable_count: int,
    risk_flags: list[str],
) -> tuple[bool, bool]:
    relevant_change = final_action in {"apply", "simulate"} and actionable_count > 0
    low_confidence = meta_confidence < 0.6
    conflict_or_override = strategy_conflict_resolved or strategy_override_applied
    risky_context = bool(risk_flags)

    if system_mode == "frozen":
        return False, False
    if system_mode == "manual_only":
        return relevant_change or conflict_or_override or risky_context, False
    if system_mode == "review_required":
        return relevant_change or low_confidence or conflict_or_override or risky_context, False
    if low_confidence or conflict_or_override:
        return False, True
    return False, False


def create_review_entry(
    db: Session,
    *,
    recommendation: dict[str, Any],
    final_action: str,
    review_status: str,
    requires_review: bool,
    source_cycle_id: str | None = None,
) -> LearningReview:
    if review_status not in REVIEW_STATUS_VALUES:
        raise ValueError("invalid_review_status")
    primary_candidate = next(
        (
            candidate
            for candidate in recommendation.get("candidate_adjustments") or []
            if not candidate.get("blocked")
        ),
        None,
    )
    if primary_candidate is None:
        primary_candidate = next(iter(recommendation.get("candidate_adjustments") or []), None)
    review_priority, review_priority_reason = _resolve_review_priority(
        recommendation=recommendation,
        final_action=final_action,
        primary_candidate=primary_candidate,
    )

    record = LearningReview(
        review_type="self_tuning",
        source_cycle_id=source_cycle_id,
        parameter_name=str((primary_candidate or {}).get("parameter_name") or "") or None,
        proposed_delta=float((primary_candidate or {}).get("strategy_effective_delta") or (primary_candidate or {}).get("delta") or 0.0),
        final_action=str(final_action or "observe_only"),
        meta_confidence=float(recommendation.get("meta_decision", {}).get("meta_confidence") or 0.0),
        strategy_profile=str(recommendation.get("strategy_decision", {}).get("final_strategy_profile") or recommendation.get("strategy_decision", {}).get("strategy_profile") or ""),
        reason_summary=str(recommendation.get("summary") or ""),
        risk_flags_json=json.dumps(list(recommendation.get("risk_flags") or [])),
        requires_review=requires_review,
        review_priority=review_priority,
        review_priority_reason=review_priority_reason,
        review_status=review_status,
        recommendation_json=json_dumps(
            {
                "recommendation": recommendation,
                "final_action": final_action,
            }
        ),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_review_queue(
    db: Session,
    *,
    review_status: str | None = "pending",
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = db.query(LearningReview)
    if review_status and review_status != "all":
        query = query.filter(LearningReview.review_status == review_status)
    items = query.all()
    items.sort(
        key=lambda item: (
            REVIEW_PRIORITY_ORDER.get(str(item.review_priority or "medium"), REVIEW_PRIORITY_ORDER["medium"]),
            -(item.created_at.timestamp() if item.created_at else 0.0),
        )
    )
    return [item.to_dict() for item in items[: max(1, min(limit, 500))]]


def approve_review(
    db: Session,
    *,
    review_id: str,
    actor: User | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    review = _get_pending_review(db, review_id)
    payload = _load_review_payload(review)
    recommendation = dict(payload["recommendation"])
    final_action = str(payload.get("final_action") or review.final_action or "observe_only")
    outcome = _execute_review_decision(
        db,
        review=review,
        actor=actor,
        recommendation=recommendation,
        final_action=final_action,
        notes=notes,
        action_type="approve_review",
        review_status="approved",
    )
    return outcome


def reject_review(
    db: Session,
    *,
    review_id: str,
    actor: User | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    review = _get_pending_review(db, review_id)
    before_state = review.to_dict()
    review.review_status = "rejected"
    review.reviewed_by_user_id = getattr(actor, "id", None)
    review.reviewed_by_email = getattr(actor, "email", None)
    review.resolved_at = utc_now()
    review.resolution_json = json.dumps(
        {
            "final_action": "block",
            "status": "rejected",
            "notes": notes,
        }
    )
    from app.services.self_tuning_override_service import _record_human_audit

    _record_human_audit(
        db,
        actor=actor,
        action_type="reject_review",
        target_type="learning_review",
        target_id=review.id,
        before_state=before_state,
        after_state=review.to_dict(),
        notes=notes,
        review_id=review.id,
    )
    db.commit()
    db.refresh(review)
    return {"review": review.to_dict(), "outcome": {"status": "rejected"}}


def override_review(
    db: Session,
    *,
    review_id: str,
    actor: User | None = None,
    forced_action: str | None = None,
    forced_delta: float | None = None,
    block_completely: bool = False,
    notes: str | None = None,
) -> dict[str, Any]:
    review = _get_pending_review(db, review_id)
    payload = _load_review_payload(review)
    recommendation = copy.deepcopy(dict(payload["recommendation"]))
    final_action = str(forced_action or payload.get("final_action") or review.final_action or "observe_only").strip().lower()
    parameter_name = review.parameter_name

    if block_completely:
        final_action = "block"
    if forced_delta is not None and parameter_name:
        recommendation = apply_manual_delta_override(
            recommendation=recommendation,
            parameter_name=parameter_name,
            forced_delta=float(forced_delta),
        )
    _validate_manual_review_override(
        recommendation=recommendation,
        final_action=final_action,
    )

    review.manual_override_json = json.dumps(
        {
            "forced_action": final_action,
            "forced_delta": forced_delta,
            "block_completely": block_completely,
            "notes": notes,
        }
    )
    review.final_action = final_action
    review.updated_at = utc_now()

    review_status = "rejected" if final_action in {"block", "observe_only"} else "approved"
    outcome = _execute_review_decision(
        db,
        review=review,
        actor=actor,
        recommendation=recommendation,
        final_action=final_action,
        notes=notes,
        action_type="override_review",
        review_status=review_status,
    )
    return outcome


def get_review_snapshot(db: Session) -> dict[str, Any]:
    reviews = db.query(LearningReview).all()
    total_reviews = len(reviews)
    pending_items = [item for item in reviews if item.review_status == "pending"]
    pending_reviews = len(pending_items)
    pending_reviews_by_priority = {"high": 0, "medium": 0, "low": 0}
    stale_reviews_count = 0
    oldest_pending_review_hours = 0.0

    for item in pending_items:
        pending_reviews_by_priority[str(item.review_priority or "medium")] = (
            pending_reviews_by_priority.get(str(item.review_priority or "medium"), 0) + 1
        )
        aging = build_review_aging_snapshot(
            created_at=item.created_at,
            review_status=item.review_status,
        )
        if aging["is_stale"]:
            stale_reviews_count += 1
        oldest_pending_review_hours = max(oldest_pending_review_hours, float(aging["age_hours"]))

    approval_count, rejection_count, override_count, recent_human_actions_summary = _get_recent_human_action_metrics(db)
    decision_count = approval_count + rejection_count + override_count
    return {
        "review_queue_size": total_reviews,
        "pending_reviews": pending_reviews,
        "pending_reviews_by_priority": pending_reviews_by_priority,
        "stale_reviews_count": stale_reviews_count,
        "oldest_pending_review_hours": round(oldest_pending_review_hours, 2),
        "approval_rate": round(approval_count / decision_count, 4) if decision_count else 0.0,
        "rejection_rate": round(rejection_count / decision_count, 4) if decision_count else 0.0,
        "override_rate": round(override_count / decision_count, 4) if decision_count else 0.0,
        "recent_human_actions_summary": recent_human_actions_summary,
    }


def _get_pending_review(db: Session, review_id: str) -> LearningReview:
    review = db.get(LearningReview, review_id)
    if review is None:
        raise ValueError("review_not_found")
    if review.review_status != "pending":
        raise ValueError("review_already_resolved")
    return review


def _load_review_payload(review: LearningReview) -> dict[str, Any]:
    try:
        payload = json.loads(review.recommendation_json or "{}")
    except (TypeError, ValueError):
        payload = {}
    return dict(payload or {})


def _execute_review_decision(
    db: Session,
    *,
    review: LearningReview,
    actor: User | None,
    recommendation: dict[str, Any],
    final_action: str,
    notes: str | None,
    action_type: str,
    review_status: str,
) -> dict[str, Any]:
    from app.services.self_tuning_override_service import _record_human_audit
    from app.services.self_tuning_service import apply_self_tuning_adjustments

    before_state = review.to_dict()
    outcome = apply_self_tuning_adjustments(
        db,
        recommendation=recommendation,
        dry_run=False,
        persist_trace=True,
        decision_override={"recommended_action": final_action},
    )
    review.review_status = review_status
    review.reviewed_by_user_id = getattr(actor, "id", None)
    review.reviewed_by_email = getattr(actor, "email", None)
    review.resolved_at = utc_now()
    review.resolution_json = json.dumps(
        {
            "final_action": final_action,
            "outcome": outcome,
            "notes": notes,
        },
        default=str,
    )
    _record_human_audit(
        db,
        actor=actor,
        action_type=action_type,
        target_type="learning_review",
        target_id=review.id,
        before_state=before_state,
        after_state=review.to_dict(),
        notes=notes,
        review_id=review.id,
    )
    db.commit()
    db.refresh(review)
    return {"review": review.to_dict(), "outcome": outcome}


def _validate_manual_review_override(
    *,
    recommendation: dict[str, Any],
    final_action: str,
) -> None:
    meta_action = str(recommendation.get("meta_decision", {}).get("recommended_action") or "observe_only")
    if meta_action == "block" and final_action in {"apply", "simulate"}:
        raise ValueError("unsafe_override_blocked_by_meta")
    if final_action == "apply":
        for candidate in recommendation.get("candidate_adjustments") or []:
            for reason in candidate.get("blocked_reasons") or []:
                normalized_reason = str(reason)
                if normalized_reason.startswith("guardrail_") or normalized_reason.startswith("safety_envelope_"):
                    raise ValueError("unsafe_override_hard_guardrail")


def _resolve_review_priority(
    *,
    recommendation: dict[str, Any],
    final_action: str,
    primary_candidate: dict[str, Any] | None,
) -> tuple[str, str]:
    meta_decision = dict(recommendation.get("meta_decision") or {})
    strategy_decision = dict(recommendation.get("strategy_decision") or {})
    meta_confidence = float(meta_decision.get("meta_confidence") or 0.0)
    risk_flags = list(recommendation.get("risk_flags") or [])
    strategy_conflict_resolved = bool(strategy_decision.get("strategy_conflict_resolved", False))
    strategy_override_applied = bool(strategy_decision.get("strategy_override_applied", False))
    strategy_profile = str(
        strategy_decision.get("final_strategy_profile")
        or strategy_decision.get("strategy_profile")
        or ""
    )
    proposed_delta = abs(
        float((primary_candidate or {}).get("strategy_effective_delta") or (primary_candidate or {}).get("delta") or 0.0)
    )

    score = 0
    reasons: list[str] = []
    if final_action == "apply":
        score += 3
        reasons.append("apply_requires_more_attention")
    elif final_action == "simulate":
        score += 1
        reasons.append("simulate_review")
    if meta_confidence < 0.45:
        score += 2
        reasons.append("low_meta_confidence")
    elif meta_confidence < 0.6:
        score += 1
        reasons.append("reduced_meta_confidence")
    if strategy_conflict_resolved:
        score += 2
        reasons.append("meta_strategy_conflict")
    if strategy_override_applied:
        score += 1
        reasons.append("strategy_override_applied")
    if risk_flags:
        score += 1
        reasons.append("risk_flags_present")
    if proposed_delta >= 1 or proposed_delta >= 0.03:
        score += 1
        reasons.append("material_delta")
    if strategy_profile in {"restricted_adjustment", "observe_only_strategy"}:
        score += 1
        reasons.append("restrictive_strategy_profile")

    if score >= 5:
        return "high", ", ".join(reasons[:4]) or "high_sensitivity_review"
    if score >= 2:
        return "medium", ", ".join(reasons[:4]) or "standard_review_priority"
    return "low", ", ".join(reasons[:4]) or "low_sensitivity_review"


def _get_recent_human_action_metrics(
    db: Session,
) -> tuple[int, int, int, dict[str, Any]]:
    recent_actions = (
        db.query(LearningHumanAuditLog)
        .filter(LearningHumanAuditLog.created_at >= utc_now() - timedelta(hours=RECENT_HUMAN_ACTIONS_WINDOW_HOURS))
        .order_by(LearningHumanAuditLog.created_at.desc())
        .all()
    )
    actions_by_type: dict[str, int] = {}
    for item in recent_actions:
        action_type = str(item.action_type or "unknown")
        actions_by_type[action_type] = actions_by_type.get(action_type, 0) + 1

    approval_count = actions_by_type.get("approve_review", 0)
    rejection_count = actions_by_type.get("reject_review", 0)
    override_count = actions_by_type.get("override_review", 0)
    recent_human_actions_summary = {
        "window_hours": RECENT_HUMAN_ACTIONS_WINDOW_HOURS,
        "total_actions": len(recent_actions),
        "actions_by_type": actions_by_type,
        "latest_action_at": recent_actions[0].created_at.isoformat() if recent_actions else None,
    }
    return approval_count, rejection_count, override_count, recent_human_actions_summary
