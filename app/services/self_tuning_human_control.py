from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.self_tuning_override_service import (
    evaluate_active_overrides,
    get_active_override_summary,
    get_human_interventions_last_24h,
    get_system_mode,
)
from app.services.self_tuning_review_service import (
    create_review_entry,
    get_review_snapshot,
    should_enqueue_review,
)


def evaluate_human_control_before_execution(
    db: Session,
    *,
    recommendation: dict[str, Any],
    meta_snapshot: dict[str, Any],
    strategy_snapshot: dict[str, Any],
    final_action_trace: dict[str, Any],
) -> dict[str, Any]:
    recommendation_with_human = dict(recommendation)
    current_action = str(final_action_trace["action_trace"]["final_resolved_action"] or "observe_only")
    override_eval = evaluate_active_overrides(
        db,
        recommendation=recommendation_with_human,
        resolved_action=current_action,
        meta_snapshot=meta_snapshot,
    )
    recommendation_with_human = dict(override_eval["recommendation"])
    current_action = str(override_eval["final_action"] or current_action)
    system_mode = get_system_mode()

    if system_mode == "frozen":
        review_snapshot = get_review_snapshot(db)
        return {
            "recommendation": recommendation_with_human,
            "final_action": "block",
            "force_decision_override": True,
            "review_required": False,
            "review_entry_id": None,
            "system_mode": system_mode,
            "applied_overrides": override_eval["applied_overrides"],
            "blocked_overrides": override_eval["blocked_overrides"],
            "overrides_active": override_eval["overrides_active"],
            "active_override_summary": override_eval["active_override_summary"],
            "review_snapshot": review_snapshot,
            "human_interventions_last_24h": get_human_interventions_last_24h(db),
            "human_control_reason": "system_frozen",
        }

    actionable_count = sum(
        1 for candidate in recommendation_with_human.get("candidate_adjustments") or []
        if not candidate.get("blocked")
    )
    requires_review, capture_auto = should_enqueue_review(
        system_mode=system_mode,
        final_action=current_action,
        meta_confidence=float(meta_snapshot.get("meta_confidence") or 0.0),
        strategy_conflict_resolved=bool(final_action_trace["action_trace"].get("strategy_conflict_resolved", False)),
        strategy_override_applied=bool(strategy_snapshot.get("strategy_override_applied", False)),
        actionable_count=actionable_count,
        risk_flags=list(recommendation_with_human.get("risk_flags") or []),
    )

    review_entry = None
    review_status = None
    if requires_review:
        review_status = "pending"
        review_entry = create_review_entry(
            db,
            recommendation=recommendation_with_human,
            final_action=current_action,
            review_status="pending",
            requires_review=True,
        )
    elif capture_auto:
        review_status = "auto"
        review_entry = create_review_entry(
            db,
            recommendation=recommendation_with_human,
            final_action=current_action,
            review_status="auto",
            requires_review=False,
        )

    review_snapshot = get_review_snapshot(db)
    return {
        "recommendation": recommendation_with_human,
        "final_action": current_action,
        "force_decision_override": bool(override_eval["applied_overrides"]),
        "review_required": requires_review,
        "review_entry_id": getattr(review_entry, "id", None),
        "review_status": review_status,
        "system_mode": system_mode,
        "applied_overrides": override_eval["applied_overrides"],
        "blocked_overrides": override_eval["blocked_overrides"],
        "overrides_active": override_eval["overrides_active"],
        "active_override_summary": override_eval["active_override_summary"],
        "review_snapshot": review_snapshot,
        "human_interventions_last_24h": get_human_interventions_last_24h(db),
        "human_control_reason": _resolve_human_control_reason(
            system_mode=system_mode,
            requires_review=requires_review,
            applied_overrides=override_eval["applied_overrides"],
        ),
    }


def get_human_control_snapshot(db: Session) -> dict[str, Any]:
    review_snapshot = get_review_snapshot(db)
    active_override_summary = get_active_override_summary()
    return {
        **review_snapshot,
        "overrides_active": active_override_summary["total_active_overrides"],
        "active_override_summary": active_override_summary,
        "system_mode": get_system_mode(),
        "human_interventions_last_24h": get_human_interventions_last_24h(db),
    }


def _resolve_human_control_reason(
    *,
    system_mode: str,
    requires_review: bool,
    applied_overrides: list[dict[str, Any]],
) -> str | None:
    if system_mode == "manual_only" and requires_review:
        return "system_manual_only_requires_review"
    if system_mode == "review_required" and requires_review:
        return "system_review_required"
    if applied_overrides:
        return "active_human_override_applied"
    return None
