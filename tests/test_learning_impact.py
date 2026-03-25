from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_action_log  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_log  # noqa: F401
from app.models.learning_impact_log import LearningImpactLog
from app.services import learning_cycle_service, learning_runtime_config
from app.services.impact_evaluator import evaluate_impact


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning_impact_simple.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def test_evaluate_impact_improved():
    result = evaluate_impact(
        {
            "fallback_rate": 0.5,
            "avg_confidence": 0.4,
            "success_rate": 0.2,
        },
        {
            "fallback_rate": 0.2,
            "avg_confidence": 0.7,
            "success_rate": 0.6,
        },
    )

    assert result == {
        "impact_score": 1.0,
        "impact_label": "improved",
    }


def test_evaluate_impact_regressed():
    result = evaluate_impact(
        {
            "fallback_rate": 0.1,
            "avg_confidence": 0.8,
            "success_rate": 0.7,
        },
        {
            "fallback_rate": 0.4,
            "avg_confidence": 0.5,
            "success_rate": 0.2,
        },
    )

    assert result == {
        "impact_score": -1.0,
        "impact_label": "regressed",
    }


def test_evaluate_impact_neutral():
    result = evaluate_impact(
        {
            "fallback_rate": 0.2,
            "avg_confidence": 0.5,
            "success_rate": 0.4,
        },
        {
            "fallback_rate": 0.2,
            "avg_confidence": 0.5,
            "success_rate": 0.4,
        },
    )

    assert result == {
        "impact_score": 0.0,
        "impact_label": "neutral",
    }


def test_learning_cycle_persists_batch_impact_log(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    learning_runtime_config.reset_runtime_config()

    recommendation = {
        "event_type": "domain_override",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 10},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }

    summaries = [
        {
            "total_queries": 10,
            "fallback_rate": 0.4,
            "average_confidence": 0.5,
            "feedback_summary": {"success_rate": 0.3},
        },
        {
            "total_queries": 10,
            "fallback_rate": 0.4,
            "average_confidence": 0.5,
            "feedback_summary": {"success_rate": 0.3},
        },
        {
            "total_queries": 10,
            "fallback_rate": 0.2,
            "average_confidence": 0.7,
            "feedback_summary": {"success_rate": 0.6},
        },
    ]

    def _next_summary(_db, last_hours=24):
        return summaries.pop(0)

    monkeypatch.setattr(
        learning_cycle_service,
        "get_learning_summary",
        _next_summary,
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
    impact_log = db.query(LearningImpactLog).order_by(LearningImpactLog.created_at.desc()).first()

    assert result["applied_count"] == 1
    assert impact_log is not None
    assert impact_log.action_log_id == "batch"
    assert impact_log.impact_label == "improved"
    assert impact_log.impact_score == 1.0
