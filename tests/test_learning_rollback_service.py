from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_action_log  # noqa: F401
import app.models.learning_decision_audit_log  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.models.learning_decision_audit_log import LearningDecisionAuditLog
from app.models.learning_impact_log import LearningImpactLog
from app.services import learning_runtime_config
from app.services.learning_rollback_service import (
    evaluate_rollback_candidate,
    execute_safe_rollback,
    get_rollback_candidate_for_action,
)
from app.services.learning_runtime_config_store import LearningRuntimeConfig, load_latest_runtime_config, save_runtime_config


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning_rollback.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _save_runtime_config(
    db: Session,
    *,
    prefer_hybrid_domains: list[str] | None = None,
    force_full_pipeline_domains: list[str] | None = None,
    thresholds: dict | None = None,
) -> dict:
    payload = {
        "prefer_hybrid_domains": prefer_hybrid_domains or [],
        "force_full_pipeline_domains": force_full_pipeline_domains or [],
        "thresholds": thresholds or {
            "low_confidence": 0.5,
            "low_decision_confidence": 0.5,
        },
    }
    save_runtime_config(db, payload)
    db.commit()
    return payload


def _create_action(
    db: Session,
    *,
    event_type: str = "domain_override",
    applied: bool = True,
    runtime_config: dict | None = None,
    operational_risk: dict | None = None,
    budget_override: dict | None = None,
) -> LearningActionLog:
    action = LearningActionLog(
        event_type=event_type,
        recommendation_type="test",
        applied=applied,
        reason="test_reason",
        confidence_score=0.95,
        priority=0.9,
        evidence_json="{}",
        changes_applied_json=json.dumps(
            {
                "runtime_config": runtime_config or {},
                "operational_risk": operational_risk or {"risk_level": "low", "risk_score": 0.2},
                "budget_override": budget_override,
            }
        ),
        impact_status="pending" if applied else None,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def _create_impact(
    db: Session,
    *,
    action_log_id: str,
    impact_label: str = "regressed",
    impact_score: float = -0.8,
) -> LearningImpactLog:
    impact = LearningImpactLog(
        learning_action_log_id=action_log_id,
        event_type="domain_override",
        status=impact_label,
        impact_label=impact_label,
        impact_score=impact_score,
        before_metrics_json="{}",
        after_metrics_json="{}",
        delta_metrics_json="{}",
        evaluation_window_hours=24,
    )
    db.add(impact)
    db.commit()
    db.refresh(impact)
    return impact


def _create_audit(
    db: Session,
    *,
    action_log_id: str,
    audit_status: str = "failed",
    recommended_action: str = "rollback_candidate",
    audit_flags: list[str] | None = None,
) -> LearningDecisionAuditLog:
    audit = LearningDecisionAuditLog(
        learning_action_log_id=action_log_id,
        event_type="domain_override",
        audit_status=audit_status,
        audit_score=-0.8 if audit_status == "failed" else 0.0,
        decision_quality="poor" if audit_status == "failed" else "mixed",
        recommended_action=recommended_action,
        reasoning="test",
        audit_flags_json=json.dumps(audit_flags or ["applied_then_regressed"]),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def test_applied_failed_regressed_reversible_is_candidate(tmp_path):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()
    runtime_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(db, runtime_config=runtime_config)
    impact = _create_impact(db, action_log_id=action.id)
    audit = _create_audit(db, action_log_id=action.id, audit_flags=["applied_then_regressed"])

    result = evaluate_rollback_candidate(db=db, action_log=action, impact_log=impact, audit_log=audit)

    assert result["is_candidate"] is True
    assert result["candidate_state"] == "candidate"
    assert result["reversible"] is True
    assert result["recommended_action"] in {"manual_review", "safe_rollback"}
    assert f"recommended_action={result['recommended_action']}" in result["reasoning"]


def test_not_applied_action_is_not_candidate(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, applied=False)

    result = get_rollback_candidate_for_action(db, action.id)

    assert result["is_candidate"] is False
    assert result["candidate_state"] == "not_candidate"
    assert result["recommended_action"] == "none"


def test_insufficient_data_is_not_candidate(tmp_path):
    db = _build_session(tmp_path)
    runtime_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(db, runtime_config=runtime_config)

    result = get_rollback_candidate_for_action(db, action.id)

    assert result["is_candidate"] is False
    assert "insufficient_rollback_evidence" in result["candidate_flags"]


def test_high_risk_failure_pushes_rollback_score(tmp_path):
    db = _build_session(tmp_path)
    runtime_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(
        db,
        runtime_config=runtime_config,
        operational_risk={"risk_level": "high", "risk_score": 0.8},
    )
    impact = _create_impact(db, action_log_id=action.id, impact_score=-0.9)
    audit = _create_audit(
        db,
        action_log_id=action.id,
        audit_flags=["applied_then_regressed", "high_risk_failure", "high_confidence_miss"],
    )

    result = evaluate_rollback_candidate(db=db, action_log=action, impact_log=impact, audit_log=audit)

    assert result["rollback_score"] >= 0.75
    assert "high_risk_failure" in result["candidate_flags"]
    assert result["recommended_action"] == "safe_rollback"


def test_budget_override_does_not_generate_candidate(tmp_path):
    db = _build_session(tmp_path)
    runtime_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(
        db,
        runtime_config=runtime_config,
        budget_override={"override_applied": True, "effective_decision_class": "skip"},
    )
    _create_impact(db, action_log_id=action.id)
    _create_audit(db, action_log_id=action.id)

    result = get_rollback_candidate_for_action(db, action.id)

    assert result["is_candidate"] is False
    assert "budget_override_present" in result["candidate_flags"]


def test_manual_only_event_is_not_candidate(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, event_type="classification_review", runtime_config={"thresholds": {}})
    impact = _create_impact(db, action_log_id=action.id)
    audit = _create_audit(db, action_log_id=action.id)

    result = evaluate_rollback_candidate(db=db, action_log=action, impact_log=impact, audit_log=audit)

    assert result["is_candidate"] is False
    assert result["candidate_state"] == "not_candidate"
    assert result["reversible"] is False


def test_rollback_score_is_clamped(tmp_path):
    db = _build_session(tmp_path)
    runtime_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(
        db,
        runtime_config=runtime_config,
        operational_risk={"risk_level": "high", "risk_score": 1.0},
    )
    impact = _create_impact(db, action_log_id=action.id, impact_score=-1.0)
    audit = _create_audit(
        db,
        action_log_id=action.id,
        audit_flags=[
            "applied_then_regressed",
            "high_risk_failure",
            "positive_simulation_mismatch",
            "high_confidence_miss",
        ],
    )

    result = evaluate_rollback_candidate(db=db, action_log=action, impact_log=impact, audit_log=audit)

    assert result["rollback_score"] <= 1.0


def test_safe_rollback_executes_and_creates_learning_action_log(tmp_path):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()
    initial_config = _save_runtime_config(db)
    applied_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(
        db,
        runtime_config=applied_config,
        operational_risk={"risk_level": "high", "risk_score": 0.9},
    )
    _create_impact(db, action_log_id=action.id, impact_score=-0.9)
    _create_audit(
        db,
        action_log_id=action.id,
        audit_flags=["applied_then_regressed", "high_risk_failure", "high_confidence_miss"],
    )

    result = execute_safe_rollback(db, action.id)

    rollback_log = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.recommendation_type == "rollback_intelligent")
        .first()
    )
    assert result["status"] == "rolled_back"
    assert rollback_log is not None
    latest_runtime = load_latest_runtime_config(db)
    assert latest_runtime["prefer_hybrid_domains"] == initial_config["prefer_hybrid_domains"]
    assert latest_runtime["force_full_pipeline_domains"] == initial_config["force_full_pipeline_domains"]
    assert latest_runtime["thresholds"] == initial_config["thresholds"]


def test_safe_rollback_rejects_unsafe_candidate(tmp_path):
    db = _build_session(tmp_path)
    runtime_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(db, runtime_config=runtime_config)
    _create_impact(db, action_log_id=action.id, impact_score=-0.3)
    _create_audit(
        db,
        action_log_id=action.id,
        audit_status="questionable",
        recommended_action="review",
        audit_flags=["neutral_outcome_after_apply"],
    )

    result = execute_safe_rollback(db, action.id)

    assert result["status"] == "rejected"
    assert result["reason"] in {"not_a_rollback_candidate", "rollback_requires_manual_review"}


def test_rollback_does_not_duplicate_on_already_reverted_action(tmp_path):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()
    _save_runtime_config(db)
    applied_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(
        db,
        runtime_config=applied_config,
        operational_risk={"risk_level": "high", "risk_score": 0.9},
    )
    _create_impact(db, action_log_id=action.id, impact_score=-0.9)
    _create_audit(
        db,
        action_log_id=action.id,
        audit_flags=["applied_then_regressed", "high_risk_failure", "high_confidence_miss"],
    )

    first = execute_safe_rollback(db, action.id)
    second = execute_safe_rollback(db, action.id)

    assert first["status"] == "rolled_back"
    assert second["status"] == "rejected"
    assert second["reason"] == "not_a_rollback_candidate"


def test_persists_rollback_reason_score_and_candidate_flags(tmp_path):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()
    _save_runtime_config(db)
    applied_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(
        db,
        runtime_config=applied_config,
        operational_risk={"risk_level": "high", "risk_score": 0.9},
    )
    _create_impact(db, action_log_id=action.id, impact_score=-0.9)
    _create_audit(
        db,
        action_log_id=action.id,
        audit_flags=["applied_then_regressed", "high_risk_failure", "high_confidence_miss"],
    )

    execute_safe_rollback(db, action.id)

    rollback_log = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.recommendation_type == "rollback_intelligent")
        .first()
    )
    payload = json.loads(rollback_log.evidence_json)
    assert payload["rolled_back_action_log_id"] == action.id
    assert isinstance(payload["rollback_reason"], str)
    assert payload["rollback_score"] >= 0.75
    assert "high_risk_failure" in payload["candidate_flags"]


def test_defensive_behavior_with_incomplete_payload(tmp_path):
    db = _build_session(tmp_path)
    action = LearningActionLog(
        event_type="domain_override",
        recommendation_type="test",
        applied=True,
        reason="test_reason",
        confidence_score=0.8,
        priority=0.8,
        evidence_json="{}",
        changes_applied_json=json.dumps({"operational_risk": {"risk_level": "low"}}),
        impact_status="pending",
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    impact = _create_impact(db, action_log_id=action.id, impact_score=-0.5)
    audit = _create_audit(db, action_log_id=action.id)

    result = evaluate_rollback_candidate(db=db, action_log=action, impact_log=impact, audit_log=audit)

    assert result["is_candidate"] is False
    assert result["candidate_state"] == "blocked_candidate"
    assert result["reversible"] is False


def test_execute_safe_rollback_rejects_when_action_is_not_latest_runtime_change(tmp_path):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()
    _save_runtime_config(db)
    old_applied_config = _save_runtime_config(db, prefer_hybrid_domains=["alimentos"])
    action = _create_action(
        db,
        runtime_config=old_applied_config,
        operational_risk={"risk_level": "high", "risk_score": 0.9},
    )
    _save_runtime_config(db, prefer_hybrid_domains=["familia"])
    _create_impact(db, action_log_id=action.id, impact_score=-0.9)
    _create_audit(
        db,
        action_log_id=action.id,
        audit_flags=["applied_then_regressed", "high_risk_failure", "high_confidence_miss"],
    )

    result = execute_safe_rollback(db, action.id)

    assert result["status"] == "rejected"
    assert result["reason"] == "action_is_not_latest_runtime_change"
    assert "not_latest_runtime_change" in result["candidate_flags"]


def test_non_reversible_with_relevant_score_becomes_blocked_candidate(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, event_type="classification_review", runtime_config={"thresholds": {}})
    impact = _create_impact(db, action_log_id=action.id, impact_score=-0.9)
    audit = _create_audit(
        db,
        action_log_id=action.id,
        audit_flags=["applied_then_regressed", "high_risk_failure"],
    )

    result = evaluate_rollback_candidate(db=db, action_log=action, impact_log=impact, audit_log=audit)

    assert result["is_candidate"] is False
    assert result["candidate_state"] == "not_candidate"


def test_non_reversible_reversible_event_with_missing_snapshot_is_blocked_candidate(tmp_path):
    db = _build_session(tmp_path)
    action = LearningActionLog(
        event_type="domain_override",
        recommendation_type="test",
        applied=True,
        reason="test_reason",
        confidence_score=0.95,
        priority=0.9,
        evidence_json="{}",
        changes_applied_json=json.dumps({"operational_risk": {"risk_level": "high", "risk_score": 0.8}}),
        impact_status="pending",
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    impact = _create_impact(db, action_log_id=action.id, impact_score=-0.9)
    audit = _create_audit(
        db,
        action_log_id=action.id,
        audit_flags=["applied_then_regressed", "high_risk_failure"],
    )

    result = evaluate_rollback_candidate(db=db, action_log=action, impact_log=impact, audit_log=audit)

    assert result["is_candidate"] is False
    assert result["candidate_state"] == "blocked_candidate"
    assert result["reversible"] is False
