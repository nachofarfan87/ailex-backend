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
from app.services.learning_decision_audit_service import (
    audit_learning_decision,
    create_decision_audit_log,
)


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning_decision_audit.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _create_action(
    db: Session,
    *,
    applied: bool = True,
    confidence_score: float = 0.9,
    payload: dict | None = None,
) -> LearningActionLog:
    action = LearningActionLog(
        event_type="domain_override",
        recommendation_type="test",
        applied=applied,
        reason="test_reason",
        confidence_score=confidence_score,
        priority=0.8,
        evidence_json="{}",
        changes_applied_json=json.dumps(payload or {}),
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
    impact_label: str,
    impact_score: float = 0.0,
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


def _payload(
    *,
    decision_class: str = "apply",
    expected_outcome: str = "positive",
    simulation_confidence: float = 0.8,
    risk_level: str = "low",
    budget_override: dict | None = None,
) -> dict:
    return {
        "final_learning_decision": {
            "should_apply": decision_class == "apply",
            "decision_class": decision_class,
            "reasoning": "test",
        },
        "simulation_snapshot": {
            "expected_outcome": expected_outcome,
            "expected_impact_score": 0.5 if expected_outcome == "positive" else -0.5,
            "confidence_score": simulation_confidence,
        },
        "operational_risk": {
            "risk_level": risk_level,
            "risk_score": 0.8 if risk_level == "high" else 0.2,
        },
        "budget_override": budget_override,
    }


def test_apply_improved_is_confirmed(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload())
    _create_impact(db, action_log_id=action.id, impact_label="improved", impact_score=0.6)

    result = audit_learning_decision(db, action.id)

    assert result["audit_status"] == "confirmed"
    assert result["decision_quality"] == "good"
    assert "applied_then_improved" in result["audit_flags"]


def test_apply_regressed_is_failed(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload())
    _create_impact(db, action_log_id=action.id, impact_label="regressed", impact_score=-0.6)

    result = audit_learning_decision(db, action.id)

    assert result["audit_status"] == "failed"
    assert result["decision_quality"] == "poor"
    assert "applied_then_regressed" in result["audit_flags"]


def test_apply_neutral_is_questionable(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload(expected_outcome="positive"))
    _create_impact(db, action_log_id=action.id, impact_label="neutral", impact_score=0.0)

    result = audit_learning_decision(db, action.id)

    assert result["audit_status"] == "questionable"
    assert "neutral_outcome_after_apply" in result["audit_flags"]
    assert "simulation_overconfidence" in result["audit_flags"]


def test_no_impact_data_is_insufficient(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload())

    result = audit_learning_decision(db, action.id)

    assert result["audit_status"] == "insufficient_data"
    assert result["decision_quality"] == "unknown"
    assert "insufficient_impact_data" in result["audit_flags"]


def test_positive_simulation_then_regressed_sets_mismatch_flag(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload(expected_outcome="positive"))
    _create_impact(db, action_log_id=action.id, impact_label="regressed", impact_score=-0.5)

    result = audit_learning_decision(db, action.id)

    assert "positive_simulation_mismatch" in result["audit_flags"]
    assert "simulation_overconfidence" in result["audit_flags"]


def test_high_risk_apply_regressed_becomes_rollback_candidate(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload(risk_level="high"), confidence_score=0.95)
    _create_impact(db, action_log_id=action.id, impact_label="regressed", impact_score=-0.9)

    result = audit_learning_decision(db, action.id)

    assert "high_risk_failure" in result["audit_flags"]
    assert result["recommended_action"] == "rollback_candidate"


def test_budget_override_flag_is_recognized_without_overreaction(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(
        db,
        applied=False,
        payload=_payload(
            decision_class="apply",
            budget_override={
                "override_applied": True,
                "reason": "change_budget_max_changes_reached",
                "effective_decision_class": "skip",
                "original_final_learning_decision": {"decision_class": "apply"},
            },
        ),
    )

    result = audit_learning_decision(db, action.id)

    assert result["audit_status"] == "insufficient_data"
    assert "budget_override_present" in result["audit_flags"]


def test_incomplete_payload_is_defensive(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload={"simulation_snapshot": {"expected_outcome": "positive"}})
    _create_impact(db, action_log_id=action.id, impact_label="neutral", impact_score=0.0)

    result = audit_learning_decision(db, action.id)

    assert result["audit_status"] in {"questionable", "insufficient_data", "confirmed", "failed"}
    assert isinstance(result["audit_flags"], list)
    assert "decision_class=" not in result["reasoning"]


def test_reasoning_includes_decision_class_when_available(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload(decision_class="defer"))
    _create_impact(db, action_log_id=action.id, impact_label="neutral", impact_score=0.0)

    result = audit_learning_decision(db, action.id)

    assert "decision_class=defer" in result["reasoning"]


def test_non_applied_improved_with_high_simulation_confidence_penalizes_more(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(
        db,
        applied=False,
        payload=_payload(decision_class="skip", simulation_confidence=0.9),
    )
    _create_impact(db, action_log_id=action.id, impact_label="improved", impact_score=0.5)

    result = audit_learning_decision(db, action.id)

    assert result["audit_score"] == -0.15
    assert "conservative_decision_with_positive_outcome" in result["audit_flags"]
    assert "deferred_too_conservative" in result["audit_flags"]


def test_create_decision_audit_log_persists_result(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload())
    _create_impact(db, action_log_id=action.id, impact_label="improved", impact_score=0.5)

    result = create_decision_audit_log(db, action.id)
    stored = db.query(LearningDecisionAuditLog).filter_by(learning_action_log_id=action.id).first()

    assert stored is not None
    assert result["audit_status"] == "confirmed"
    assert stored.audit_status == "confirmed"
    assert stored.decision_quality == "good"


def test_audit_score_is_clamped(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, payload=_payload(risk_level="high"), confidence_score=1.0)
    _create_impact(db, action_log_id=action.id, impact_label="regressed", impact_score=-1.0)

    result = audit_learning_decision(db, action.id)

    assert result["audit_score"] >= -1.0
    assert result["audit_score"] <= 1.0
