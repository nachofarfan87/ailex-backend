from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_action_log  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.services import learning_runtime_config
from app.services.learning_governance_feedback_service import (
    evaluate_governance_feedback,
    resolve_governance_feedback,
)
from app.services.learning_runtime_config_store import LearningRuntimeConfig, load_latest_runtime_config, save_runtime_config


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning_governance_feedback.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _seed_runtime_config(db: Session) -> None:
    learning_runtime_config.reset_runtime_config()
    save_runtime_config(
        db,
        {
            "prefer_hybrid_domains": [],
            "force_full_pipeline_domains": [],
            "thresholds": {
                "low_confidence": 0.5,
                "low_decision_confidence": 0.5,
            },
        },
    )
    db.commit()


def test_governance_healthy_produces_no_feedback():
    result = evaluate_governance_feedback(
        {
            "audited_count": 10,
            "failed_count": 0,
            "rollback_candidates": 0,
            "review_candidates": 1,
            "status": "healthy",
            "top_flags": [{"flag": "applied_then_improved", "count": 8}],
        }
    )

    assert result["should_apply"] is False
    assert result["feedback_mode"] == "none"
    assert result["feedback_state"] == "none"
    assert result["proposed_adjustments"] == {}


def test_governance_watch_produces_cautious_feedback():
    result = evaluate_governance_feedback(
        {
            "audited_count": 20,
            "failed_count": 3,
            "rollback_candidates": 1,
            "review_candidates": 6,
            "status": "watch",
            "top_flags": [{"flag": "simulation_overconfidence", "count": 3}],
        }
    )

    assert result["should_apply"] is True
    assert result["feedback_mode"] == "cautious"
    assert result["severity"] == "medium"


def test_governance_degraded_produces_protective_feedback():
    result = evaluate_governance_feedback(
        {
            "audited_count": 20,
            "failed_count": 7,
            "rollback_candidates": 3,
            "review_candidates": 5,
            "status": "degraded",
            "top_flags": [{"flag": "applied_then_regressed", "count": 4}],
        }
    )

    assert result["should_apply"] is True
    assert result["feedback_mode"] == "protective"
    assert result["severity"] == "high"


def test_simulation_overconfidence_frequent_adds_trigger():
    result = evaluate_governance_feedback(
        {
            "audited_count": 12,
            "failed_count": 1,
            "rollback_candidates": 0,
            "review_candidates": 2,
            "status": "healthy",
            "top_flags": [{"flag": "simulation_overconfidence", "count": 3}],
        }
    )

    assert "simulation_overconfidence_pressure" in result["trigger_flags"]
    assert result["feedback_mode"] == "cautious"


def test_high_rollback_candidates_hardens_mode():
    result = evaluate_governance_feedback(
        {
            "audited_count": 15,
            "failed_count": 2,
            "rollback_candidates": 3,
            "review_candidates": 2,
            "status": "watch",
            "top_flags": [],
        }
    )

    assert "rollback_candidates_elevated" in result["trigger_flags"]
    assert result["feedback_mode"] == "protective"


def test_proposed_adjustments_have_clear_structure():
    result = evaluate_governance_feedback(
        {
            "audited_count": 15,
            "failed_count": 3,
            "rollback_candidates": 1,
            "review_candidates": 5,
            "status": "watch",
            "top_flags": [],
        }
    )

    assert "budget_caps" in result["proposed_adjustments"]
    assert "threshold_adjustments" in result["proposed_adjustments"]
    assert "uncertain_apply_policy" in result["proposed_adjustments"]


def test_feedback_application_is_persisted_when_needed(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)

    monkeypatch.setattr(
        "app.services.learning_governance_feedback_service.get_learning_governance_summary",
        lambda _db, limit=100: {
            "audited_count": 18,
            "failed_count": 5,
            "rollback_candidates": 2,
            "review_candidates": 4,
            "status": "degraded",
            "top_flags": [{"flag": "high_risk_failure", "count": 3}],
        },
    )

    result = resolve_governance_feedback(db)

    action_log = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == "governance_feedback")
        .first()
    )
    latest_runtime = load_latest_runtime_config(db)

    assert result["applied"] is True
    assert result["feedback_state"] == "applied"
    assert action_log is not None
    assert action_log.recommendation_type == "governance_feedback_loop"
    assert latest_runtime["governance_controls"]["feedback_mode"] == "protective"


def test_feedback_is_not_applied_when_not_needed(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)

    monkeypatch.setattr(
        "app.services.learning_governance_feedback_service.get_learning_governance_summary",
        lambda _db, limit=100: {
            "audited_count": 10,
            "failed_count": 0,
            "rollback_candidates": 0,
            "review_candidates": 1,
            "status": "healthy",
            "top_flags": [],
        },
    )

    result = resolve_governance_feedback(db)

    assert result["applied"] is False
    assert result["feedback_state"] == "none"
    assert db.query(LearningActionLog).count() == 0


def test_feedback_state_is_already_active_when_same_mode_is_active(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    save_runtime_config(
        db,
        {
            "prefer_hybrid_domains": [],
            "force_full_pipeline_domains": [],
            "thresholds": {
                "low_confidence": 0.55,
                "low_decision_confidence": 0.55,
            },
            "governance_controls": {
                "feedback_mode": "cautious",
                "severity": "medium",
                "adjustments": {
                    "budget_caps": {
                        "max_changes_cap": 2,
                        "max_high_risk_changes": 0,
                    },
                    "threshold_adjustments": {
                        "low_confidence": 0.05,
                        "low_decision_confidence": 0.05,
                    },
                    "uncertain_apply_policy": "restricted",
                },
                "trigger_flags": ["governance_watch"],
            },
        },
    )
    db.commit()

    monkeypatch.setattr(
        "app.services.learning_governance_feedback_service.get_learning_governance_summary",
        lambda _db, limit=100: {
            "audited_count": 20,
            "failed_count": 3,
            "rollback_candidates": 1,
            "review_candidates": 6,
            "status": "watch",
            "top_flags": [{"flag": "simulation_overconfidence", "count": 3}],
        },
    )

    result = resolve_governance_feedback(db)

    assert result["should_apply"] is True
    assert result["applied"] is False
    assert result["feedback_state"] == "already_active"
    assert result["skip_reason"] == "feedback_mode_already_active"
    assert db.query(LearningActionLog).count() == 0


def test_threshold_adjustments_are_clamped_within_range(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()
    save_runtime_config(
        db,
        {
            "prefer_hybrid_domains": [],
            "force_full_pipeline_domains": [],
            "thresholds": {
                "low_confidence": 0.95,
                "low_decision_confidence": 0.95,
            },
        },
    )
    db.commit()

    monkeypatch.setattr(
        "app.services.learning_governance_feedback_service.get_learning_governance_summary",
        lambda _db, limit=100: {
            "audited_count": 20,
            "failed_count": 7,
            "rollback_candidates": 3,
            "review_candidates": 5,
            "status": "degraded",
            "top_flags": [{"flag": "high_risk_failure", "count": 4}],
        },
    )

    result = resolve_governance_feedback(db)
    latest_runtime = load_latest_runtime_config(db)

    assert result["applied"] is True
    assert latest_runtime["thresholds"]["low_confidence"] == 1.0
    assert latest_runtime["thresholds"]["low_decision_confidence"] == 1.0


def test_defensive_with_incomplete_governance_summary():
    result = evaluate_governance_feedback({"status": "watch"})

    assert result["feedback_mode"] == "cautious"
    assert isinstance(result["trigger_flags"], list)


def test_no_crash_when_top_flags_missing():
    result = evaluate_governance_feedback(
        {
            "audited_count": 8,
            "failed_count": 1,
            "rollback_candidates": 0,
            "review_candidates": 0,
            "status": "healthy",
        }
    )

    assert result["feedback_mode"] in {"none", "cautious", "protective"}
    assert isinstance(result["proposed_adjustments"], dict)


def test_no_crash_when_runtime_config_has_no_governance_controls(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)

    monkeypatch.setattr(
        "app.services.learning_governance_feedback_service.get_learning_governance_summary",
        lambda _db, limit=100: {
            "audited_count": 20,
            "failed_count": 3,
            "rollback_candidates": 1,
            "review_candidates": 6,
            "status": "watch",
            "top_flags": [],
        },
    )

    result = resolve_governance_feedback(db)

    assert result["feedback_state"] == "applied"
