from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_decision_audit_log  # noqa: F401
from app.models.learning_decision_audit_log import LearningDecisionAuditLog
from app.services.learning_governance_service import get_learning_governance_summary


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning_governance.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _create_audit_log(
    db: Session,
    *,
    audit_status: str,
    recommended_action: str = "none",
    audit_flags: list[str] | None = None,
) -> LearningDecisionAuditLog:
    audit_log = LearningDecisionAuditLog(
        learning_action_log_id=f"action-{audit_status}-{recommended_action}-{len(audit_flags or [])}",
        event_type="domain_override",
        audit_status=audit_status,
        audit_score=0.5 if audit_status == "confirmed" else (-0.5 if audit_status == "failed" else 0.0),
        decision_quality="good" if audit_status == "confirmed" else ("poor" if audit_status == "failed" else "mixed"),
        recommended_action=recommended_action,
        reasoning="test",
        audit_flags_json=json.dumps(audit_flags or []),
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log


def test_governance_summary_healthy(tmp_path):
    db = _build_session(tmp_path)
    for _ in range(8):
        _create_audit_log(db, audit_status="confirmed", recommended_action="none", audit_flags=["applied_then_improved"])
    _create_audit_log(db, audit_status="questionable", recommended_action="monitor", audit_flags=["neutral_outcome_after_apply"])

    result = get_learning_governance_summary(db)

    assert result["audited_count"] == 9
    assert result["confirmed_count"] == 8
    assert result["questionable_count"] == 1
    assert result["failed_count"] == 0
    assert result["status"] == "healthy"


def test_governance_summary_watch(tmp_path):
    db = _build_session(tmp_path)
    for _ in range(6):
        _create_audit_log(db, audit_status="confirmed", recommended_action="none", audit_flags=["applied_then_improved"])
    for _ in range(3):
        _create_audit_log(db, audit_status="questionable", recommended_action="review", audit_flags=["simulation_overconfidence"])
    _create_audit_log(db, audit_status="failed", recommended_action="review", audit_flags=["applied_then_regressed"])

    result = get_learning_governance_summary(db)

    assert result["failed_count"] == 1
    assert result["review_candidates"] == 4
    assert result["status"] == "watch"


def test_governance_summary_degraded(tmp_path):
    db = _build_session(tmp_path)
    for _ in range(4):
        _create_audit_log(db, audit_status="confirmed", recommended_action="none", audit_flags=["applied_then_improved"])
    for _ in range(4):
        _create_audit_log(
            db,
            audit_status="failed",
            recommended_action="rollback_candidate",
            audit_flags=["applied_then_regressed", "high_risk_failure"],
        )

    result = get_learning_governance_summary(db)

    assert result["failed_count"] == 4
    assert result["rollback_candidates"] == 4
    assert result["status"] == "degraded"


def test_governance_counts_rollback_candidates_correctly(tmp_path):
    db = _build_session(tmp_path)
    _create_audit_log(db, audit_status="failed", recommended_action="rollback_candidate", audit_flags=["high_risk_failure"])
    _create_audit_log(db, audit_status="failed", recommended_action="rollback_candidate", audit_flags=["high_risk_failure"])
    _create_audit_log(db, audit_status="questionable", recommended_action="review", audit_flags=["simulation_overconfidence"])

    result = get_learning_governance_summary(db)

    assert result["rollback_candidates"] == 2
    assert result["review_candidates"] == 1


def test_governance_top_flags_are_sorted_by_frequency(tmp_path):
    db = _build_session(tmp_path)
    for _ in range(4):
        _create_audit_log(db, audit_status="failed", recommended_action="review", audit_flags=["applied_then_regressed"])
    for _ in range(2):
        _create_audit_log(db, audit_status="questionable", recommended_action="review", audit_flags=["simulation_overconfidence"])
    _create_audit_log(db, audit_status="confirmed", recommended_action="none", audit_flags=["applied_then_improved"])

    result = get_learning_governance_summary(db)

    assert result["top_flags"][0] == {"flag": "applied_then_regressed", "count": 4}
    assert result["top_flags"][1] == {"flag": "simulation_overconfidence", "count": 2}


def test_governance_summary_without_data_is_healthy_and_empty(tmp_path):
    db = _build_session(tmp_path)

    result = get_learning_governance_summary(db)

    assert result == {
        "audited_count": 0,
        "confirmed_count": 0,
        "questionable_count": 0,
        "failed_count": 0,
        "rollback_candidates": 0,
        "review_candidates": 0,
        "status": "healthy",
        "top_flags": [],
    }
