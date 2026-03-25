from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.models.learning_decision_audit_log import LearningDecisionAuditLog
from app.models.learning_impact_log import LearningImpactLog


def get_latest_impact_for_action(db: Session, learning_action_log_id: str) -> LearningImpactLog | None:
    return (
        db.query(LearningImpactLog)
        .filter(LearningImpactLog.learning_action_log_id == str(learning_action_log_id))
        .order_by(LearningImpactLog.created_at.desc())
        .first()
    )


def audit_learning_decision(
    db: Session,
    learning_action_log_id: str,
) -> dict[str, Any]:
    action_log = db.get(LearningActionLog, learning_action_log_id)
    if action_log is None:
        raise ValueError("learning_action_log_not_found")

    impact_log = get_latest_impact_for_action(db, action_log.id)
    return evaluate_decision_audit(action_log=action_log, impact_log=impact_log)


def create_decision_audit_log(
    db: Session,
    learning_action_log_id: str,
) -> dict[str, Any]:
    action_log = db.get(LearningActionLog, learning_action_log_id)
    if action_log is None:
        raise ValueError("learning_action_log_not_found")

    impact_log = get_latest_impact_for_action(db, action_log.id)
    result = evaluate_decision_audit(action_log=action_log, impact_log=impact_log)
    audit_log = LearningDecisionAuditLog(
        learning_action_log_id=action_log.id,
        event_type=str(action_log.event_type or ""),
        audit_status=result["audit_status"],
        audit_score=result["audit_score"],
        decision_quality=result["decision_quality"],
        recommended_action=result["recommended_action"],
        reasoning=result["reasoning"],
        audit_flags_json=_safe_json_dumps(result["audit_flags"]),
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log.to_dict()


def evaluate_decision_audit(
    *,
    action_log: LearningActionLog,
    impact_log: LearningImpactLog | None,
) -> dict[str, Any]:
    payload = _safe_json_loads(action_log.changes_applied_json, {})
    final_learning_decision = dict(payload.get("final_learning_decision") or {})
    simulation_snapshot = dict(payload.get("simulation_snapshot") or {})
    operational_risk = dict(payload.get("operational_risk") or {})
    budget_override = dict(payload.get("budget_override") or {})

    audit_flags: list[str] = []
    score = 0.0
    applied = bool(action_log.applied)
    confidence_score = _safe_float(action_log.confidence_score)
    impact_label = ""
    decision_class = str(final_learning_decision.get("decision_class") or "").strip().lower()

    if budget_override:
        audit_flags.append("budget_override_present")

    if impact_log is None:
        audit_flags.append("insufficient_impact_data")
        return {
            "audit_status": "insufficient_data",
            "audit_score": 0.0,
            "decision_quality": "unknown",
            "reasoning": _build_reasoning(
                audit_status="insufficient_data",
                applied=applied,
                impact_label="unknown",
                score=0.0,
                audit_flags=audit_flags,
                decision_class=decision_class,
            ),
            "audit_flags": audit_flags,
            "recommended_action": "monitor",
        }

    impact_label = str(impact_log.impact_label or impact_log.status or "").strip().lower()

    if not impact_label:
        audit_flags.append("insufficient_impact_data")
        return {
            "audit_status": "insufficient_data",
            "audit_score": 0.0,
            "decision_quality": "unknown",
            "reasoning": _build_reasoning(
                audit_status="insufficient_data",
                applied=applied,
                impact_label="unknown",
                score=0.0,
                audit_flags=audit_flags,
                decision_class=decision_class,
            ),
            "audit_flags": audit_flags,
            "recommended_action": "monitor",
        }

    expected_outcome = str(simulation_snapshot.get("expected_outcome") or "uncertain").strip().lower()
    simulation_confidence = _safe_float(simulation_snapshot.get("confidence_score"))
    risk_level = str(operational_risk.get("risk_level") or "medium").strip().lower()

    if applied:
        if impact_label == "improved":
            score += 0.65
            audit_flags.append("applied_then_improved")
        elif impact_label == "neutral":
            score += 0.05
            audit_flags.append("neutral_outcome_after_apply")
        elif impact_label == "regressed":
            score -= 0.70
            audit_flags.append("applied_then_regressed")
        else:
            audit_flags.append("insufficient_impact_data")
            return {
                "audit_status": "insufficient_data",
                "audit_score": 0.0,
                "decision_quality": "unknown",
                "reasoning": _build_reasoning(
                    audit_status="insufficient_data",
                    applied=applied,
                    impact_label="unknown",
                    score=0.0,
                    audit_flags=audit_flags,
                    decision_class=decision_class,
                ),
                "audit_flags": audit_flags,
                "recommended_action": "monitor",
            }

        if expected_outcome == "positive" and impact_label == "regressed":
            score -= 0.20
            audit_flags.append("positive_simulation_mismatch")
        if confidence_score >= 0.85 and impact_label == "regressed":
            score -= 0.15
            audit_flags.append("high_confidence_miss")
        if risk_level == "high" and impact_label == "regressed":
            score -= 0.20
            audit_flags.append("high_risk_failure")
    else:
        if budget_override:
            score += 0.10
        elif decision_class in {"skip", "defer"}:
            score += 0.0

        if impact_label == "improved":
            score -= 0.10
            audit_flags.append("conservative_decision_with_positive_outcome")
            if simulation_confidence >= 0.8:
                score -= 0.05
                audit_flags.append("deferred_too_conservative")
        elif impact_label == "neutral":
            score += 0.10
        elif impact_label == "regressed":
            score += 0.20

    if simulation_confidence >= 0.8 and impact_label in {"neutral", "regressed"}:
        audit_flags.append("simulation_overconfidence")
    if simulation_confidence >= 0.8 and impact_label == "neutral":
        audit_flags.append("high_confidence_neutral_outcome")
        score -= 0.05

    score = _clamp(score, -1.0, 1.0)
    audit_status, decision_quality = _classify_audit(score=score)
    recommended_action = _recommended_action(
        audit_status=audit_status,
        audit_flags=audit_flags,
        applied=applied,
    )
    reasoning = _build_reasoning(
        audit_status=audit_status,
        applied=applied,
        impact_label=impact_label,
        score=score,
        audit_flags=audit_flags,
        decision_class=decision_class,
    )

    return {
        "audit_status": audit_status,
        "audit_score": score,
        "decision_quality": decision_quality,
        "reasoning": reasoning,
        "audit_flags": audit_flags,
        "recommended_action": recommended_action,
    }


def _classify_audit(*, score: float) -> tuple[str, str]:
    if score >= 0.4:
        return "confirmed", "good"
    if score < -0.2:
        return "failed", "poor"
    return "questionable", "mixed"


def _recommended_action(
    *,
    audit_status: str,
    audit_flags: list[str],
    applied: bool,
) -> str:
    if audit_status == "confirmed":
        return "none"
    if audit_status == "insufficient_data":
        return "monitor"
    if audit_status == "questionable":
        return "review" if applied else "monitor"
    if "high_risk_failure" in audit_flags:
        return "rollback_candidate"
    return "review"


def _build_reasoning(
    *,
    audit_status: str,
    applied: bool,
    impact_label: str,
    score: float,
    audit_flags: list[str],
    decision_class: str = "",
) -> str:
    action_mode = "aplicada" if applied else "no_aplicada"
    decision_fragment = f", decision_class={decision_class}" if decision_class else ""
    return (
        f"Decision {action_mode} auditada como {audit_status} "
        f"con outcome_real={impact_label}{decision_fragment}, audit_score={score}, "
        f"flags={','.join(audit_flags[:4]) if audit_flags else 'none'}"
    )


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else [], ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "[]"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return round(max(min_value, min(max_value, value)), 4)
