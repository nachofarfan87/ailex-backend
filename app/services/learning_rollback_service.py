from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.models.learning_decision_audit_log import LearningDecisionAuditLog
from app.models.learning_impact_log import LearningImpactLog
from app.services import learning_runtime_config
from app.services.learning_runtime_config_store import LearningRuntimeConfig, _extract_runtime_config, save_runtime_config
from app.services.utc import utc_now


REVERSIBLE_EVENT_TYPES = {"domain_override", "threshold_adjustment"}
MANUAL_ONLY_EVENT_TYPES = {"classification_review", "strategy_recalibration", "version_alert"}
ROLLBACK_PUSH_FLAGS = {
    "high_risk_failure": 0.15,
    "applied_then_regressed": 0.10,
    "positive_simulation_mismatch": 0.05,
    "high_confidence_miss": 0.05,
}


def get_rollback_candidate_for_action(
    db: Session,
    learning_action_log_id: str,
) -> dict[str, Any] | None:
    action_log = db.get(LearningActionLog, learning_action_log_id)
    if action_log is None:
        return None

    impact_log = _get_latest_impact_for_action(db, action_log.id)
    audit_log = _get_latest_audit_for_action(db, action_log.id)
    return evaluate_rollback_candidate(
        db=db,
        action_log=action_log,
        impact_log=impact_log,
        audit_log=audit_log,
    )


def evaluate_rollback_candidate(
    *,
    db: Session,
    action_log: LearningActionLog,
    impact_log: LearningImpactLog | None,
    audit_log: LearningDecisionAuditLog | None,
) -> dict[str, Any]:
    payload = _safe_json_loads(action_log.changes_applied_json, {})
    audit_flags = _safe_json_loads(audit_log.audit_flags_json if audit_log else None, [])
    operational_risk = dict(payload.get("operational_risk") or {})
    budget_override = dict(payload.get("budget_override") or {})
    event_type = str(action_log.event_type or "").strip().lower()
    impact_label = str((impact_log.impact_label if impact_log else "") or (impact_log.status if impact_log else "") or "").strip().lower()
    impact_score = _safe_float(impact_log.impact_score if impact_log else 0.0)
    audit_status = str(audit_log.audit_status or "").strip().lower() if audit_log else ""
    audit_recommended_action = str(audit_log.recommended_action or "").strip().lower() if audit_log else ""
    risk_level = str(operational_risk.get("risk_level") or "medium").strip().lower()
    reversible = _is_action_reversible(action_log=action_log, payload=payload)
    candidate_flags: list[str] = []

    if not bool(action_log.applied):
        return _candidate_result(
            is_candidate=False,
            candidate_state="not_candidate",
            rollback_score=0.0,
            severity="low",
            reasoning="La accion no fue aplicada; no corresponde rollback.",
            candidate_flags=["not_applied"],
            reversible=False,
            recommended_action="none",
        )

    if budget_override:
        return _candidate_result(
            is_candidate=False,
            candidate_state="not_candidate",
            rollback_score=0.0,
            severity="low",
            reasoning="La accion tiene budget override; no hubo aplicacion real segura para revertir.",
            candidate_flags=["budget_override_present"],
            reversible=False,
            recommended_action="none",
        )

    if _has_existing_rollback(db, action_log.id):
        return _candidate_result(
            is_candidate=False,
            candidate_state="not_candidate",
            rollback_score=0.0,
            severity="low",
            reasoning="La accion ya fue revertida previamente.",
            candidate_flags=["already_reverted"],
            reversible=False,
            recommended_action="none",
        )

    if event_type in MANUAL_ONLY_EVENT_TYPES or event_type == "rollback":
        return _candidate_result(
            is_candidate=False,
            candidate_state="not_candidate",
            rollback_score=0.0,
            severity="low",
            reasoning="El tipo de evento es manual o no reversible por politica prudente.",
            candidate_flags=["manual_only_or_non_reversible_event"],
            reversible=False,
            recommended_action="none",
        )

    if impact_log is None or audit_log is None or audit_status in {"", "insufficient_data"}:
        return _candidate_result(
            is_candidate=False,
            candidate_state="not_candidate",
            rollback_score=0.0,
            severity="low",
            reasoning="No hay evidencia suficiente de impacto/auditoria para evaluar rollback.",
            candidate_flags=["insufficient_rollback_evidence"],
            reversible=reversible,
            recommended_action="none",
        )

    score = 0.0

    if audit_status == "failed":
        score += 0.45
        candidate_flags.append("failed_audit")
    elif audit_status == "questionable":
        score += 0.10
        candidate_flags.append("questionable_audit")

    if audit_recommended_action == "rollback_candidate":
        score += 0.20
        candidate_flags.append("audit_marked_rollback_candidate")

    if impact_label == "regressed":
        score += 0.15
        candidate_flags.append("regressed_impact")

    if risk_level == "high":
        score += 0.05
        candidate_flags.append("high_operational_risk")

    for flag, boost in ROLLBACK_PUSH_FLAGS.items():
        if flag in audit_flags:
            score += boost
            candidate_flags.append(flag)

    if impact_score <= -0.80:
        score += 0.15
        candidate_flags.append("severe_negative_impact")
    elif impact_score <= -0.50:
        score += 0.10
        candidate_flags.append("material_negative_impact")

    if not reversible:
        score -= 0.35
        candidate_flags.append("non_reversible_change")

    score = _clamp(score, 0.0, 1.0)
    severity = _resolve_severity(score)

    if not reversible or score < 0.45:
        candidate_state = "blocked_candidate" if score >= 0.45 or ("failed_audit" in candidate_flags) else "not_candidate"
        return _candidate_result(
            is_candidate=False,
            candidate_state=candidate_state,
            rollback_score=score,
            severity=severity,
            reasoning=_build_reasoning(
                action_log=action_log,
                audit_status=audit_status,
                impact_label=impact_label,
                score=score,
                reversible=reversible,
                candidate_flags=candidate_flags,
                recommended_action="none",
            ),
            candidate_flags=candidate_flags,
            reversible=reversible,
            recommended_action="none",
        )

    recommended_action = "safe_rollback" if score >= 0.75 else "manual_review"
    return _candidate_result(
        is_candidate=True,
        candidate_state="candidate",
        rollback_score=score,
        severity=severity,
        reasoning=_build_reasoning(
            action_log=action_log,
            audit_status=audit_status,
            impact_label=impact_label,
            score=score,
            reversible=reversible,
            candidate_flags=candidate_flags,
            recommended_action=recommended_action,
        ),
        candidate_flags=candidate_flags,
        reversible=reversible,
        recommended_action=recommended_action,
    )


def execute_safe_rollback(
    db: Session,
    learning_action_log_id: str,
) -> dict[str, Any]:
    action_log = db.get(LearningActionLog, learning_action_log_id)
    if action_log is None:
        raise ValueError("learning_action_log_not_found")

    candidate = get_rollback_candidate_for_action(db, learning_action_log_id)
    if not candidate or not candidate.get("is_candidate"):
        return {
            "status": "rejected",
            "reason": "not_a_rollback_candidate",
            "candidate": candidate,
        }

    if candidate.get("recommended_action") != "safe_rollback":
        return {
            "status": "rejected",
            "reason": "rollback_requires_manual_review",
            "candidate": candidate,
        }

    if not bool(candidate.get("reversible")):
        return {
            "status": "rejected",
            "reason": "non_reversible_change",
            "candidate": candidate,
        }

    if _has_existing_rollback(db, action_log.id):
        return {
            "status": "rejected",
            "reason": "already_reverted",
            "candidate": candidate,
        }

    runtime_logs = (
        db.query(LearningRuntimeConfig)
        .order_by(LearningRuntimeConfig.created_at.desc())
        .limit(2)
        .all()
    )
    if len(runtime_logs) < 2:
        return {
            "status": "rejected",
            "reason": "insufficient_runtime_history",
            "candidate": candidate,
        }

    latest_runtime_config = _extract_runtime_config(_safe_json_loads(runtime_logs[0].config_json, {})) or {}
    previous_runtime_config = _extract_runtime_config(_safe_json_loads(runtime_logs[1].config_json, {})) or {}
    action_runtime_config = _extract_action_runtime_config(action_log)

    if not action_runtime_config:
        return {
            "status": "rejected",
            "reason": "missing_action_runtime_snapshot",
            "candidate": candidate,
        }

    if dict(action_runtime_config) != dict(latest_runtime_config):
        return {
            "status": "rejected",
            "reason": "action_is_not_latest_runtime_change",
            "candidate_flags": list(dict.fromkeys([*(candidate.get("candidate_flags") or []), "not_latest_runtime_change"])),
            "candidate": candidate,
        }

    learning_runtime_config.apply_persisted_runtime_config(previous_runtime_config)
    runtime_config = learning_runtime_config.get_effective_runtime_config()
    save_runtime_config(db, runtime_config)
    db.add(
        LearningActionLog(
            event_type="rollback",
            recommendation_type="rollback_intelligent",
            applied=True,
            reason="safe_rollback_executed",
            confidence_score=None,
            priority=None,
            impact_status="pending",
            applied_at=utc_now(),
            evidence_json=json.dumps(
                {
                    "rolled_back_action_log_id": action_log.id,
                    "rollback_reason": candidate["reasoning"],
                    "rollback_score": candidate["rollback_score"],
                    "candidate_flags": candidate["candidate_flags"],
                    "restored_snapshot_id": runtime_logs[1].id,
                }
            ),
            changes_applied_json=json.dumps(
                {
                    "runtime_config": runtime_config,
                    "rollback_source": {
                        "rolled_back_action_log_id": action_log.id,
                        "event_type": action_log.event_type,
                    },
                }
            ),
        )
    )
    db.commit()
    return {
        "status": "rolled_back",
        "rolled_back_action_log_id": action_log.id,
        "rollback_score": candidate["rollback_score"],
        "candidate_flags": candidate["candidate_flags"],
        "runtime_config": runtime_config,
    }


def _get_latest_impact_for_action(db: Session, learning_action_log_id: str) -> LearningImpactLog | None:
    return (
        db.query(LearningImpactLog)
        .filter(LearningImpactLog.learning_action_log_id == str(learning_action_log_id))
        .order_by(LearningImpactLog.created_at.desc())
        .first()
    )


def _get_latest_audit_for_action(db: Session, learning_action_log_id: str) -> LearningDecisionAuditLog | None:
    return (
        db.query(LearningDecisionAuditLog)
        .filter(LearningDecisionAuditLog.learning_action_log_id == str(learning_action_log_id))
        .order_by(LearningDecisionAuditLog.created_at.desc())
        .first()
    )


def _is_action_reversible(
    *,
    action_log: LearningActionLog,
    payload: dict[str, Any],
) -> bool:
    event_type = str(action_log.event_type or "").strip().lower()
    if event_type not in REVERSIBLE_EVENT_TYPES:
        return False
    if not bool(action_log.applied):
        return False
    return bool(_extract_action_runtime_config(action_log, payload=payload))


def _extract_action_runtime_config(
    action_log: LearningActionLog,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    payload = payload if payload is not None else _safe_json_loads(action_log.changes_applied_json, {})
    runtime_config = payload.get("runtime_config")
    if isinstance(runtime_config, dict):
        return dict(runtime_config)
    details = dict(payload.get("details") or {})
    nested_runtime_config = details.get("runtime_config")
    if isinstance(nested_runtime_config, dict):
        return dict(nested_runtime_config)
    return None


def _has_existing_rollback(db: Session, learning_action_log_id: str) -> bool:
    rollback_logs = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == "rollback")
        .all()
    )
    target_id = str(learning_action_log_id)
    for rollback_log in rollback_logs:
        evidence = _safe_json_loads(rollback_log.evidence_json, {})
        if str(evidence.get("rolled_back_action_log_id") or "") == target_id:
            return True
    return False


def _candidate_result(
    *,
    is_candidate: bool,
    candidate_state: str,
    rollback_score: float,
    severity: str,
    reasoning: str,
    candidate_flags: list[str],
    reversible: bool,
    recommended_action: str,
) -> dict[str, Any]:
    return {
        "is_candidate": bool(is_candidate),
        "candidate_state": candidate_state,
        "rollback_score": _clamp(rollback_score, 0.0, 1.0),
        "severity": severity,
        "reasoning": reasoning,
        "candidate_flags": list(dict.fromkeys(candidate_flags)),
        "reversible": bool(reversible),
        "recommended_action": recommended_action,
    }


def _resolve_severity(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _build_reasoning(
    *,
    action_log: LearningActionLog,
    audit_status: str,
    impact_label: str,
    score: float,
    reversible: bool,
    candidate_flags: list[str],
    recommended_action: str = "",
) -> str:
    action_fragment = f", recommended_action={recommended_action}" if recommended_action else ""
    return (
        f"Rollback evaluado para event_type={action_log.event_type} "
        f"con audit_status={audit_status or 'unknown'}, impact_label={impact_label or 'unknown'}, "
        f"reversible={str(bool(reversible)).lower()}{action_fragment}, rollback_score={score}, "
        f"flags={','.join(candidate_flags[:5]) if candidate_flags else 'none'}"
    )


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return round(max(min_value, min(max_value, value)), 4)
