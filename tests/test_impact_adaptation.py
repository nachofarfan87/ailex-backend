from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_action_log  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_log  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.services import learning_cycle_service, learning_runtime_config
from app.services.impact_memory_service import (
    SIGNATURE_METADATA_VERSION,
    build_impact_signature,
    build_impact_signature_family,
    extract_persisted_impact_metadata,
    get_impact_by_event_type,
    get_impact_by_signature,
    get_impact_by_signature_family,
)
from app.services.learning_adaptation_policy import evaluate_impact_adaptation


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'impact_adaptation.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _threshold_recommendation(**overrides) -> dict:
    recommendation = {
        "event_type": "threshold_adjustment",
        "title": "Adjust thresholds",
        "confidence_score": 0.7,
        "priority": 0.8,
        "evidence": {"sample_size": 12},
        "proposed_changes": {
            "threshold_review": {
                "low_confidence_threshold": 0.55,
            }
        },
    }
    recommendation.update(overrides)
    return recommendation


def _domain_recommendation(**overrides) -> dict:
    recommendation = {
        "event_type": "domain_override",
        "title": "Prefer alimentos",
        "confidence_score": 0.9,
        "priority": 0.8,
        "evidence": {"sample_size": 15},
        "proposed_changes": {
            "prefer_hybrid_domains_add": ["alimentos"],
        },
    }
    recommendation.update(overrides)
    return recommendation


def _add_impact_entry(
    db: Session,
    *,
    recommendation: dict,
    status: str,
    created_at: datetime,
    metadata: dict | None = None,
) -> None:
    payload = {
        "impact_metadata_version": SIGNATURE_METADATA_VERSION,
        "impact_signature": build_impact_signature(recommendation),
        "impact_signature_family": build_impact_signature_family(recommendation),
    }
    payload.update(metadata or {})
    action_log = LearningActionLog(
        event_type=str(recommendation.get("event_type") or ""),
        recommendation_type="historical",
        applied=True,
        reason="historical",
        confidence_score=float(recommendation.get("confidence_score") or 0.0),
        priority=float(recommendation.get("priority") or 0.0),
        evidence_json="{}",
        changes_applied_json=json.dumps(payload),
        impact_status=status,
        created_at=created_at,
    )
    db.add(action_log)
    db.flush()
    db.add(
        LearningImpactLog(
            learning_action_log_id=action_log.id,
            event_type=str(recommendation.get("event_type") or ""),
            status=status,
            before_metrics_json="{}",
            after_metrics_json="{}",
            delta_metrics_json="{}",
            evaluation_window_hours=24,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def _add_event_only_impact(
    db: Session,
    *,
    event_type: str,
    status: str,
    created_at: datetime,
) -> None:
    db.add(
        LearningImpactLog(
            learning_action_log_id=f"event-{status}-{created_at.timestamp()}",
            event_type=event_type,
            status=status,
            before_metrics_json="{}",
            after_metrics_json="{}",
            delta_metrics_json="{}",
            evaluation_window_hours=24,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def _memory_entry(
    *,
    score: float,
    raw_total: int,
    weighted_total: float,
    improved: int = 0,
    regressed: int = 0,
    neutral: int = 0,
    scope: str = "signature",
    family: str = "test",
) -> dict:
    return {
        "improved": improved,
        "regressed": regressed,
        "neutral": neutral,
        "raw_total": raw_total,
        "weighted_improved": float(improved),
        "weighted_regressed": float(regressed),
        "weighted_neutral": float(neutral),
        "weighted_total": float(weighted_total),
        "score": float(score),
        "scope": scope,
        "family": family,
        "dominant_signal": "improved" if score > 0 else ("regressed" if score < 0 else "neutral"),
        "latest_seen_at": "2026-03-23T00:00:00",
        "oldest_seen_at": "2026-03-01T00:00:00",
        "temporal_decay": {
            "strategy": "exponential_half_life",
            "half_life_days": 30.0,
            "reference_time": "2026-03-23T00:00:00",
        },
    }


def test_aggregation_by_signature_family(tmp_path):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 23, 12, 0, 0)
    recommendation = _threshold_recommendation()
    _add_impact_entry(db, recommendation=recommendation, status="improved", created_at=now - timedelta(days=2))
    _add_impact_entry(db, recommendation=recommendation, status="regressed", created_at=now - timedelta(days=1))
    db.commit()

    memory = get_impact_by_signature_family(db, reference_time=now)

    assert memory["threshold_adjustment:thresholds"]["raw_total"] == 2
    assert memory["threshold_adjustment:thresholds"]["family"] == "threshold_adjustment:thresholds"


def test_fallback_signature_to_family_to_event_type(tmp_path):
    recommendation = _threshold_recommendation()
    decision = evaluate_impact_adaptation(
        recommendation,
        impact_memory={},
        signature_memory={},
        family_memory={
            "threshold_adjustment:thresholds": _memory_entry(
                score=-0.6,
                raw_total=4,
                weighted_total=3.2,
                regressed=3,
                neutral=1,
                scope="signature_family",
                family="threshold_adjustment:thresholds",
            )
        },
    )

    assert decision["should_apply"] is False
    assert decision["decision_level"] == "signature_family"
    assert decision["reason"] == "blocked_by_negative_signature_family_impact"


def test_negative_family_signal_blocks(tmp_path):
    recommendation = _threshold_recommendation()
    decision = evaluate_impact_adaptation(
        recommendation,
        impact_memory={},
        signature_memory={},
        family_memory={
            "threshold_adjustment:thresholds": _memory_entry(
                score=-0.7,
                raw_total=5,
                weighted_total=4.1,
                regressed=4,
                neutral=1,
                scope="signature_family",
                family="threshold_adjustment:thresholds",
            )
        },
    )

    assert decision["should_apply"] is False
    assert decision["reason"] == "blocked_by_negative_signature_family_impact"


def test_positive_family_signal_boosts(tmp_path):
    recommendation = _threshold_recommendation()
    decision = evaluate_impact_adaptation(
        recommendation,
        impact_memory={},
        signature_memory={},
        family_memory={
            "threshold_adjustment:thresholds": _memory_entry(
                score=0.8,
                raw_total=5,
                weighted_total=4.0,
                improved=4,
                neutral=1,
                scope="signature_family",
                family="threshold_adjustment:thresholds",
            )
        },
    )

    assert decision["should_apply"] is True
    assert decision["decision_level"] == "signature_family"
    assert decision["reason"] == "boosted_by_positive_signature_family_impact"


def test_temporal_decay_favors_recent_events(tmp_path):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 23, 12, 0, 0)
    recommendation = _domain_recommendation()
    _add_impact_entry(db, recommendation=recommendation, status="improved", created_at=now - timedelta(days=120))
    _add_impact_entry(db, recommendation=recommendation, status="regressed", created_at=now - timedelta(days=2))
    db.commit()

    memory = get_impact_by_signature(db, reference_time=now)
    entry = memory["domain_override:prefer_hybrid:alimentos"]

    assert entry["weighted_regressed"] > entry["weighted_improved"]
    assert entry["score"] < 0


def test_old_history_weighs_less_than_recent_history(tmp_path):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 23, 12, 0, 0)
    recommendation = _domain_recommendation()
    _add_impact_entry(db, recommendation=recommendation, status="improved", created_at=now - timedelta(days=90))
    _add_impact_entry(db, recommendation=recommendation, status="improved", created_at=now - timedelta(days=1))
    db.commit()

    memory = get_impact_by_signature(db, reference_time=now)
    entry = memory["domain_override:prefer_hybrid:alimentos"]

    assert entry["weighted_total"] < entry["raw_total"]
    assert entry["latest_seen_at"] > entry["oldest_seen_at"]


def test_insufficient_evidence_does_not_overadjust():
    recommendation = _threshold_recommendation()
    decision = evaluate_impact_adaptation(
        recommendation,
        impact_memory={},
        signature_memory={
            "threshold_adjustment:low_confidence": _memory_entry(
                score=-1.0,
                raw_total=1,
                weighted_total=0.5,
                regressed=1,
                scope="signature",
                family="threshold_adjustment:thresholds",
            )
        },
        family_memory={
            "threshold_adjustment:thresholds": _memory_entry(
                score=-0.2,
                raw_total=1,
                weighted_total=0.4,
                regressed=1,
                scope="signature_family",
                family="threshold_adjustment:thresholds",
            )
        },
    )

    assert decision["should_apply"] is True
    assert decision["reason"] == "observed_insufficient_hierarchical_evidence"
    assert decision["decision_mode"] == "observed"


def test_conflict_between_levels_is_resolved_consistently():
    recommendation = _threshold_recommendation()
    decision = evaluate_impact_adaptation(
        recommendation,
        impact_memory={
            "threshold_adjustment": _memory_entry(
                score=-0.6,
                raw_total=5,
                weighted_total=4.0,
                regressed=4,
                neutral=1,
                scope="event_type",
                family="threshold_adjustment",
            )
        },
        signature_memory={
            "threshold_adjustment:low_confidence": _memory_entry(
                score=0.8,
                raw_total=4,
                weighted_total=3.5,
                improved=3,
                neutral=1,
                scope="signature",
                family="threshold_adjustment:thresholds",
            )
        },
        family_memory={
            "threshold_adjustment:thresholds": _memory_entry(
                score=-0.5,
                raw_total=4,
                weighted_total=3.1,
                regressed=3,
                neutral=1,
                scope="signature_family",
                family="threshold_adjustment:thresholds",
            )
        },
    )

    assert decision["should_apply"] is True
    assert decision["decision_level"] == "signature"
    assert decision["conflict_summary"]["has_conflict"] is True
    assert {item["level"] for item in decision["conflict_summary"]["conflicts"]} == {
        "signature_family",
        "event_type",
    }


def test_persistence_of_level_source_reason_and_evidence(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 23, 12, 0, 0)
    learning_runtime_config.reset_runtime_config()
    recommendation = _threshold_recommendation()
    family_recommendation = _threshold_recommendation(
        proposed_changes={"threshold_review": {"low_decision_confidence_threshold": 0.65}}
    )
    _add_impact_entry(db, recommendation=family_recommendation, status="improved", created_at=now - timedelta(days=2))
    _add_impact_entry(db, recommendation=family_recommendation, status="improved", created_at=now - timedelta(days=1))
    _add_impact_entry(db, recommendation=family_recommendation, status="neutral", created_at=now - timedelta(hours=12))
    db.commit()

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
    payload = json.loads(action_log.changes_applied_json)

    assert result["applied_count"] == 1
    assert payload["impact_decision_level"] == "signature_family"
    assert payload["impact_decision_source"] == "signature_family"
    assert payload["impact_decision_reason"] == "boosted_by_positive_signature_family_impact"
    assert payload["impact_score_reference"]["signature_family_evidence"]["raw_total"] == 3
    assert payload["impact_score_reference"]["temporal_weighting"]["strategy"] == "exponential_half_life"


def test_system_is_deterministic_for_same_inputs(tmp_path):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 23, 12, 0, 0)
    recommendation = _domain_recommendation(
        proposed_changes={"prefer_hybrid_domains_add": [" ALIMENTOS ", "alimentos"]}
    )
    _add_impact_entry(db, recommendation=recommendation, status="improved", created_at=now - timedelta(days=2))
    db.commit()

    first_signature = build_impact_signature(recommendation)
    second_signature = build_impact_signature(recommendation)
    first_memory = get_impact_by_signature(db, reference_time=now)
    second_memory = get_impact_by_signature(db, reference_time=now)

    assert first_signature == second_signature == "domain_override:prefer_hybrid:alimentos"
    assert first_memory == second_memory


def test_legacy_metadata_does_not_break_new_aggregation(tmp_path):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 23, 12, 0, 0)
    recommendation = _threshold_recommendation()
    _add_impact_entry(
        db,
        recommendation=recommendation,
        status="improved",
        created_at=now - timedelta(days=1),
        metadata={"impact_signature": "", "impact_signature_family": ""},
    )
    db.commit()

    family_memory = get_impact_by_signature_family(db, reference_time=now)
    signature_memory = get_impact_by_signature(db, reference_time=now)
    action_log = db.query(LearningActionLog).order_by(LearningActionLog.created_at.desc()).first()
    metadata = extract_persisted_impact_metadata(action_log, fallback_event_type="threshold_adjustment")

    assert metadata["impact_signature"] == "threshold_adjustment"
    assert family_memory["threshold_adjustment"]["raw_total"] == 1
    assert signature_memory["threshold_adjustment"]["raw_total"] == 1


def test_behavior_stays_compatible_when_family_data_is_not_useful(tmp_path):
    recommendation = _threshold_recommendation()
    decision = evaluate_impact_adaptation(
        recommendation,
        impact_memory={
            "threshold_adjustment": _memory_entry(
                score=-0.7,
                raw_total=3,
                weighted_total=2.4,
                regressed=3,
                scope="event_type",
                family="threshold_adjustment",
            )
        },
        signature_memory={},
        family_memory={
            "threshold_adjustment:thresholds": _memory_entry(
                score=-0.1,
                raw_total=1,
                weighted_total=0.4,
                regressed=1,
                scope="signature_family",
                family="threshold_adjustment:thresholds",
            )
        },
    )

    assert decision["should_apply"] is False
    assert decision["decision_level"] == "event_type"
    assert decision["reason"] == "blocked_by_negative_impact"
