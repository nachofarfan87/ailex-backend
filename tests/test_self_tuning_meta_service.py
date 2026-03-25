from __future__ import annotations

import json
from pathlib import Path
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_action_log  # noqa: F401
import app.models.learning_human_audit  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_decision_audit_log  # noqa: F401
import app.models.learning_review  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.services import learning_runtime_config, self_tuning_service
from app.services.learning_runtime_config_store import save_runtime_config
from app.services.self_tuning_meta_service import build_self_tuning_meta_snapshot, get_self_tuning_meta_summary
from app.services.utc import utc_now


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'self_tuning_meta.db'}",
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


def _create_cycle(
    db: Session,
    *,
    status: str,
    parameter_name: str = "apply_confidence_delta",
    direction: str = "decrease",
    mode: str = "balanced",
    confidence: float = 0.82,
    impact_status: str | None = None,
    rollback_ratio: float = 0.0,
    trend_stability: float = 0.82,
    consistency: float = 0.84,
    sample_size: int = 64,
    drift_level: str = "none",
    created_at=None,
) -> None:
    applied_adjustments = []
    candidate_adjustments = [
        {
            "parameter_name": parameter_name,
            "direction": direction,
            "delta": 0.02,
            "confidence": confidence,
            "priority_score": 0.8,
            "blocked": status not in {"applied", "simulated"},
        }
    ]
    if status == "applied":
        applied_adjustments = [
            {
                "parameter_name": parameter_name,
                "direction": direction,
                "delta": 0.02,
                "previous_value": 0.0,
                "new_value": -0.02,
            }
        ]
    db.add(
        LearningActionLog(
            event_type="self_tuning",
            recommendation_type="self_tuning_cycle",
            applied=status == "applied",
            reason=f"self_tuning_{status}",
            confidence_score=confidence,
            impact_status=impact_status,
            evidence_json=json.dumps(
                {
                    "signals_snapshot": {
                        "rollback_ratio": rollback_ratio,
                        "trend_stability": trend_stability,
                        "consistency": consistency,
                        "drift_level": drift_level,
                        "sample_size": sample_size,
                    },
                    "risk_flags": ["rollback_pressure"] if rollback_ratio >= 0.08 else [],
                    "aggressiveness_mode": mode,
                }
            ),
            changes_applied_json=json.dumps(
                {
                    "status": status,
                    "candidate_adjustments": candidate_adjustments,
                    "applied_adjustments": applied_adjustments,
                }
            ),
            created_at=created_at or utc_now(),
        )
    )
    db.commit()


def _mock_live_signals(monkeypatch):
    monkeypatch.setattr(
        self_tuning_service,
        "collect_self_tuning_signals",
        lambda db, limit=100: {
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
        },
    )


def test_parameter_with_high_rollback_rate_is_penalized_in_meta_snapshot(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(db, status="applied", impact_status="regressed", rollback_ratio=0.12)
    _create_cycle(db, status="applied", impact_status="neutral", rollback_ratio=0.12)

    snapshot = get_self_tuning_meta_summary(db)

    performance = snapshot["parameter_performance"]["apply_confidence_delta"]
    assert performance["rollback_after_tuning_rate"] > 0.0
    assert snapshot["top_risky_parameters"]


def test_recent_events_weigh_more_than_old_events(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(
        db,
        status="applied",
        parameter_name="apply_confidence_delta",
        impact_status="regressed",
        created_at=utc_now() - timedelta(days=14),
    )
    _create_cycle(
        db,
        status="applied",
        parameter_name="apply_confidence_delta",
        impact_status="improved",
        created_at=utc_now() - timedelta(hours=3),
    )

    snapshot = get_self_tuning_meta_summary(db)

    performance = snapshot["parameter_performance"]["apply_confidence_delta"]
    assert performance["weighted_success_rate"] > performance["success_rate"]


def test_parameter_context_performance_changes_in_fragile_context(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(
        db,
        status="applied",
        parameter_name="apply_confidence_delta",
        impact_status="improved",
        trend_stability=0.85,
        consistency=0.88,
    )
    _create_cycle(
        db,
        status="applied",
        parameter_name="apply_confidence_delta",
        impact_status="regressed",
        trend_stability=0.32,
        consistency=0.4,
    )

    snapshot = get_self_tuning_meta_summary(db)

    contexts = snapshot["parameter_performance"]["apply_confidence_delta"]["context_performance"]
    assert contexts["stable"]["context_meta_score"] > contexts["fragile"]["context_meta_score"]


def test_top_effective_parameters_are_exposed(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="improved")
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="improved")
    _create_cycle(db, status="applied", parameter_name="uncertain_apply_confidence_min", impact_status="regressed")

    snapshot = get_self_tuning_meta_summary(db)

    assert snapshot["top_effective_parameters"][0]["parameter_name"] == "apply_confidence_delta"


def test_meta_snapshot_is_persisted_and_auditable(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="improved")
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="improved")
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="improved")
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="improved")
    _mock_live_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    action_log = db.query(LearningActionLog).filter(LearningActionLog.event_type == "self_tuning").order_by(LearningActionLog.created_at.desc()).first()

    assert result["meta_status"] is not None
    assert result["recommended_action"] in {"apply", "simulate", "observe_only", "block"}
    assert "override_summary" in result
    evidence_payload = json.loads(action_log.evidence_json)
    assert "meta_decision" in evidence_payload
    assert "meta_signals" in evidence_payload
    assert "base_recommended_action" in evidence_payload["meta_decision"]
    assert "final_recommended_action" in evidence_payload["meta_decision"]


def test_meta_policy_can_degrade_apply_to_simulate_in_service(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    for _ in range(5):
        _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status=None)
    _mock_live_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["recommended_action"] in {"simulate", "apply", "observe_only", "block"}
    assert result["meta_status"] is not None
    assert "base_recommended_action" in result["override_summary"]
    assert "final_recommended_action" in result["override_summary"]


def test_meta_summary_returns_usable_backend_snapshot(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="improved")
    _create_cycle(db, status="simulated", parameter_name="uncertain_apply_confidence_min", impact_status=None)

    snapshot = get_self_tuning_meta_summary(db)

    assert "recommended_mode" in snapshot
    assert "recommended_action" in snapshot
    assert "mode_performance" in snapshot
    assert "parameter_performance" in snapshot
    assert "history_window_summary" in snapshot
    assert "meta_confidence" in snapshot
    assert "meta_confidence_reasoning" in snapshot
    assert "meta_confidence_components" in snapshot
    assert "mode_evidence_status" in snapshot
    assert "context_performance" in snapshot
    assert "meta_override_rate" in snapshot["override_summary"]
    assert "meta_action_override_rate" in snapshot["override_summary"]
    assert "meta_mode_override_rate" in snapshot["override_summary"]


def test_build_meta_snapshot_marks_risky_candidates(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="regressed", rollback_ratio=0.12)
    _create_cycle(db, status="applied", parameter_name="apply_confidence_delta", impact_status="regressed", rollback_ratio=0.12)

    snapshot = build_self_tuning_meta_snapshot(
        db,
        current_recommendation={
            "candidate_adjustments": [
                {
                    "parameter_name": "apply_confidence_delta",
                    "direction": "increase",
                    "blocked": False,
                    "priority_score": 0.8,
                    "confidence": 0.84,
                    "blocked_reasons": [],
                    "explanation": {"why_not": []},
                }
            ]
        },
        current_signals={"trend_stability": 0.82, "consistency": 0.86},
        requested_mode="balanced",
        dry_run=False,
    )

    candidate = snapshot["adjusted_candidates"][0]
    assert candidate["meta_support_label"] == "risky"
    assert "meta_historically_risky_parameter" in candidate["blocked_reasons"]


def test_mode_with_small_sample_is_marked_insufficient(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(db, status="applied", mode="aggressive", impact_status="improved")

    snapshot = get_self_tuning_meta_summary(db)

    assert snapshot["mode_evidence_status"]["aggressive"] == "insufficient_mode_evidence"


def test_weighted_rollback_rate_penalizes_recent_bad_strategy(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(
        db,
        status="applied",
        parameter_name="apply_confidence_delta",
        impact_status="improved",
        rollback_ratio=0.0,
        created_at=utc_now() - timedelta(days=12),
    )
    _create_cycle(
        db,
        status="applied",
        parameter_name="apply_confidence_delta",
        impact_status="regressed",
        rollback_ratio=0.12,
        created_at=utc_now() - timedelta(hours=2),
    )

    snapshot = get_self_tuning_meta_summary(db)

    performance = snapshot["parameter_performance"]["apply_confidence_delta"]
    assert performance["weighted_rollback_rate"] > performance["rollback_after_tuning_rate"]


def test_meta_confidence_can_fall_clearly_to_low_zone(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(
        db,
        status="applied",
        impact_status=None,
        trend_stability=0.35,
        consistency=0.38,
        sample_size=18,
        created_at=utc_now() - timedelta(days=10),
    )

    snapshot = get_self_tuning_meta_summary(db)

    assert snapshot["meta_confidence"] < 0.4


def test_meta_confidence_can_rise_clearly_to_high_zone(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    for hours_ago in [2, 8, 20, 30, 48]:
        _create_cycle(
            db,
            status="applied",
            impact_status="improved",
            trend_stability=0.86,
            consistency=0.88,
            sample_size=72,
            created_at=utc_now() - timedelta(hours=hours_ago),
        )

    snapshot = get_self_tuning_meta_summary(db)

    assert snapshot["meta_confidence"] >= 0.8


def test_meta_confidence_reasoning_has_component_traceability(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(db, status="applied", impact_status="improved")
    snapshot = get_self_tuning_meta_summary(db)

    reasoning = snapshot["meta_confidence_reasoning"]
    components = snapshot["meta_confidence_components"]
    assert any(item.startswith("evidence_component=") for item in reasoning)
    assert any(item.startswith("stability_component=") for item in reasoning)
    assert any(item.startswith("uncertainty_penalty=") for item in reasoning)
    assert any(item.startswith("rollback_penalty=") for item in reasoning)
    assert "evidence_component" in components
    assert "rollback_penalty" in components


def test_unknown_does_not_change_known_success_failure_rates(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(db, status="applied", impact_status="improved")
    _create_cycle(db, status="applied", impact_status="regressed")
    _create_cycle(db, status="applied", impact_status=None)

    snapshot = get_self_tuning_meta_summary(db)

    performance = snapshot["parameter_performance"]["apply_confidence_delta"]
    assert performance["success_rate"] == 0.5
    assert performance["failure_rate"] == 0.5
    assert performance["unknown_outcome_rate"] > 0.0


def test_override_summary_distinguishes_action_vs_mode_override(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    for _ in range(4):
        _create_cycle(db, status="applied", impact_status="improved")
    _create_cycle(db, status="simulated", mode="aggressive", impact_status=None)
    _mock_live_signals(monkeypatch)

    self_tuning_service.run_self_tuning_cycle(db, dry_run=False, aggressiveness_mode="aggressive")
    snapshot = get_self_tuning_meta_summary(db)

    override_summary = snapshot["override_summary"]
    assert "meta_override_rate" in override_summary
    assert "meta_action_override_rate" in override_summary
    assert "meta_mode_override_rate" in override_summary
    assert "override_counts" in override_summary
