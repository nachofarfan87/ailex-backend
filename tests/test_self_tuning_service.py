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
from app.services.learning_runtime_config_store import load_latest_runtime_config, save_runtime_config
from app.services.utc import utc_now


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'self_tuning.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _seed_runtime_config(db: Session, *, apply_confidence_delta: float = 0.0) -> None:
    learning_runtime_config.reset_runtime_config()
    learning_runtime_config.set_self_tuning_control("apply_confidence_delta", apply_confidence_delta)
    save_runtime_config(db, learning_runtime_config.get_effective_runtime_config())
    db.commit()


def _create_self_tuning_history(
    db: Session,
    *,
    parameter_name: str,
    direction: str,
    impact_status: str | None = None,
    created_at=None,
) -> None:
    db.add(
        LearningActionLog(
            event_type="self_tuning",
            recommendation_type="self_tuning_cycle",
            applied=True,
            reason="self_tuning_applied",
            confidence_score=0.8,
            priority=None,
            impact_status=impact_status,
            evidence_json="{}",
            changes_applied_json=json.dumps(
                {
                    "applied_adjustments": [
                        {
                            "parameter_name": parameter_name,
                            "previous_value": 0.0,
                            "new_value": 0.02,
                            "direction": direction,
                            "delta": 0.02,
                        }
                    ]
                }
            ),
            applied_at=created_at or utc_now(),
            created_at=created_at or utc_now(),
        )
    )
    db.commit()


def _mock_signals(
    monkeypatch,
    *,
    sample_size: int = 64,
    improvement_rate: float = 0.76,
    regression_rate: float = 0.04,
    neutral_rate: float = 0.20,
    failed_ratio: float = 0.05,
    questionable_ratio: float = 0.1,
    rollback_ratio: float = 0.0,
    rollback_candidates: int = 0,
    recent_avg_score: float = 0.38,
    previous_avg_score: float = 0.32,
    historical_avg_score: float = 0.24,
    recent_vs_historical_delta: float = 0.14,
    trend_stability: float = 0.82,
    consistency: float = 0.86,
    drift_level: str = "none",
    governance_status: str = "healthy",
    top_flag_counts: dict | None = None,
):
    monkeypatch.setattr(
        self_tuning_service,
        "collect_self_tuning_signals",
        lambda db, limit=100: {
            "sample_size": sample_size,
            "impact_total": sample_size,
            "total_observations": sample_size,
            "audited_count": sample_size,
            "improvement_rate": improvement_rate,
            "regression_rate": regression_rate,
            "neutral_rate": neutral_rate,
            "failed_ratio": failed_ratio,
            "questionable_ratio": questionable_ratio,
            "rollback_ratio": rollback_ratio,
            "rollback_candidates": rollback_candidates,
            "recent_avg_score": recent_avg_score,
            "previous_avg_score": previous_avg_score,
            "historical_avg_score": historical_avg_score,
            "recent_vs_historical_delta": recent_vs_historical_delta,
            "trend_stability": trend_stability,
            "consistency": consistency,
            "drift_level": drift_level,
            "governance_status": governance_status,
            "top_flag_counts": top_flag_counts or {},
            "overview": {},
            "impact_summary": {},
            "governance_summary": {},
            "drift": {},
        },
    )


def test_no_data_returns_no_adjustment(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(
        monkeypatch,
        sample_size=0,
        improvement_rate=0.0,
        regression_rate=0.0,
        neutral_rate=0.0,
        consistency=0.0,
        trend_stability=0.0,
    )

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)

    assert result["status"] == "no_data"
    assert result["applied_adjustments"] == []


def test_dry_run_simulates_without_mutating_config(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)
    latest_runtime = load_latest_runtime_config(db)

    assert result["status"] == "simulated"
    assert latest_runtime["self_tuning_controls"]["apply_confidence_delta"] == 0.0


def test_apply_mode_updates_config_and_audit_trail(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    latest_runtime = load_latest_runtime_config(db)
    action_log = db.query(LearningActionLog).filter(LearningActionLog.event_type == "self_tuning").first()

    assert result["status"] == "applied"
    assert result["applied_adjustments"]
    assert action_log is not None
    assert latest_runtime["self_tuning_controls"]["apply_confidence_delta"] != 0.0

    evidence_payload = json.loads(action_log.evidence_json)
    assert "signals_snapshot" in evidence_payload
    assert "tuning_history_snapshot" in evidence_payload


def test_trend_instability_blocks_cycle(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch, trend_stability=0.34)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["status"] == "blocked"
    assert "unstable_trend" in result["blocked_reasons"]


def test_contradictory_recent_evidence_blocks_cycle(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(
        monkeypatch,
        recent_avg_score=-0.08,
        previous_avg_score=0.28,
        historical_avg_score=0.21,
        recent_vs_historical_delta=-0.31,
        regression_rate=0.16,
    )

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["status"] == "blocked"
    assert "contradictory_recent_evidence" in result["blocked_reasons"]


def test_historical_ineffective_tuning_blocks_parameter(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_self_tuning_history(
        db,
        parameter_name="apply_confidence_delta",
        direction="decrease",
        impact_status="regressed",
        created_at=utc_now() - timedelta(hours=96),
    )
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)
    candidate = next(
        item for item in result["candidate_adjustments"]
        if item["parameter_name"] == "apply_confidence_delta"
    )

    assert "historical_ineffective_tuning" in candidate["blocked_reasons"]


def test_unknown_tuning_history_does_not_block_by_itself(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_self_tuning_history(
        db,
        parameter_name="apply_confidence_delta",
        direction="decrease",
        impact_status=None,
        created_at=utc_now() - timedelta(hours=96),
    )
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)
    actionable = [candidate for candidate in result["candidate_adjustments"] if not candidate["blocked"]]

    assert actionable


def test_rollback_pressure_blocks_cycle(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch, rollback_ratio=0.09, rollback_candidates=3)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["status"] == "blocked"
    assert "rollback_pressure_block" in result["blocked_reasons"]


def test_cold_start_tuning_block_works(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch, sample_size=28)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["status"] == "blocked"
    assert "cold_start_tuning_block" in result["blocked_reasons"]


def test_candidate_prioritization_respects_new_rule(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(
        monkeypatch,
        improvement_rate=0.18,
        regression_rate=0.18,
        failed_ratio=0.12,
        consistency=0.72,
        trend_stability=0.81,
        top_flag_counts={"simulation_overconfidence": 2},
    )

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)
    actionable = [candidate for candidate in result["candidate_adjustments"] if not candidate["blocked"]]

    assert actionable
    assert actionable[0]["parameter_name"] == "apply_confidence_delta"
    assert actionable[0]["priority_score"] >= actionable[-1]["priority_score"]


def test_allowlisted_params_remain_the_only_adjustable(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)

    assert all(
        candidate["parameter_name"] in learning_runtime_config.get_self_tuning_controls()
        for candidate in result["candidate_adjustments"]
    )


def test_get_latest_self_tuning_cycle_returns_snapshot(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)
    self_tuning_service.run_self_tuning_cycle(db, dry_run=True)

    latest = self_tuning_service.get_latest_self_tuning_cycle(db)

    assert latest is not None
    assert latest["event_type"] == "self_tuning"


def test_self_tuning_preserves_rollback_compatibility(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)

    assert result["rollback_reference"] == "manual_runtime_rollback"


def test_collect_self_tuning_signals_is_defensive(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)

    signals = self_tuning_service.collect_self_tuning_signals(db)

    assert signals["sample_size"] == 0
    assert signals["governance_status"] == "healthy"
    assert "trend_stability" in signals
    assert "consistency" in signals


# ---------------------------------------------------------------------------
# FASE 8.1B — Mode, Safety, Budget, Explanation in service layer
# ---------------------------------------------------------------------------


def test_get_and_set_self_tuning_mode():
    assert self_tuning_service.get_self_tuning_mode() in {"conservative", "balanced", "aggressive"}
    previous = self_tuning_service.get_self_tuning_mode()
    self_tuning_service.set_self_tuning_mode("conservative")
    assert self_tuning_service.get_self_tuning_mode() == "conservative"
    self_tuning_service.set_self_tuning_mode("aggressive")
    assert self_tuning_service.get_self_tuning_mode() == "aggressive"
    self_tuning_service.set_self_tuning_mode(previous)


def test_set_invalid_mode_raises():
    import pytest

    with pytest.raises(ValueError, match="Invalid self-tuning mode"):
        self_tuning_service.set_self_tuning_mode("turbo")


def test_metadata_includes_self_tuning_mode(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)
    self_tuning_service.set_self_tuning_mode("balanced")

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)

    assert "self_tuning_mode" in result["metadata"]
    assert result["metadata"]["self_tuning_mode"] == "balanced"


def test_conservative_mode_limits_applied_adjustments(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(
        monkeypatch,
        improvement_rate=0.18,
        regression_rate=0.18,
        failed_ratio=0.12,
        consistency=0.72,
        trend_stability=0.81,
        top_flag_counts={"simulation_overconfidence": 2},
    )
    self_tuning_service.set_self_tuning_mode("conservative")

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)

    actionable = [c for c in result["candidate_adjustments"] if not c["blocked"]]
    assert len(actionable) <= 1
    self_tuning_service.set_self_tuning_mode("balanced")


def test_evidence_json_includes_safety_and_budget(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    action_log = db.query(LearningActionLog).filter(LearningActionLog.event_type == "self_tuning").first()

    assert action_log is not None
    evidence_payload = json.loads(action_log.evidence_json)
    assert "safety_checks" in evidence_payload
    assert "budget_usage" in evidence_payload
    assert "aggressiveness_mode" in evidence_payload
    assert isinstance(evidence_payload["safety_checks"], dict)
    assert isinstance(evidence_payload["budget_usage"], dict)


def test_explanation_present_in_candidates(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _mock_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=True)

    for candidate in result["candidate_adjustments"]:
        assert "explanation" in candidate
        explanation = candidate["explanation"]
        assert "why" in explanation
        assert "why_not" in explanation
        assert "risk_context" in explanation
        assert "historical_context" in explanation
