from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.services import learning_runtime_config
from app.services.learning_governance_service import get_learning_governance_summary
from app.services.learning_runtime_config_store import load_latest_runtime_config, save_runtime_config
from app.services.utc import utc_now


WATCH_FLAGS = {"simulation_overconfidence", "applied_then_regressed"}
PROTECTIVE_FLAGS = {"high_risk_failure", "applied_then_regressed"}
THRESHOLD_MIN = 0.0
THRESHOLD_MAX = 1.0


def resolve_governance_feedback(
    db: Session,
    limit: int = 100,
) -> dict[str, Any]:
    governance_summary = get_learning_governance_summary(db, limit=limit)
    decision = evaluate_governance_feedback(governance_summary)
    latest_runtime_config = dict(load_latest_runtime_config(db) or {})

    result = {
        **decision,
        "governance_summary": governance_summary,
        "applied": False,
        "action_log_id": None,
        "feedback_state": "none",
        "skip_reason": None,
    }

    if not decision["should_apply"]:
        return result

    if _is_feedback_already_active(
        runtime_config=latest_runtime_config,
        decision=decision,
    ):
        result["feedback_state"] = "already_active"
        result["skip_reason"] = "feedback_mode_already_active"
        return result

    action_log = _apply_governance_feedback(
        db=db,
        governance_summary=governance_summary,
        decision=decision,
    )
    result["applied"] = True
    result["action_log_id"] = action_log.id
    result["feedback_state"] = "applied"
    return result


def evaluate_governance_feedback(governance_summary: dict[str, Any] | None) -> dict[str, Any]:
    governance_summary = dict(governance_summary or {})
    status = str(governance_summary.get("status") or "healthy").strip().lower()
    audited_count = _safe_int(governance_summary.get("audited_count"))
    failed_count = _safe_int(governance_summary.get("failed_count"))
    rollback_candidates = _safe_int(governance_summary.get("rollback_candidates"))
    review_candidates = _safe_int(governance_summary.get("review_candidates"))
    top_flags = governance_summary.get("top_flags") or []
    flag_counts = _normalize_top_flags(top_flags)

    trigger_flags: list[str] = []
    feedback_mode = "none"
    severity = "low"

    if status == "degraded":
        feedback_mode = "protective"
        severity = "high"
        trigger_flags.append("governance_degraded")
    elif status == "watch":
        feedback_mode = "cautious"
        severity = "medium"
        trigger_flags.append("governance_watch")

    if rollback_candidates >= 3 or (audited_count > 0 and rollback_candidates / audited_count >= 0.10):
        feedback_mode = "protective"
        severity = "high"
        trigger_flags.append("rollback_candidates_elevated")

    if _has_flag_pressure(flag_counts, "simulation_overconfidence", minimum=3, ratio_base=audited_count, ratio_threshold=0.12):
        if feedback_mode == "none":
            feedback_mode = "cautious"
            severity = "medium"
        trigger_flags.append("simulation_overconfidence_pressure")

    if any(_has_flag_pressure(flag_counts, flag, minimum=2, ratio_base=audited_count, ratio_threshold=0.10) for flag in PROTECTIVE_FLAGS):
        feedback_mode = "protective"
        severity = "high"
        trigger_flags.append("critical_governance_pattern")
    elif any(_has_flag_pressure(flag_counts, flag, minimum=2, ratio_base=audited_count, ratio_threshold=0.08) for flag in WATCH_FLAGS):
        if feedback_mode == "none":
            feedback_mode = "cautious"
            severity = "medium"
        trigger_flags.append("recurrent_governance_pattern")

    if review_candidates >= 5 or (audited_count > 0 and review_candidates / audited_count >= 0.25):
        if feedback_mode == "none":
            feedback_mode = "cautious"
            severity = "medium"
        trigger_flags.append("review_volume_elevated")

    trigger_flags = list(dict.fromkeys(trigger_flags))
    proposed_adjustments = _build_proposed_adjustments(feedback_mode)
    should_apply = feedback_mode != "none"
    reasoning = _build_reasoning(
        status=status,
        audited_count=audited_count,
        failed_count=failed_count,
        rollback_candidates=rollback_candidates,
        review_candidates=review_candidates,
        feedback_mode=feedback_mode,
        trigger_flags=trigger_flags,
    )

    return {
        "should_apply": should_apply,
        "feedback_mode": feedback_mode,
        "feedback_state": "none",
        "skip_reason": None,
        "reasoning": reasoning,
        "trigger_flags": trigger_flags,
        "proposed_adjustments": proposed_adjustments,
        "severity": severity,
    }


def _apply_governance_feedback(
    *,
    db: Session,
    governance_summary: dict[str, Any],
    decision: dict[str, Any],
) -> LearningActionLog:
    previous_runtime_config = dict(load_latest_runtime_config(db) or learning_runtime_config.get_effective_runtime_config() or {})
    previous_thresholds = dict(previous_runtime_config.get("thresholds") or learning_runtime_config.get_runtime_config().get("thresholds") or {})

    learning_runtime_config.apply_persisted_runtime_config(previous_runtime_config)
    threshold_adjustments = dict(decision.get("proposed_adjustments", {}).get("threshold_adjustments") or {})
    for key, delta in threshold_adjustments.items():
        current_value = _safe_float(previous_thresholds.get(key))
        next_value = _clamp_threshold(current_value + _safe_float(delta))
        learning_runtime_config.update_threshold(key, next_value)

    runtime_config = learning_runtime_config.get_effective_runtime_config()
    persisted_runtime_config = {
        **runtime_config,
        "governance_controls": {
            "feedback_mode": decision.get("feedback_mode", "none"),
            "severity": decision.get("severity", "low"),
            "adjustments": dict(decision.get("proposed_adjustments") or {}),
            "trigger_flags": list(decision.get("trigger_flags") or []),
            "applied_at": utc_now().isoformat(),
        },
    }
    save_runtime_config(db, persisted_runtime_config)

    action_log = LearningActionLog(
        event_type="governance_feedback",
        recommendation_type="governance_feedback_loop",
        applied=True,
        reason=str(decision.get("reasoning") or "governance_feedback_applied"),
        confidence_score=None,
        priority=None,
        impact_status="pending",
        applied_at=utc_now(),
        evidence_json=json.dumps(
            {
                "governance_summary": governance_summary,
                "trigger_flags": list(decision.get("trigger_flags") or []),
                "feedback_mode": decision.get("feedback_mode", "none"),
                "severity": decision.get("severity", "low"),
                "previous_state": previous_runtime_config,
            }
        ),
        changes_applied_json=json.dumps(
            {
                "proposed_adjustments": dict(decision.get("proposed_adjustments") or {}),
                "runtime_config": persisted_runtime_config,
            }
        ),
    )
    db.add(action_log)
    db.commit()
    db.refresh(action_log)
    return action_log


def _build_proposed_adjustments(feedback_mode: str) -> dict[str, Any]:
    if feedback_mode == "cautious":
        return {
            "budget_caps": {
                "max_changes_cap": 2,
                "max_high_risk_changes": 0,
            },
            "threshold_adjustments": {
                "low_confidence": 0.05,
                "low_decision_confidence": 0.05,
            },
            "uncertain_apply_policy": "restricted",
        }
    if feedback_mode == "protective":
        return {
            "budget_caps": {
                "max_changes_cap": 1,
                "max_high_risk_changes": 0,
            },
            "threshold_adjustments": {
                "low_confidence": 0.1,
                "low_decision_confidence": 0.1,
            },
            "uncertain_apply_policy": "blocked",
            "block_high_risk_changes": True,
        }
    return {}


def _is_feedback_already_active(
    *,
    runtime_config: dict[str, Any],
    decision: dict[str, Any],
) -> bool:
    governance_controls = dict(runtime_config.get("governance_controls") or {})
    active_mode = str(governance_controls.get("feedback_mode") or "none").strip().lower()
    current_adjustments = dict(governance_controls.get("adjustments") or {})
    proposed_adjustments = dict(decision.get("proposed_adjustments") or {})
    return (
        active_mode == str(decision.get("feedback_mode") or "none").strip().lower()
        and current_adjustments == proposed_adjustments
        and active_mode != "none"
    )


def _build_reasoning(
    *,
    status: str,
    audited_count: int,
    failed_count: int,
    rollback_candidates: int,
    review_candidates: int,
    feedback_mode: str,
    trigger_flags: list[str],
) -> str:
    return (
        f"Governance feedback evaluado con status={status or 'unknown'}, "
        f"audited_count={audited_count}, failed_count={failed_count}, "
        f"rollback_candidates={rollback_candidates}, review_candidates={review_candidates}, "
        f"feedback_mode={feedback_mode}, triggers={','.join(trigger_flags[:5]) if trigger_flags else 'none'}"
    )


def _normalize_top_flags(top_flags: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in top_flags if isinstance(top_flags, list) else []:
        if not isinstance(item, dict):
            continue
        flag = str(item.get("flag") or "").strip()
        if not flag:
            continue
        counts[flag] = _safe_int(item.get("count"))
    return counts


def _has_flag_pressure(
    flag_counts: dict[str, int],
    flag: str,
    *,
    minimum: int,
    ratio_base: int,
    ratio_threshold: float,
) -> bool:
    count = _safe_int(flag_counts.get(flag))
    if count >= minimum:
        return True
    if ratio_base > 0 and (count / ratio_base) >= ratio_threshold:
        return True
    return False


def _clamp_threshold(value: float) -> float:
    return round(max(THRESHOLD_MIN, min(THRESHOLD_MAX, float(value))), 4)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
