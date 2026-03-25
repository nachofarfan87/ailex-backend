from __future__ import annotations

from datetime import datetime, timedelta

from app.services.utc import utc_now
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_action_log  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_log  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.models.learning_log import LearningLog
from app.services import learning_cycle_service, learning_impact_service, learning_runtime_config


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning_impact.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _create_learning_log(
    db: Session,
    *,
    created_at: datetime,
    fallback_used: bool,
    confidence_score: float,
    decision_confidence: float,
    success_signal: bool | None = None,
    negative_signal: bool | None = None,
) -> LearningLog:
    quality_flags_json = "{}"
    has_feedback = success_signal is not None or negative_signal is not None
    if has_feedback:
        quality_flags_json = (
            '{"review_feedback":{"feedback_is_positive_confirmation":%s,"feedback_is_negative":%s}}'
            % (
                "true" if bool(success_signal) else "false",
                "true" if bool(negative_signal) else "false",
            )
        )

    log = LearningLog(
        request_id=f"req-{created_at.timestamp()}-{confidence_score}",
        query="consulta",
        jurisdiction="jujuy",
        forum="familia",
        case_domain="alimentos",
        retrieval_mode="offline",
        strategy_mode="conservative",
        pipeline_mode="full",
        decision_confidence=decision_confidence,
        confidence_score=confidence_score,
        fallback_used=fallback_used,
        processing_time_ms=100,
        quality_flags_json=quality_flags_json,
        reviewed_by_user=has_feedback,
        user_feedback_score=5 if success_signal else (1 if negative_signal else None),
        is_user_feedback_positive=True if success_signal else (False if negative_signal else None),
        feedback_submitted_at=created_at if has_feedback else None,
        created_at=created_at,
    )
    db.add(log)
    return log


def _create_action(
    db: Session,
    *,
    applied: bool,
    applied_at: datetime | None = None,
    impact_status: str | None = None,
) -> LearningActionLog:
    action = LearningActionLog(
        event_type="domain_override",
        recommendation_type="test-action",
        applied=applied,
        reason="applied_domain_override" if applied else "below_threshold",
        confidence_score=0.9,
        priority=0.8,
        evidence_json="{}",
        changes_applied_json="{}",
        applied_at=applied_at,
        impact_status=impact_status,
    )
    db.add(action)
    db.commit()
    return action


def test_evaluate_learning_action_impact_fails_if_action_missing(tmp_path):
    db = _build_session(tmp_path)

    try:
        learning_impact_service.evaluate_learning_action_impact(db, "missing-id")
        assert False, "Se esperaba ValueError"
    except ValueError as exc:
        assert str(exc) == "learning_action_log_not_found"


def test_evaluate_learning_action_impact_fails_if_action_not_applied(tmp_path):
    db = _build_session(tmp_path)
    action = _create_action(db, applied=False)

    try:
        learning_impact_service.evaluate_learning_action_impact(db, action.id)
        assert False, "Se esperaba ValueError"
    except ValueError as exc:
        assert str(exc) == "learning_action_not_applied"


def test_evaluate_learning_action_impact_returns_insufficient_data_when_windows_are_small(tmp_path):
    db = _build_session(tmp_path)
    applied_at = utc_now()
    action = _create_action(db, applied=True, applied_at=applied_at, impact_status="pending")

    _create_learning_log(
        db,
        created_at=applied_at - timedelta(hours=1),
        fallback_used=True,
        confidence_score=0.4,
        decision_confidence=0.4,
    )
    _create_learning_log(
        db,
        created_at=applied_at + timedelta(hours=1),
        fallback_used=False,
        confidence_score=0.8,
        decision_confidence=0.8,
    )
    db.commit()

    result = learning_impact_service.evaluate_learning_action_impact(db, action.id, window_hours=24)

    assert result["status"] == "insufficient_data"
    refreshed = db.get(LearningActionLog, action.id)
    assert refreshed is not None
    assert refreshed.impact_status == "insufficient_data"


def test_evaluate_learning_action_impact_classifies_improved(tmp_path):
    db = _build_session(tmp_path)
    applied_at = utc_now()
    action = _create_action(db, applied=True, applied_at=applied_at, impact_status="pending")

    for idx in range(4):
        _create_learning_log(
            db,
            created_at=applied_at - timedelta(hours=8) + timedelta(minutes=idx),
            fallback_used=True,
            confidence_score=0.4,
            decision_confidence=0.4,
            success_signal=False,
            negative_signal=True,
        )
    for idx in range(4):
        _create_learning_log(
            db,
            created_at=applied_at + timedelta(hours=8) + timedelta(minutes=idx),
            fallback_used=False,
            confidence_score=0.85,
            decision_confidence=0.82,
            success_signal=True,
            negative_signal=False,
        )
    db.commit()

    result = learning_impact_service.evaluate_learning_action_impact(db, action.id, window_hours=24)

    assert result["status"] == "improved"
    assert result["delta_metrics_json"]["fallback_rate"] <= -0.05
    assert result["delta_metrics_json"]["average_confidence"] >= 0.05


def test_evaluate_learning_action_impact_classifies_regressed(tmp_path):
    db = _build_session(tmp_path)
    applied_at = utc_now()
    action = _create_action(db, applied=True, applied_at=applied_at, impact_status="pending")

    for idx in range(4):
        _create_learning_log(
            db,
            created_at=applied_at - timedelta(hours=8) + timedelta(minutes=idx),
            fallback_used=False,
            confidence_score=0.85,
            decision_confidence=0.82,
            success_signal=True,
            negative_signal=False,
        )
    for idx in range(4):
        _create_learning_log(
            db,
            created_at=applied_at + timedelta(hours=8) + timedelta(minutes=idx),
            fallback_used=True,
            confidence_score=0.4,
            decision_confidence=0.4,
            success_signal=False,
            negative_signal=True,
        )
    db.commit()

    result = learning_impact_service.evaluate_learning_action_impact(db, action.id, window_hours=24)

    assert result["status"] == "regressed"
    assert result["delta_metrics_json"]["fallback_rate"] >= 0.05
    assert result["delta_metrics_json"]["average_confidence"] <= -0.05


def test_evaluate_learning_action_impact_classifies_neutral(tmp_path):
    db = _build_session(tmp_path)
    applied_at = utc_now()
    action = _create_action(db, applied=True, applied_at=applied_at, impact_status="pending")

    for idx in range(4):
        _create_learning_log(
            db,
            created_at=applied_at - timedelta(hours=8) + timedelta(minutes=idx),
            fallback_used=False,
            confidence_score=0.7,
            decision_confidence=0.7,
        )
    for idx in range(4):
        _create_learning_log(
            db,
            created_at=applied_at + timedelta(hours=8) + timedelta(minutes=idx),
            fallback_used=False,
            confidence_score=0.72,
            decision_confidence=0.71,
        )
    db.commit()

    result = learning_impact_service.evaluate_learning_action_impact(db, action.id, window_hours=24)

    assert result["status"] == "neutral"


def test_get_impact_summary_aggregates_statuses(tmp_path):
    db = _build_session(tmp_path)
    db.add(
        LearningImpactLog(
            learning_action_log_id="a1",
            event_type="domain_override",
            status="improved",
            before_metrics_json="{}",
            after_metrics_json="{}",
            delta_metrics_json="{}",
            evaluation_window_hours=24,
        )
    )
    db.add(
        LearningImpactLog(
            learning_action_log_id="a2",
            event_type="domain_override",
            status="regressed",
            before_metrics_json="{}",
            after_metrics_json="{}",
            delta_metrics_json="{}",
            evaluation_window_hours=24,
        )
    )
    db.add(
        LearningImpactLog(
            learning_action_log_id="a3",
            event_type="domain_override",
            status="neutral",
            before_metrics_json="{}",
            after_metrics_json="{}",
            delta_metrics_json="{}",
            evaluation_window_hours=24,
        )
    )
    db.add(
        LearningImpactLog(
            learning_action_log_id="a4",
            event_type="domain_override",
            status="insufficient_data",
            before_metrics_json="{}",
            after_metrics_json="{}",
            delta_metrics_json="{}",
            evaluation_window_hours=24,
        )
    )
    db.commit()

    summary = learning_impact_service.get_impact_summary(db)

    assert summary == {
        "total_evaluated": 4,
        "improved": 1,
        "regressed": 1,
        "neutral": 1,
        "insufficient_data": 1,
        "improvement_rate": 0.25,
        "regression_rate": 0.25,
    }


def test_learning_cycle_marks_applied_action_as_pending_with_applied_at(tmp_path, monkeypatch):
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
    action_log = db.query(LearningActionLog).order_by(LearningActionLog.created_at.desc()).first()

    assert result["applied_count"] == 1
    assert action_log is not None
    assert action_log.applied_at is not None
    assert action_log.impact_status == "pending"
