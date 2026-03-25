from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.learning import rollback_last
from app.db.database import Base
import app.models.learning_log  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.services.learning_actions_service import apply_recommendation
from app.services import learning_cycle_service, learning_runtime_config
from app.services.learning_runtime_config_store import LearningRuntimeConfig, load_latest_runtime_config, save_runtime_config


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning_cycle.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def test_run_learning_cycle_applies_valid_change(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "domain_override",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 10},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["total_recommendations"] == 1
    assert result["applied_count"] == 1
    assert result["skipped_count"] == 0
    assert result["results"][0]["applied"] is True
    assert result["results"][0]["reason"] == "applied_domain_override"
    assert "alimentos" in result["results"][0]["details"]["runtime_config"]["prefer_hybrid_domains"]

    action_logs = db.query(LearningActionLog).all()
    config_logs = db.query(LearningRuntimeConfig).all()
    assert len(action_logs) == 1
    assert action_logs[0].applied is True
    assert action_logs[0].applied_at is not None
    assert action_logs[0].impact_status == "pending"
    payload = json.loads(action_logs[0].changes_applied_json)
    assert payload["final_learning_decision"]["decision_class"] == "apply"
    assert payload["rank_position"] == 1
    assert "simulation_snapshot" in payload
    assert "operational_risk" in payload
    assert "budget_context" in payload
    assert len(config_logs) == 1
    assert '"config_version": "v1"' in config_logs[0].config_json


def test_run_learning_cycle_skips_low_confidence_recommendation(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "domain_override",
        "confidence_score": 0.5,
        "priority": 0.8,
        "evidence": {"sample_size": 12},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 0
    assert result["skipped_count"] == 1
    assert result["budget_context"]["mode"] == "normal"
    assert result["results"][0]["applied"] is False
    assert result["results"][0]["reason"] == "below_threshold"
    assert result["results"][0].get("details") is None

    action_logs = db.query(LearningActionLog).all()
    config_logs = db.query(LearningRuntimeConfig).all()
    assert len(action_logs) == 1
    assert action_logs[0].applied is False
    assert action_logs[0].applied_at is None
    assert action_logs[0].impact_status is None
    payload = json.loads(action_logs[0].changes_applied_json)
    assert payload["final_learning_decision"]["decision_class"] == "skip"
    assert len(config_logs) == 0


def test_run_learning_cycle_skips_manual_only_event_type(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "classification_review",
        "confidence_score": 0.95,
        "priority": 0.95,
        "evidence": {"sample_size": 20},
        "proposed_changes": {
            "classification_review": {
                "from_domain": "familia",
                "to_domain": "alimentos",
            }
        },
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 0
    assert result["skipped_count"] == 1
    assert result["results"][0]["applied"] is False
    assert result["results"][0]["reason"] == "manual_only_event_type"


def test_run_learning_cycle_persists_threshold_runtime_config(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "threshold_adjustment",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 12},
        "proposed_changes": {
            "threshold_review": {
                "low_confidence_threshold": 0.55,
                "low_decision_confidence_threshold": 0.65,
            }
        },
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 0
    assert result["skipped_count"] == 1
    assert result["results"][0]["applied"] is False
    assert result["results"][0]["final_learning_decision"]["decision_class"] == "defer"

    config_logs = db.query(LearningRuntimeConfig).all()
    assert len(config_logs) == 0


def test_apply_recommendation_requires_db_session():
    try:
        apply_recommendation(
            None,
            {
                "event_type": "domain_override",
                "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
            },
        )
        assert False, "Se esperaba ValueError"
    except ValueError as exc:
        assert str(exc) == "db_session_required"


def test_load_latest_runtime_config_is_backward_compatible_with_raw_format(tmp_path):
    db = _build_session(tmp_path)
    raw_record = LearningRuntimeConfig(
        config_json='{"prefer_hybrid_domains":["alimentos"],"force_full_pipeline_domains":[],"thresholds":{"low_confidence":0.5,"low_decision_confidence":0.5}}'
    )
    db.add(raw_record)
    db.commit()

    loaded = load_latest_runtime_config(db)

    assert loaded == {
        "prefer_hybrid_domains": ["alimentos"],
        "force_full_pipeline_domains": [],
        "thresholds": {
            "low_confidence": 0.5,
            "low_decision_confidence": 0.5,
        },
    }


def test_load_latest_runtime_config_returns_none_for_corrupt_json(tmp_path):
    db = _build_session(tmp_path)
    db.add(LearningRuntimeConfig(config_json="{invalid-json"))
    db.commit()

    assert load_latest_runtime_config(db) is None


def test_created_at_columns_are_indexed():
    assert LearningActionLog.created_at.property.columns[0].index is True
    assert LearningRuntimeConfig.created_at.property.columns[0].index is True


def test_rollback_logs_learning_action(tmp_path):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    initial_snapshot = save_runtime_config(
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
    learning_runtime_config.add_prefer_hybrid_domain("alimentos")
    save_runtime_config(db, learning_runtime_config.get_runtime_config())
    db.commit()

    result = rollback_last(db=db, _user=object())

    rollback_log = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == "rollback")
        .order_by(LearningActionLog.created_at.desc())
        .first()
    )

    assert result["status"] == "rolled_back"
    assert result["runtime_config"]["prefer_hybrid_domains"] == []
    assert rollback_log is not None
    assert rollback_log.recommendation_type == "manual_rollback"
    assert rollback_log.reason == "manual_rollback"
    assert rollback_log.impact_status == "pending"
    assert json.loads(rollback_log.evidence_json) == {"restored_snapshot_id": initial_snapshot.id}


def test_run_learning_cycle_defers_when_simulation_is_uncertain_and_risk_is_high(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "threshold_adjustment",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 12},
        "proposed_changes": {
            "threshold_review": {
                "low_confidence_threshold": 0.55,
                "low_decision_confidence_threshold": 0.65,
            }
        },
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "simulate_recommendation_outcome",
        lambda **kwargs: {
            "expected_outcome": "uncertain",
            "expected_impact_score": 0.05,
            "risk_score": 0.7,
            "confidence_score": 0.3,
            "simulation_mode": "historical_heuristic",
            "reasoning": "uncertain",
            "drivers": ["limited_historical_evidence"],
            "warnings": ["limited_historical_evidence"],
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 0
    assert result["skipped_count"] == 1
    assert result["results"][0]["applied"] is False
    assert result["results"][0]["final_learning_decision"]["decision_class"] == "defer"
    payload = json.loads(db.query(LearningActionLog).first().changes_applied_json)
    assert payload["simulation_snapshot"]["expected_outcome"] == "uncertain"
    assert payload["operational_risk"]["risk_level"] == "high"
    assert payload["final_learning_decision"]["decision_class"] == "defer"


def test_run_learning_cycle_skip_when_previous_layers_block(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "domain_override",
        "confidence_score": 0.5,
        "priority": 0.8,
        "evidence": {"sample_size": 12},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "simulate_recommendation_outcome",
        lambda **kwargs: {
            "expected_outcome": "positive",
            "expected_impact_score": 0.4,
            "risk_score": 0.2,
            "confidence_score": 0.8,
            "simulation_mode": "historical_heuristic",
            "reasoning": "positive",
            "drivers": [],
            "warnings": [],
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["results"][0]["reason"] == "below_threshold"
    assert result["results"][0]["final_learning_decision"]["decision_class"] == "skip"


def test_run_learning_cycle_defers_uncertain_with_red_flags(tmp_path, monkeypatch):
    """uncertain + low risk but red flag warnings => defer (hardened rule)."""
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "domain_override",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 10},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "evaluate_operational_risk",
        lambda rec: {
            "risk_level": "low",
            "risk_score": 0.12,
            "reversible": True,
            "blast_radius": "small",
            "reasoning": "low risk",
            "drivers": ["additive_change"],
        },
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "simulate_recommendation_outcome",
        lambda **kwargs: {
            "expected_outcome": "uncertain",
            "expected_impact_score": 0.05,
            "risk_score": 0.3,
            "confidence_score": 0.35,
            "simulation_mode": "historical_heuristic",
            "reasoning": "uncertain with regression",
            "drivers": ["limited_historical_evidence"],
            "warnings": ["recent_regression", "limited_historical_evidence"],
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 0
    assert result["skipped_count"] == 1
    assert result["results"][0]["final_learning_decision"]["decision_class"] == "defer"
    assert result["results"][0]["final_learning_decision"]["reasoning"] == "defer_uncertain_simulation"


def test_run_learning_cycle_defers_uncertain_with_very_low_confidence(tmp_path, monkeypatch):
    """uncertain + low risk + confidence < 0.20 => defer even without red flags."""
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "domain_override",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 10},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "evaluate_operational_risk",
        lambda rec: {
            "risk_level": "low",
            "risk_score": 0.12,
            "reversible": True,
            "blast_radius": "small",
            "reasoning": "low risk",
            "drivers": ["additive_change"],
        },
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "simulate_recommendation_outcome",
        lambda **kwargs: {
            "expected_outcome": "uncertain",
            "expected_impact_score": 0.0,
            "risk_score": 0.3,
            "confidence_score": 0.10,
            "simulation_mode": "historical_heuristic",
            "reasoning": "uncertain extremely low confidence",
            "drivers": ["limited_historical_evidence"],
            "warnings": ["limited_historical_evidence"],
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 0
    assert result["skipped_count"] == 1
    assert result["results"][0]["final_learning_decision"]["decision_class"] == "defer"


def test_run_learning_cycle_applies_uncertain_with_sufficient_confidence(tmp_path, monkeypatch):
    """uncertain + low risk + sufficient simulation confidence => apply prudently."""
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "domain_override",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 10},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "evaluate_operational_risk",
        lambda rec: {
            "risk_level": "low",
            "risk_score": 0.12,
            "reversible": True,
            "blast_radius": "small",
            "reasoning": "low risk",
            "drivers": ["additive_change"],
        },
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "simulate_recommendation_outcome",
        lambda **kwargs: {
            "expected_outcome": "uncertain",
            "expected_impact_score": 0.05,
            "risk_score": 0.3,
            "confidence_score": 0.45,
            "simulation_mode": "historical_heuristic",
            "reasoning": "uncertain but reasonable confidence",
            "drivers": [],
            "warnings": [],
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 1
    assert result["results"][0]["applied"] is True
    assert result["results"][0]["final_learning_decision"]["decision_class"] == "apply"


def test_run_learning_cycle_handles_missing_fields_without_crashing(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "domain_override",
        "confidence_score": 0.8,
        "priority": 0.8,
        "evidence": {"sample_size": 9},
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        lambda _db, last_hours=24: {"total_queries": 10},
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "get_recent_learning_logs",
        lambda _db, limit=200: [],
    )
    monkeypatch.setattr(
        learning_cycle_service.AdaptiveLearningEngine,
        "analyze",
        lambda self, summary, recent_logs: [recommendation],
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["total_recommendations"] == 1
    assert "final_learning_decision" in result["results"][0]


def test_run_learning_cycle_respects_max_changes_and_ranking_order(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendations = [
        {
            "title": "third",
            "event_type": "domain_override",
            "confidence_score": 0.9,
            "priority": 0.8,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
        },
        {
            "title": "first",
            "event_type": "domain_override",
            "confidence_score": 0.95,
            "priority": 0.95,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["familia"]},
        },
        {
            "title": "second",
            "event_type": "domain_override",
            "confidence_score": 0.92,
            "priority": 0.9,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["civil"]},
        },
    ]

    monkeypatch.setattr(learning_cycle_service, "get_learning_summary", lambda _db, last_hours=24: {"total_queries": 10})
    monkeypatch.setattr(learning_cycle_service, "get_recent_learning_logs", lambda _db, limit=200: [])
    monkeypatch.setattr(learning_cycle_service.AdaptiveLearningEngine, "analyze", lambda self, summary, recent_logs: recommendations)
    monkeypatch.setattr(
        learning_cycle_service,
        "resolve_change_budget",
        lambda **kwargs: {
            "mode": "restricted",
            "max_changes": 2,
            "max_high_risk_changes": 0,
            "reasoning": "test budget",
        },
    )

    scores = {
        "first": 0.9,
        "second": 0.6,
        "third": 0.2,
    }

    monkeypatch.setattr(
        learning_cycle_service,
        "simulate_recommendation_outcome",
        lambda **kwargs: {
            "expected_outcome": "positive",
            "expected_impact_score": scores[kwargs["recommendation"]["title"]],
            "risk_score": 0.1,
            "confidence_score": 0.8,
            "simulation_mode": "historical_heuristic",
            "reasoning": "positive",
            "drivers": [],
            "warnings": [],
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 2
    assert result["skipped_count"] == 1
    assert result["budget_context"]["max_changes"] == 2
    assert result["budget_context"]["reasoning"] == "test budget"
    assert result["results"][0]["recommendation"]["title"] == "first"
    assert result["results"][0]["applied"] is True
    assert result["results"][1]["recommendation"]["title"] == "second"
    assert result["results"][1]["applied"] is True
    assert result["results"][2]["recommendation"]["title"] == "third"
    assert result["results"][2]["applied"] is False
    assert result["results"][2]["reason"] == "change_budget_max_changes_reached"


def test_run_learning_cycle_respects_high_risk_budget(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendations = [
        {
            "title": "high-one",
            "event_type": "domain_override",
            "confidence_score": 0.95,
            "priority": 0.95,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
        },
        {
            "title": "high-two",
            "event_type": "domain_override",
            "confidence_score": 0.94,
            "priority": 0.94,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["familia"]},
        },
    ]

    monkeypatch.setattr(learning_cycle_service, "get_learning_summary", lambda _db, last_hours=24: {"total_queries": 10})
    monkeypatch.setattr(learning_cycle_service, "get_recent_learning_logs", lambda _db, limit=200: [])
    monkeypatch.setattr(learning_cycle_service.AdaptiveLearningEngine, "analyze", lambda self, summary, recent_logs: recommendations)
    monkeypatch.setattr(
        learning_cycle_service,
        "resolve_change_budget",
        lambda **kwargs: {
            "mode": "normal",
            "max_changes": 3,
            "max_high_risk_changes": 1,
            "reasoning": "test high risk budget",
        },
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "simulate_recommendation_outcome",
        lambda **kwargs: {
            "expected_outcome": "positive",
            "expected_impact_score": 0.7,
            "risk_score": 0.2,
            "confidence_score": 0.8,
            "simulation_mode": "historical_heuristic",
            "reasoning": "positive",
            "drivers": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "evaluate_operational_risk",
        lambda rec: {
            "risk_level": "high",
            "risk_score": 0.8,
            "reversible": False,
            "blast_radius": "large",
            "reasoning": "high",
            "drivers": ["sensitive_config_change"],
        },
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "_resolve_final_learning_decision",
        lambda **kwargs: {
            "should_apply": True,
            "decision_class": "apply",
            "reasoning": "forced_apply_for_budget_test",
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["applied_count"] == 1
    assert result["skipped_count"] == 1
    assert result["results"][1]["applied"] is False
    assert result["results"][1]["reason"] == "change_budget_high_risk_limit_reached"
    assert result["results"][1]["final_learning_decision"]["decision_class"] == "apply"
    assert result["results"][1]["budget_override"]["override_applied"] is True
    assert result["results"][1]["budget_override"]["reason"] == "change_budget_high_risk_limit_reached"
    assert result["results"][1]["budget_override"]["effective_decision_class"] == "skip"


def test_run_learning_cycle_budget_override_preserves_original_decision(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendations = [
        {
            "title": "first",
            "event_type": "domain_override",
            "confidence_score": 0.95,
            "priority": 0.95,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
        },
        {
            "title": "second",
            "event_type": "domain_override",
            "confidence_score": 0.94,
            "priority": 0.94,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["familia"]},
        },
    ]

    monkeypatch.setattr(learning_cycle_service, "get_learning_summary", lambda _db, last_hours=24: {"total_queries": 10})
    monkeypatch.setattr(learning_cycle_service, "get_recent_learning_logs", lambda _db, limit=200: [])
    monkeypatch.setattr(learning_cycle_service.AdaptiveLearningEngine, "analyze", lambda self, summary, recent_logs: recommendations)
    monkeypatch.setattr(
        learning_cycle_service,
        "resolve_change_budget",
        lambda **kwargs: {
            "mode": "protective",
            "max_changes": 1,
            "max_high_risk_changes": 1,
            "reasoning": "forced budget",
        },
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "_resolve_final_learning_decision",
        lambda **kwargs: {
            "should_apply": True,
            "decision_class": "apply",
            "reasoning": "original_apply",
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    skipped_item = result["results"][1]
    assert skipped_item["applied"] is False
    assert skipped_item["final_learning_decision"]["decision_class"] == "apply"
    assert skipped_item["budget_override"]["override_applied"] is True
    assert skipped_item["budget_override"]["original_final_learning_decision"]["decision_class"] == "apply"
    payload = json.loads(
        db.query(LearningActionLog)
        .filter(LearningActionLog.recommendation_type == "second")
        .first()
        .changes_applied_json
    )
    assert payload["final_learning_decision"]["decision_class"] == "apply"
    assert payload["budget_override"]["override_applied"] is True
    assert payload["budget_override"]["effective_decision_class"] == "skip"


def test_run_learning_cycle_budget_uses_apply_candidates_not_all_recommendations(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendations = [
        {
            "title": "apply-one",
            "event_type": "domain_override",
            "confidence_score": 0.95,
            "priority": 0.95,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
        },
        {
            "title": "apply-two",
            "event_type": "domain_override",
            "confidence_score": 0.94,
            "priority": 0.94,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["familia"]},
        },
        {
            "title": "defer-one",
            "event_type": "domain_override",
            "confidence_score": 0.93,
            "priority": 0.93,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["civil"]},
        },
        {
            "title": "skip-one",
            "event_type": "domain_override",
            "confidence_score": 0.92,
            "priority": 0.92,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["laboral"]},
        },
    ]

    monkeypatch.setattr(learning_cycle_service, "get_learning_summary", lambda _db, last_hours=24: {"total_queries": 10})
    monkeypatch.setattr(learning_cycle_service, "get_recent_learning_logs", lambda _db, limit=200: [])
    monkeypatch.setattr(learning_cycle_service.AdaptiveLearningEngine, "analyze", lambda self, summary, recent_logs: recommendations)

    decision_map = {
        "apply-one": {"should_apply": True, "decision_class": "apply", "reasoning": "apply"},
        "apply-two": {"should_apply": True, "decision_class": "apply", "reasoning": "apply"},
        "defer-one": {"should_apply": False, "decision_class": "defer", "reasoning": "defer"},
        "skip-one": {"should_apply": False, "decision_class": "skip", "reasoning": "skip"},
    }
    monkeypatch.setattr(
        learning_cycle_service,
        "_resolve_final_learning_decision",
        lambda **kwargs: decision_map[kwargs["simulation_result"]["reasoning"]],
    )
    monkeypatch.setattr(
        learning_cycle_service,
        "simulate_recommendation_outcome",
        lambda **kwargs: {
            "expected_outcome": "positive",
            "expected_impact_score": 0.6,
            "risk_score": 0.2,
            "confidence_score": 0.8,
            "simulation_mode": "historical_heuristic",
            "reasoning": kwargs["recommendation"]["title"],
            "drivers": [],
            "warnings": [],
        },
    )

    result = learning_cycle_service.run_learning_cycle(db)

    assert result["budget_context"]["max_changes"] == 2
    assert "candidate_apply_count=2" in result["budget_context"]["reasoning"]


def test_run_learning_cycle_persists_ranking_and_budget_context(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "title": "persisted",
        "event_type": "domain_override",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 10},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }

    monkeypatch.setattr(learning_cycle_service, "get_learning_summary", lambda _db, last_hours=24: {"total_queries": 10})
    monkeypatch.setattr(learning_cycle_service, "get_recent_learning_logs", lambda _db, limit=200: [])
    monkeypatch.setattr(learning_cycle_service.AdaptiveLearningEngine, "analyze", lambda self, summary, recent_logs: [recommendation])

    result = learning_cycle_service.run_learning_cycle(db)

    payload = json.loads(db.query(LearningActionLog).first().changes_applied_json)
    assert payload["ranking_score"] == result["results"][0]["ranking_score"]
    assert payload["rank_position"] == 1
    assert payload["budget_context"]["mode"] == result["budget_context"]["mode"]
