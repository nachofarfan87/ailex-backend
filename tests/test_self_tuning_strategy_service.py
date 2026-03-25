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
from app.services.self_tuning_strategy_service import (
    build_self_tuning_strategy_snapshot,
    get_self_tuning_strategy_summary,
    resolve_final_tuning_action,
)
from app.services.utc import utc_now


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'self_tuning_strategy.db'}",
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
    strategy_profile: str = "micro_adjustment",
    strategy_controls: dict | None = None,
    current_context: str = "stable",
    restricted_parameters: list[str] | None = None,
    meta_action: str = "apply",
    final_action: str = "simulate",
    requested_mode: str = "balanced",
    effective_mode: str = "balanced",
    impact_status: str | None = None,
    created_at=None,
) -> None:
    db.add(
        LearningActionLog(
            event_type="self_tuning",
            recommendation_type="self_tuning_cycle",
            applied=status == "applied",
            reason=f"self_tuning_{status}",
            confidence_score=0.82,
            impact_status=impact_status,
            evidence_json=json.dumps(
                {
                    "meta_decision": {
                        "requested_mode": requested_mode,
                        "recommended_mode": effective_mode,
                        "base_recommended_action": meta_action,
                        "final_recommended_action": final_action,
                    },
                    "strategy_decision": {
                        "strategy_profile": strategy_profile,
                        "strategy_controls": strategy_controls
                        or {
                            "effective_step_multiplier": 0.5,
                            "effective_cooldown_multiplier": 1.5,
                            "effective_max_adjustments": 1,
                            "effective_cooldown_hours": 36,
                        },
                        "strategy_reasoning": ["test strategy"],
                        "strategy_risk_flags": [],
                        "strategy_override_applied": meta_action != final_action or requested_mode != effective_mode,
                        "strategy_support_level": "medium",
                        "current_context": current_context,
                        "restricted_parameters": restricted_parameters or [],
                        "base_strategy_profile": strategy_profile,
                        "final_strategy_profile": strategy_profile,
                        "strategy_transition_reason": "test transition",
                        "strategy_hysteresis_applied": False,
                        "meta_recommended_action": meta_action,
                        "strategy_recommended_action": final_action,
                        "final_resolved_action": final_action,
                        "decision_precedence": "strategy_hardens_meta" if meta_action != final_action else "aligned",
                        "strategy_conflict_resolved": meta_action != final_action,
                        "strategy_conflict_reason": "test conflict" if meta_action != final_action else None,
                    },
                }
            ),
            changes_applied_json=json.dumps({"status": status, "candidate_adjustments": [], "applied_adjustments": []}),
            created_at=created_at or utc_now(),
        )
    )
    db.commit()


def _mock_live_signals(monkeypatch, **overrides):
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


def test_build_strategy_snapshot_returns_usable_strategy_data():
    snapshot = build_self_tuning_strategy_snapshot(
        recommendation={
            "candidate_adjustments": [
                {
                    "parameter_name": "apply_confidence_delta",
                    "current_value": 0.0,
                    "proposed_value": -0.02,
                    "delta": -0.02,
                    "confidence": 0.82,
                    "priority_score": 0.8,
                    "blocked": False,
                    "blocked_reasons": [],
                    "explanation": {"why_not": []},
                }
            ],
            "risk_flags": [],
        },
        meta_snapshot={
            "recommended_action": "apply",
            "meta_confidence": 0.52,
            "meta_risk_flags": [],
            "history_window_summary": {"weighted_unknown_outcome_rate": 0.1},
            "historical_support": {
                "risky_parameters": [],
                "supportive_parameters": [],
                "mode_support": {"requested_mode_evidence_status": "insufficient_mode_evidence"},
            },
            "meta_signals": {"current_context": "fragile"},
        },
        current_signals={"rollback_ratio": 0.0, "trend_stability": 0.42, "consistency": 0.44, "sample_size": 64},
        tuning_history=[],
    )

    assert snapshot["strategy_profile"] in {"micro_adjustment", "restricted_adjustment"}
    assert "strategy_controls" in snapshot
    assert "adapted_candidates" in snapshot
    assert "final_strategy_profile" in snapshot
    assert "strategy_hysteresis_applied" in snapshot
    assert "strategy_hysteresis_state" in snapshot


def test_strategy_summary_aggregates_profiles_and_restrictions(tmp_path):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    _create_cycle(
        db,
        status="simulated",
        strategy_profile="micro_adjustment",
        current_context="fragile",
        restricted_parameters=["apply_confidence_delta"],
        meta_action="apply",
        final_action="simulate",
    )
    _create_cycle(
        db,
        status="observe_only",
        strategy_profile="restricted_adjustment",
        current_context="rollback_pressure",
        restricted_parameters=["uncertain_apply_confidence_min"],
        meta_action="simulate",
        final_action="observe_only",
        created_at=utc_now() - timedelta(hours=2),
    )

    summary = get_self_tuning_strategy_summary(db)

    assert summary["strategy_profile_current"] in {"micro_adjustment", "restricted_adjustment"}
    assert "strategy_profiles_used" in summary
    assert summary["parameters_most_restricted"]
    assert summary["micro_adjustment_contexts"]
    assert "strategy_profile_rates" in summary
    assert "strategy_profile_transitions" in summary
    assert "average_effective_step_multiplier" in summary
    assert "average_effective_cooldown_hours" in summary
    assert "strategy_stability_score" in summary
    assert "strategy_stability_label" in summary
    assert "strategy_restriction_rate" in summary
    assert "strategy_transition_summary" in summary


def test_run_cycle_persists_strategy_controls_and_auditability(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    _seed_runtime_config(db)
    for hours_ago in [2, 10, 18]:
        _create_cycle(
            db,
            status="applied",
            strategy_profile="micro_adjustment",
            current_context="stable",
            meta_action="apply",
            final_action="apply",
            impact_status="improved",
            created_at=utc_now() - timedelta(hours=hours_ago),
        )
    _mock_live_signals(monkeypatch)

    result = self_tuning_service.run_self_tuning_cycle(db, dry_run=False)
    action_log = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == "self_tuning")
        .order_by(LearningActionLog.created_at.desc())
        .first()
    )
    evidence_payload = json.loads(action_log.evidence_json)

    assert result["strategy_profile"] in {
        "micro_adjustment",
        "standard_adjustment",
        "restricted_adjustment",
        "observe_only_strategy",
    }
    assert "strategy_controls" in result
    assert "strategy_recommended_action" in result
    assert "strategy_decision" in evidence_payload
    assert "strategy_controls" in evidence_payload["strategy_decision"]
    assert "strategy_override_applied" in evidence_payload["strategy_decision"]
    assert "final_resolved_action" in evidence_payload["strategy_decision"]
    assert "strategy_hysteresis_state" in result


def test_effective_strategy_changes_effective_delta_in_candidates():
    candidate_recommendation = {
        "candidate_adjustments": [
            {
                "parameter_name": "apply_confidence_delta",
                "current_value": 0.0,
                "proposed_value": -0.02,
                "delta": -0.02,
                "confidence": 0.86,
                "priority_score": 0.8,
                "blocked": False,
                "blocked_reasons": [],
                "explanation": {"why_not": []},
            }
        ],
        "risk_flags": [],
    }
    snapshot = build_self_tuning_strategy_snapshot(
        recommendation=candidate_recommendation,
        meta_snapshot={
            "recommended_action": "apply",
            "meta_confidence": 0.48,
            "meta_risk_flags": [],
            "history_window_summary": {"weighted_unknown_outcome_rate": 0.2},
            "historical_support": {
                "risky_parameters": [],
                "supportive_parameters": [],
                "mode_support": {"requested_mode_evidence_status": "insufficient_mode_evidence"},
            },
            "meta_signals": {"current_context": "fragile"},
        },
        current_signals={"trend_stability": 0.48, "consistency": 0.5, "rollback_ratio": 0.0, "sample_size": 64},
        tuning_history=[],
    )

    candidate = snapshot["adapted_candidates"][0]
    assert abs(float(candidate["strategy_effective_delta"])) <= abs(float(candidate["delta"]))


def test_conflict_resolution_is_explicit_and_strategy_cannot_relax_meta():
    resolved = resolve_final_tuning_action(
        meta_recommended_action="simulate",
        strategy_recommended_action="apply",
    )

    assert resolved["final_resolved_action"] == "simulate"
    assert resolved["strategy_conflict_resolved"] is True
    assert resolved["decision_precedence"] == "meta_dominates"
