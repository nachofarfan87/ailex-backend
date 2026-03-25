from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.user_models import User
import app.models.learning_action_log  # noqa: F401
import app.models.learning_human_audit  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_decision_audit_log  # noqa: F401
import app.models.learning_review  # noqa: F401
from app.models.learning_human_audit import LearningHumanAuditLog
from app.models.learning_review import LearningReview
from app.services import learning_runtime_config, self_tuning_service
from app.services.learning_runtime_config_store import save_runtime_config
from app.services.self_tuning_human_control import get_human_control_snapshot
from app.services.self_tuning_override_service import create_override, set_system_mode
from app.services.self_tuning_review_service import (
    approve_review,
    create_review_entry,
    get_review_queue,
    override_review,
    reject_review,
)
from app.services.utc import utc_now


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'self_tuning_human_control.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _seed_runtime_config(db: Session) -> None:
    learning_runtime_config.reset_runtime_config()
    save_runtime_config(db, learning_runtime_config.get_effective_runtime_config())
    db.commit()


def _create_user(db: Session) -> User:
    user = User(
        email="ops@ailex.local",
        nombre="Ops",
        hashed_password="not_used_in_tests",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _mock_signals(monkeypatch, **overrides):
    payload = {
        "sample_size": 64,
        "impact_total": 64,
        "total_observations": 64,
        "audited_count": 64,
        "improvement_rate": 0.76,
        "regression_rate": 0.04,
        "neutral_rate": 0.2,
        "failed_ratio": 0.05,
        "questionable_ratio": 0.1,
        "rollback_ratio": 0.0,
        "rollback_candidates": 0,
        "recent_avg_score": 0.38,
        "previous_avg_score": 0.32,
        "historical_avg_score": 0.24,
        "recent_vs_historical_delta": 0.14,
        "trend_stability": 0.82,
        "consistency": 0.86,
        "drift_level": "none",
        "governance_status": "healthy",
        "top_flag_counts": {},
        "overview": {},
        "impact_summary": {},
        "governance_summary": {},
        "drift": {},
    }
    payload.update(overrides)
    monkeypatch.setattr(self_tuning_service, "collect_self_tuning_signals", lambda db, limit=100: payload)


def _review_recommendation(
    *,
    final_action: str = "apply",
    meta_confidence: float = 0.52,
    risk_flags: list[str] | None = None,
    strategy_conflict_resolved: bool = False,
    strategy_override_applied: bool = False,
    strategy_profile: str = "micro_adjustment",
    delta: float = -0.02,
) -> dict:
    return {
        "summary": "Self-tuning review test",
        "risk_flags": list(risk_flags or []),
        "candidate_adjustments": [
            {
                "parameter_name": "apply_confidence_delta",
                "current_value": 0.0,
                "proposed_value": delta,
                "delta": delta,
                "strategy_effective_delta": delta,
                "confidence": 0.82,
                "priority_score": 0.8,
                "blocked": False,
                "blocked_reasons": [],
                "explanation": {"why_not": []},
            }
        ],
        "meta_decision": {
            "meta_confidence": meta_confidence,
            "recommended_action": final_action,
        },
        "strategy_decision": {
            "strategy_profile": strategy_profile,
            "final_strategy_profile": strategy_profile,
            "strategy_conflict_resolved": strategy_conflict_resolved,
            "strategy_override_applied": strategy_override_applied,
        },
    }


def test_review_queue_is_generated_in_manual_only_mode(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["status"] == "review_pending"
    assert result["human_control"]["system_mode"] == "manual_only"
    assert result["human_control"]["review_entry_id"] is not None
    assert db.query(LearningReview).filter(LearningReview.review_status == "pending").count() == 1
    review = db.query(LearningReview).filter(LearningReview.review_status == "pending").first()
    assert review.review_priority in {"high", "medium", "low"}
    assert review.review_priority_reason


def test_review_queue_orders_more_sensitive_reviews_first(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    create_review_entry(
        db,
        recommendation=_review_recommendation(
            final_action="simulate",
            meta_confidence=0.88,
            delta=-0.01,
        ),
        final_action="simulate",
        review_status="pending",
        requires_review=True,
    )
    create_review_entry(
        db,
        recommendation=_review_recommendation(
            final_action="apply",
            meta_confidence=0.32,
            risk_flags=["rollback_pressure"],
            strategy_conflict_resolved=True,
            strategy_profile="restricted_adjustment",
            delta=-0.08,
        ),
        final_action="apply",
        review_status="pending",
        requires_review=True,
    )

    queue = get_review_queue(db)

    assert queue[0]["review_priority"] == "high"
    assert queue[0]["final_action"] == "apply"
    assert "low_meta_confidence" in queue[0]["review_priority_reason"]


def test_approve_review_applies_change(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)
    self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    review = db.query(LearningReview).filter(LearningReview.review_status == "pending").first()

    outcome = approve_review(db, review_id=review.id, actor=actor, notes="approved for rollout")

    assert outcome["review"]["review_status"] == "approved"
    assert outcome["outcome"]["status"] == "applied"


def test_reject_review_blocks_execution(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)
    self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    review = db.query(LearningReview).filter(LearningReview.review_status == "pending").first()

    outcome = reject_review(db, review_id=review.id, actor=actor, notes="reject")

    assert outcome["review"]["review_status"] == "rejected"
    assert outcome["outcome"]["status"] == "rejected"


def test_override_review_can_change_action_to_simulate(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)
    self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    review = db.query(LearningReview).filter(LearningReview.review_status == "pending").first()

    outcome = override_review(
        db,
        review_id=review.id,
        actor=actor,
        forced_action="simulate",
        notes="simulate first",
    )

    assert outcome["review"]["review_status"] == "approved"
    assert outcome["outcome"]["status"] == "simulated"


def test_system_mode_frozen_blocks_everything(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="frozen", actor=actor)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["status"] == "blocked"
    assert result["human_control"]["system_mode"] == "frozen"


def test_active_override_can_force_simulation(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    create_override(
        db,
        override_type="force_action",
        forced_action="simulate",
        duration_cycles=2,
        reason="safe rollout",
        actor=actor,
    )

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    snapshot = get_human_control_snapshot(db)

    assert result["status"] == "simulated"
    assert result["human_control"]["applied_overrides"]
    assert snapshot["active_override_summary"]["override_count_by_type"]["force_action"] >= 1


def test_manual_override_cannot_break_hard_safety(tmp_path, monkeypatch):
    import pytest

    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)
    self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    review = db.query(LearningReview).filter(LearningReview.review_status == "pending").first()

    with pytest.raises(ValueError, match="unsafe_override_delta"):
        override_review(
            db,
            review_id=review.id,
            actor=actor,
            forced_action="apply",
            forced_delta=0.5,
            notes="unsafe delta",
        )


def test_audit_log_registers_human_actions(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)
    self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    review = db.query(LearningReview).filter(LearningReview.review_status == "pending").first()
    approve_review(db, review_id=review.id, actor=actor, notes="approved")

    assert db.query(LearningHumanAuditLog).count() >= 2


def test_human_control_snapshot_exposes_required_fields(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)
    self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    snapshot = get_human_control_snapshot(db)

    assert "review_queue_size" in snapshot
    assert "pending_reviews" in snapshot
    assert "overrides_active" in snapshot
    assert "active_override_summary" in snapshot
    assert "pending_reviews_by_priority" in snapshot
    assert "stale_reviews_count" in snapshot
    assert "recent_human_actions_summary" in snapshot
    assert "system_mode" in snapshot
    assert "human_interventions_last_24h" in snapshot


def test_review_item_exposes_age_and_stale_fields(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    review = create_review_entry(
        db,
        recommendation=_review_recommendation(final_action="apply", meta_confidence=0.41),
        final_action="apply",
        review_status="pending",
        requires_review=True,
    )
    review.created_at = utc_now() - timedelta(hours=30)
    review.updated_at = review.created_at
    db.commit()
    db.refresh(review)

    queue = get_review_queue(db)

    assert queue[0]["age_hours"] >= 30
    assert queue[0]["is_stale"] is True
    assert queue[0]["stale_bucket"] == "stale"
    assert queue[0]["stale_reason"]


def test_control_snapshot_summarizes_active_overrides_and_pending_priorities(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)
    create_override(
        db,
        override_type="freeze_parameter",
        parameter_name="apply_confidence_delta",
        duration_cycles=2,
        reason="freeze while reviewing",
        actor=actor,
    )
    create_override(
        db,
        override_type="force_action",
        forced_action="simulate",
        duration_cycles=3,
        reason="safe rollout",
        actor=actor,
    )
    self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    snapshot = get_human_control_snapshot(db)

    assert snapshot["pending_reviews_by_priority"]["high"] >= 0
    assert snapshot["active_override_summary"]["override_count_by_type"]["freeze_parameter"] == 1
    assert snapshot["active_override_summary"]["override_count_by_type"]["force_action"] == 1
    assert "apply_confidence_delta" in snapshot["active_override_summary"]["overridden_parameters"]
    assert "simulate" in snapshot["active_override_summary"]["forced_actions_active"]
    assert snapshot["active_override_summary"]["expiring_overrides"]
    assert snapshot["active_override_summary"]["remaining_cycles_total"] >= 3


def test_recent_human_actions_summary_and_rates_are_exposed(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    actor = _create_user(db)
    _mock_signals(monkeypatch)
    set_system_mode(db, mode="manual_only", actor=actor)
    self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    review = db.query(LearningReview).filter(LearningReview.review_status == "pending").first()
    approve_review(db, review_id=review.id, actor=actor, notes="approved")

    snapshot = get_human_control_snapshot(db)

    assert snapshot["recent_human_actions_summary"]["total_actions"] >= 2
    assert "approve_review" in snapshot["recent_human_actions_summary"]["actions_by_type"]
    assert snapshot["approval_rate"] >= 0.0
    assert snapshot["rejection_rate"] >= 0.0
    assert snapshot["override_rate"] >= 0.0


def test_default_auto_mode_preserves_autonomy(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["status"] == "applied"
    assert result["human_control"]["system_mode"] == "auto"
