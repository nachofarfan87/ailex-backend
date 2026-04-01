from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.auto_healing_event  # noqa: F401
import app.models.learning_action_log  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_review  # noqa: F401
import app.models.system_safety_event  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.services import baseline_service, drift_policy, live_alert_policy, live_alert_service, priority_engine
from app.services.impact_memory_service import (
    SIGNATURE_METADATA_VERSION,
    build_impact_signature,
    build_impact_signature_family,
)


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'baseline_drift_priority.db'}",
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
        "confidence_score": 0.75,
        "priority": 0.8,
        "evidence": {"sample_size": 12},
        "proposed_changes": {"threshold_review": {"low_confidence_threshold": 0.55}},
    }
    recommendation.update(overrides)
    return recommendation


def _domain_recommendation(**overrides) -> dict:
    recommendation = {
        "event_type": "domain_override",
        "title": "Prefer alimentos",
        "confidence_score": 0.85,
        "priority": 0.8,
        "evidence": {"sample_size": 15},
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }
    recommendation.update(overrides)
    return recommendation


def _add_impact_entry(
    db: Session,
    *,
    recommendation: dict,
    status: str,
    created_at: datetime,
    applied: bool = True,
    confidence_score: float | None = None,
    reason: str = "historical",
) -> None:
    sig = build_impact_signature(recommendation)
    fam = build_impact_signature_family(recommendation)
    payload = {
        "impact_metadata_version": SIGNATURE_METADATA_VERSION,
        "impact_signature": sig,
        "impact_signature_family": fam,
        "impact_decision_level": "signature",
        "impact_decision_reason": reason,
        "impact_decision_source": "signature",
        "output_mode": recommendation.get("output_mode"),
    }
    action_log = LearningActionLog(
        event_type=recommendation["event_type"],
        recommendation_type=recommendation.get("title"),
        applied=applied,
        reason=reason,
        confidence_score=confidence_score if confidence_score is not None else recommendation.get("confidence_score"),
        priority=recommendation.get("priority"),
        evidence_json=json.dumps(recommendation.get("evidence", {})),
        changes_applied_json=json.dumps(payload),
        impact_status=status if applied else None,
        created_at=created_at,
    )
    db.add(action_log)
    db.flush()
    db.add(
        LearningImpactLog(
            learning_action_log_id=action_log.id,
            event_type=recommendation["event_type"],
            status=status,
            before_metrics_json="{}",
            after_metrics_json="{}",
            delta_metrics_json="{}",
            evaluation_window_hours=24,
            created_at=created_at,
            updated_at=created_at,
            impact_score=0.4 if status == "improved" else (-0.4 if status == "regressed" else 0.0),
            impact_label=status,
        )
    )


def _write_turns(log_path: Path, rows: list[dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _turn(
    *,
    conversation_id: str,
    turn_number: int,
    timestamp: datetime,
    output_mode: str,
    case_domain: str = "divorcio",
    question_asked: str = "",
    progress_delta: int = 0,
    repeat_question: bool = False,
    no_progress: bool = True,
    loop_detected: bool = False,
) -> dict:
    return {
        "conversation_id": conversation_id,
        "turn_number": turn_number,
        "output_mode": output_mode,
        "question_asked": question_asked,
        "case_domain": case_domain,
        "missing_information": ["Hay hijos"] if no_progress else [],
        "facts_detected": {},
        "quick_start": "",
        "timestamp": timestamp.replace(tzinfo=timezone.utc).isoformat(),
        "progress": {
            "previous_count": 0,
            "current_count": progress_delta,
            "new_keys": ["nuevo_fact"] if progress_delta else [],
            "changed_keys": [],
            "delta": progress_delta,
            "has_progress": progress_delta > 0,
        },
        "signals": {
            "repeat_question": repeat_question,
            "no_progress": no_progress,
            "loop_detected": loop_detected,
            "domain_shift": False,
            "unnecessary_clarification": False,
        },
    }


def _neutral_safety_snapshot(*args, **kwargs) -> dict:
    return {
        "total_safety_events": 0,
        "protective_mode_active": False,
        "severity_breakdown": {},
        "fallback_type_breakdown": {},
        "recent_safety_events": [],
        "top_safety_reasons": [],
    }


def _neutral_review_snapshot(*args, **kwargs) -> dict:
    return {
        "review_queue_size": 0,
        "pending_reviews": 0,
        "pending_reviews_by_priority": {"high": 0, "medium": 0, "low": 0},
        "stale_reviews_count": 0,
        "oldest_pending_review_hours": 0.0,
        "approval_rate": 0.0,
        "rejection_rate": 0.0,
        "override_rate": 0.0,
        "recent_human_actions_summary": {},
    }


def _neutral_auto_healing_snapshot(*args, **kwargs) -> dict:
    return {
        "auto_healing_status": "normal",
        "recovery_counter": 0,
        "system_mode_effective": "auto",
        "protective_mode_active": False,
        "recovery_progress": 0.0,
        "total_events_last_24h": 0,
        "applied_actions_count": 0,
        "recommended_actions_count": 0,
        "action_breakdown": {},
        "situation_breakdown": {},
        "recent_auto_healing_events": [],
    }


@pytest.fixture
def fixed_now(monkeypatch):
    now = datetime(2026, 3, 31, 12, 0, 0)
    monkeypatch.setattr(live_alert_service, "utc_now", lambda: now)
    return now


@pytest.fixture
def stable_monitors(monkeypatch):
    monkeypatch.setattr(live_alert_service, "get_safety_snapshot", _neutral_safety_snapshot)
    monkeypatch.setattr(live_alert_service, "_get_previous_safety_snapshot", lambda *args, **kwargs: _neutral_safety_snapshot())
    monkeypatch.setattr(live_alert_service, "get_review_snapshot", _neutral_review_snapshot)
    monkeypatch.setattr(live_alert_service, "get_auto_healing_snapshot", _neutral_auto_healing_snapshot)


def test_baseline_calculates_with_sufficient_history(tmp_path):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 31, 12, 0, 0)
    log_path = tmp_path / "conversations.jsonl"
    recent_start = now - timedelta(hours=6)

    rows = [
        _turn(conversation_id="b1", turn_number=1, timestamp=now - timedelta(days=2, hours=10), output_mode="advice", progress_delta=1, no_progress=False),
        _turn(conversation_id="b2", turn_number=1, timestamp=now - timedelta(days=1, hours=10), output_mode="advice", progress_delta=1, no_progress=False),
        _turn(conversation_id="b3", turn_number=1, timestamp=now - timedelta(hours=20), output_mode="clarification", progress_delta=1, no_progress=False),
        _turn(conversation_id="b4", turn_number=1, timestamp=now - timedelta(hours=18), output_mode="advice", progress_delta=1, no_progress=False),
        _turn(conversation_id="b5", turn_number=1, timestamp=now - timedelta(hours=14), output_mode="advice", progress_delta=1, no_progress=False),
    ]
    _write_turns(log_path, rows)

    for created_at in [now - timedelta(days=2), now - timedelta(days=1, hours=4), now - timedelta(hours=18), now - timedelta(hours=12)]:
        _add_impact_entry(db, recommendation=_threshold_recommendation(), status="improved", created_at=created_at)
    db.commit()

    baseline = baseline_service.build_operational_baseline(
        db,
        recent_start=recent_start,
        recent_end=now,
        recent_window_hours=24,
        event_limit=50,
        log_path=log_path,
        baseline_days=3,
    )

    assert baseline["global_metrics"]["resolution_rate"]["available"] is True
    assert baseline["baseline_window"]["mode"] == "aggregate"
    assert baseline["family_metrics"]
    signature_baseline = next(iter(baseline["signature_metrics"].values()))
    assert signature_baseline["available"] is False or signature_baseline["observation_count"] >= 4


def test_baseline_is_prudent_with_low_sample(tmp_path):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 31, 12, 0, 0)
    log_path = tmp_path / "conversations.jsonl"
    recent_start = now - timedelta(hours=6)
    _write_turns(log_path, [_turn(conversation_id="only-1", turn_number=1, timestamp=now - timedelta(days=2, hours=10), output_mode="advice", progress_delta=1, no_progress=False)])

    _add_impact_entry(db, recommendation=_threshold_recommendation(), status="improved", created_at=now - timedelta(days=2))
    db.commit()

    baseline = baseline_service.build_operational_baseline(
        db,
        recent_start=recent_start,
        recent_end=now,
        recent_window_hours=24,
        event_limit=50,
        log_path=log_path,
        baseline_days=3,
    )

    assert baseline["global_metrics"]["resolution_rate"]["available"] is False
    assert baseline["global_metrics"]["resolution_rate"]["low_sample"] is True
    first_signature = next(iter(baseline["signature_metrics"].values()))
    assert first_signature["available"] is False


def test_drift_detects_real_resolution_drop():
    context = {
        "recent_conversation_metrics": {
            "volume": {"total_conversations": 5, "total_turns": 10},
            "progress": {"conversations_with_progress": 1},
            "output_modes": {"clarification_ratio": 0.75},
            "friction": {"loop_conversations": []},
        },
        "previous_conversation_metrics": {
            "volume": {"total_conversations": 5, "total_turns": 10},
            "progress": {"conversations_with_progress": 1},
            "output_modes": {"clarification_ratio": 0.6},
            "friction": {"loop_conversations": []},
        },
        "recent_safety_snapshot": {},
        "previous_safety_snapshot": {},
        "action_confidence_stats": {"total_actions": 0, "low_confidence_ratio": 0.0},
        "previous_action_confidence_stats": {"total_actions": 0, "low_confidence_ratio": 0.0},
        "auto_healing_snapshot": {"total_events_last_24h": 0, "action_breakdown": {}},
        "previous_auto_healing_snapshot": {"total_events_last_24h": 0, "action_breakdown": {}},
        "family_metrics_recent": [],
        "family_metrics_previous": [],
        "signature_metrics_recent": [],
        "signature_metrics_previous": [],
    }
    baseline = {
        "global_metrics": {
            "resolution_rate": {"available": True, "baseline_value": 0.85, "sample_count": 5, "confidence": "high"},
            "clarification_ratio": {"available": True, "baseline_value": 0.35, "sample_count": 5, "confidence": "high"},
        },
        "family_metrics": {},
        "signature_metrics": {},
        "summary": {},
    }

    drift = drift_policy.build_drift_context(context, baseline, detected_at=datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc))
    resolution_drift = next(item for item in drift["drifts"] if item["metric_name"] == "resolution_rate")
    clarification_drift = next(item for item in drift["drifts"] if item["metric_name"] == "clarification_ratio")

    assert resolution_drift["severity"] == "critical"
    assert clarification_drift["severity"] in {"warning", "critical"}


def test_drift_ignores_small_variation_and_low_sample():
    context = {
        "recent_conversation_metrics": {
            "volume": {"total_conversations": 2, "total_turns": 4},
            "progress": {"conversations_with_progress": 1},
            "output_modes": {"clarification_ratio": 0.42},
            "friction": {"loop_conversations": []},
        },
        "previous_conversation_metrics": {
            "volume": {"total_conversations": 2, "total_turns": 4},
            "progress": {"conversations_with_progress": 1},
            "output_modes": {"clarification_ratio": 0.4},
            "friction": {"loop_conversations": []},
        },
        "recent_safety_snapshot": {},
        "previous_safety_snapshot": {},
        "action_confidence_stats": {"total_actions": 2, "low_confidence_ratio": 0.2},
        "previous_action_confidence_stats": {"total_actions": 2, "low_confidence_ratio": 0.2},
        "auto_healing_snapshot": {"total_events_last_24h": 0, "action_breakdown": {}},
        "previous_auto_healing_snapshot": {"total_events_last_24h": 0, "action_breakdown": {}},
        "family_metrics_recent": [],
        "family_metrics_previous": [],
        "signature_metrics_recent": [],
        "signature_metrics_previous": [],
    }
    baseline = {
        "global_metrics": {
            "resolution_rate": {"available": False, "baseline_value": 0.55, "sample_count": 1, "confidence": "low"},
            "clarification_ratio": {"available": True, "baseline_value": 0.4, "sample_count": 5, "confidence": "medium"},
        },
        "family_metrics": {},
        "signature_metrics": {},
        "summary": {},
    }

    drift = drift_policy.build_drift_context(context, baseline, detected_at=datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc))
    assert drift["drifts"] == []


def test_drift_detects_clarification_rise_without_confusing_noise():
    context = {
        "recent_conversation_metrics": {
            "volume": {"total_conversations": 8, "total_turns": 16},
            "progress": {"conversations_with_progress": 6},
            "output_modes": {"clarification_ratio": 0.62},
            "friction": {"loop_conversations": []},
        },
        "previous_conversation_metrics": {
            "volume": {"total_conversations": 8, "total_turns": 16},
            "progress": {"conversations_with_progress": 7},
            "output_modes": {"clarification_ratio": 0.58},
            "friction": {"loop_conversations": []},
        },
        "recent_safety_snapshot": {},
        "previous_safety_snapshot": {},
        "action_confidence_stats": {"total_actions": 0, "low_confidence_ratio": 0.0},
        "previous_action_confidence_stats": {"total_actions": 0, "low_confidence_ratio": 0.0},
        "auto_healing_snapshot": {"total_events_last_24h": 0, "action_breakdown": {}},
        "previous_auto_healing_snapshot": {"total_events_last_24h": 0, "action_breakdown": {}},
        "family_metrics_recent": [],
        "family_metrics_previous": [],
        "signature_metrics_recent": [],
        "signature_metrics_previous": [],
    }
    baseline = {
        "global_metrics": {
            "clarification_ratio": {"available": True, "baseline_value": 0.34, "sample_count": 14, "confidence": "high"},
        },
        "family_metrics": {},
        "signature_metrics": {},
        "summary": {},
    }

    drift = drift_policy.build_drift_context(context, baseline, detected_at=datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc))
    clarification_drift = next(item for item in drift["drifts"] if item["metric_name"] == "clarification_ratio")

    assert clarification_drift["severity"] in {"warning", "critical"}
    assert clarification_drift["previous_value"] == 0.58
    assert clarification_drift["persistent"] is True


def test_drift_surfaces_gradual_persistent_change_as_info():
    context = {
        "recent_conversation_metrics": {
            "volume": {"total_conversations": 10, "total_turns": 20},
            "progress": {"conversations_with_progress": 7},
            "output_modes": {"clarification_ratio": 0.59},
            "friction": {"loop_conversations": []},
        },
        "previous_conversation_metrics": {
            "volume": {"total_conversations": 10, "total_turns": 20},
            "progress": {"conversations_with_progress": 8},
            "output_modes": {"clarification_ratio": 0.57},
            "friction": {"loop_conversations": []},
        },
        "recent_safety_snapshot": {},
        "previous_safety_snapshot": {},
        "action_confidence_stats": {"total_actions": 0, "low_confidence_ratio": 0.0},
        "previous_action_confidence_stats": {"total_actions": 0, "low_confidence_ratio": 0.0},
        "auto_healing_snapshot": {"total_events_last_24h": 0, "action_breakdown": {}},
        "previous_auto_healing_snapshot": {"total_events_last_24h": 0, "action_breakdown": {}},
        "family_metrics_recent": [],
        "family_metrics_previous": [],
        "signature_metrics_recent": [],
        "signature_metrics_previous": [],
    }
    baseline = {
        "global_metrics": {
            "clarification_ratio": {"available": True, "baseline_value": 0.5, "sample_count": 16, "confidence": "high"},
        },
        "family_metrics": {},
        "signature_metrics": {},
        "summary": {},
    }

    drift = drift_policy.build_drift_context(context, baseline, detected_at=datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc))
    clarification_drift = next(item for item in drift["drifts"] if item["metric_name"] == "clarification_ratio")

    assert clarification_drift["severity"] == "info"
    assert clarification_drift["persistent"] is True


def test_drift_detects_segment_regressed_ratio():
    context = {
        "recent_conversation_metrics": {},
        "recent_safety_snapshot": {},
        "action_confidence_stats": {},
        "auto_healing_snapshot": {},
        "family_metrics_recent": [
            {
                "signature_family": "domain_override:prefer_hybrid",
                "event_type": "domain_override",
                "observation_count": 8,
                "avg_score": -0.1,
                "negative_count": 5,
            }
        ],
        "signature_metrics_recent": [],
    }
    baseline = {
        "global_metrics": {},
        "family_metrics": {
            "domain_override:prefer_hybrid": {
                "available": True,
                "confidence": "high",
                "observation_count": 12,
                "avg_score": -0.05,
                "regressed_ratio": 0.08,
            }
        },
        "signature_metrics": {},
        "summary": {},
    }

    drift = drift_policy.build_drift_context(context, baseline, detected_at=datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc))
    assert any(item["metric_name"] == "family_regressed_ratio" for item in drift["drifts"])


def test_drift_detects_signature_regression_with_good_sample():
    context = {
        "recent_conversation_metrics": {},
        "recent_safety_snapshot": {},
        "action_confidence_stats": {},
        "auto_healing_snapshot": {},
        "family_metrics_recent": [],
        "family_metrics_previous": [],
        "signature_metrics_recent": [
            {
                "signature": "threshold_adjustment:low_confidence",
                "signature_family": "threshold_adjustment",
                "event_type": "threshold_adjustment",
                "observation_count": 10,
                "avg_score": -0.52,
                "negative_count": 7,
            }
        ],
        "signature_metrics_previous": [
            {
                "signature": "threshold_adjustment:low_confidence",
                "signature_family": "threshold_adjustment",
                "event_type": "threshold_adjustment",
                "observation_count": 8,
                "avg_score": -0.32,
                "negative_count": 4,
            }
        ],
    }
    baseline = {
        "global_metrics": {},
        "family_metrics": {},
        "signature_metrics": {
            "threshold_adjustment:low_confidence": {
                "available": True,
                "confidence": "high",
                "observation_count": 14,
                "avg_score": -0.1,
                "regressed_ratio": 0.14,
            }
        },
        "summary": {},
    }

    drift = drift_policy.build_drift_context(context, baseline, detected_at=datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc))
    score_drift = next(item for item in drift["drifts"] if item["metric_name"] == "signature_avg_score")

    assert score_drift["scope"] == "signature"
    assert score_drift["persistent"] is True
    assert score_drift["confidence"] in {"medium", "high"}


def test_priority_engine_orders_alerts_deterministically():
    alerts = [
        {
            "alert_id": "family-warning",
            "category": "family_specific_degradation",
            "severity": "warning",
            "related_family": "domain_override:prefer_hybrid",
            "metric": {"name": "family_avg_score", "value": -0.5, "observation_count": 8},
            "recommended_action": "Revisar family.",
            "drift": {"severity": "warning", "confidence": "medium", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {},
        },
        {
            "alert_id": "global-critical",
            "category": "resolution_drop",
            "severity": "critical",
            "metric": {"name": "resolution_rate", "value": 0.2, "sample_size": 10},
            "recommended_action": "Revisar flujo.",
            "drift": {"severity": "critical", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
        {
            "alert_id": "signature-warning",
            "category": "signature_specific_regression",
            "severity": "warning",
            "related_signature": "threshold_adjustment:low_confidence",
            "metric": {"name": "signature_avg_score", "value": -0.45, "observation_count": 4},
            "recommended_action": "",
            "drift": {"severity": "warning", "confidence": "low", "persistent": False},
            "baseline_context": {"low_sample": True},
            "evidence": {},
        },
    ]

    prioritized = priority_engine.enrich_alert_priorities(alerts)

    assert [item["alert_id"] for item in prioritized] == ["global-critical", "family-warning", "signature-warning"]
    assert prioritized[0]["priority_level"] == "high"
    assert prioritized[0]["priority_reason"]
    assert prioritized[0]["priority_factors"]["severity_score"] > prioritized[1]["priority_factors"]["severity_score"]
    assert prioritized[-1]["priority_level"] in {"low", "medium"}


def test_priority_engine_caps_low_sample_alerts():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "critical-low-sample",
            "category": "resolution_drop",
            "severity": "critical",
            "metric": {"name": "resolution_rate", "value": 0.1, "sample_size": 2},
            "recommended_action": "Revisar flujo.",
            "drift": {"severity": "critical", "confidence": "low"},
            "baseline_context": {"low_sample": True},
            "evidence": {"deduped_alert_count": 3},
        }
    ])

    assert prioritized[0]["priority_level"] == "medium"
    assert prioritized[0]["priority_score"] < 70
    assert prioritized[0]["priority_factors"]["low_sample"] is True


def test_priority_engine_prefers_segment_critical_over_global_warning_when_both_are_solid():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "global-warning-strong",
            "category": "resolution_drop",
            "severity": "warning",
            "metric": {"name": "resolution_rate", "value": 0.4, "sample_size": 16},
            "recommended_action": "Revisar flujo.",
            "drift": {"severity": "critical", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
        {
            "alert_id": "family-critical-solid",
            "category": "family_specific_degradation",
            "severity": "critical",
            "related_family": "domain_override:prefer_hybrid",
            "metric": {"name": "family_avg_score", "value": -0.6, "observation_count": 11},
            "recommended_action": "Revisar family.",
            "drift": {"severity": "critical", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {},
        },
    ])

    assert [item["alert_id"] for item in prioritized] == ["family-critical-solid", "global-warning-strong"]


def test_priority_engine_signature_critical_strong_can_dominate_global_warning():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "global-warning",
            "category": "resolution_drop",
            "severity": "warning",
            "metric": {"name": "resolution_rate", "value": 0.38, "sample_size": 18},
            "drift": {"severity": "critical", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
        {
            "alert_id": "signature-critical-strong",
            "category": "signature_specific_regression",
            "severity": "critical",
            "related_signature": "sig:critical",
            "metric": {"name": "signature_avg_score", "value": -0.72, "observation_count": 14},
            "drift": {"severity": "critical", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
    ])

    assert prioritized[0]["alert_id"] == "signature-critical-strong"
    assert prioritized[0]["priority_factors"]["dominance_rank"] == 0


def test_priority_engine_prefers_strong_warning_over_low_sample_critical():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "critical-low-evidence",
            "category": "signature_specific_regression",
            "severity": "critical",
            "related_signature": "sig:a",
            "metric": {"name": "signature_avg_score", "value": -0.7, "observation_count": 2},
            "recommended_action": "Revisar signature.",
            "drift": {"severity": "critical", "confidence": "low", "persistent": False},
            "baseline_context": {"low_sample": True},
            "evidence": {},
        },
        {
            "alert_id": "warning-strong",
            "category": "loop_risk",
            "severity": "warning",
            "metric": {"name": "loop_conversations", "value": 4, "sample_size": 12},
            "recommended_action": "Corregir loop.",
            "drift": {"severity": "warning", "confidence": "medium", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
    ])

    assert prioritized[0]["alert_id"] == "warning-strong"
    assert prioritized[0]["priority_level"] in {"medium", "high"}
    assert prioritized[1]["priority_level"] == "medium"


def test_priority_engine_signature_critical_limited_does_not_dominate_global_warning():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "global-warning-strong",
            "category": "resolution_drop",
            "severity": "warning",
            "metric": {"name": "resolution_rate", "value": 0.41, "sample_size": 16},
            "drift": {"severity": "critical", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
        {
            "alert_id": "signature-critical-limited",
            "category": "signature_specific_regression",
            "severity": "critical",
            "related_signature": "sig:weak",
            "metric": {"name": "signature_avg_score", "value": -0.75, "observation_count": 2},
            "drift": {"severity": "critical", "confidence": "low", "persistent": False},
            "baseline_context": {"low_sample": True},
            "evidence": {},
        },
    ])

    assert prioritized[0]["alert_id"] == "global-warning-strong"
    assert prioritized[1]["priority_factors"]["evidence_level"] == "limited"


def test_priority_engine_orders_same_severity_by_drift_and_sample_quality():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "warning-no-drift",
            "category": "excessive_clarification",
            "severity": "warning",
            "metric": {"name": "clarification_ratio", "value": 0.5, "sample_size": 12},
            "recommended_action": "Monitorear.",
            "baseline_context": {"low_sample": False},
            "evidence": {},
        },
        {
            "alert_id": "warning-persistent",
            "category": "loop_risk",
            "severity": "warning",
            "metric": {"name": "loop_conversations", "value": 3, "sample_size": 12},
            "recommended_action": "Corregir loop.",
            "drift": {"severity": "warning", "confidence": "medium", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {},
        },
        {
            "alert_id": "warning-low-sample",
            "category": "signature_specific_regression",
            "severity": "warning",
            "related_signature": "sig:b",
            "metric": {"name": "signature_avg_score", "value": -0.5, "observation_count": 2},
            "recommended_action": "Revisar.",
            "drift": {"severity": "warning", "confidence": "low", "persistent": False},
            "baseline_context": {"low_sample": True},
            "evidence": {},
        },
    ])

    assert [item["alert_id"] for item in prioritized] == ["warning-persistent", "warning-no-drift", "warning-low-sample"]


def test_priority_engine_uses_evidence_level_for_same_severity_ties():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "warning-moderate",
            "category": "loop_risk",
            "severity": "warning",
            "metric": {"name": "loop_conversations", "value": 2, "sample_size": 6},
            "drift": {"severity": "warning", "confidence": "medium", "persistent": False},
            "baseline_context": {"low_sample": False},
            "evidence": {},
        },
        {
            "alert_id": "warning-strong",
            "category": "loop_risk",
            "severity": "warning",
            "metric": {"name": "loop_conversations", "value": 4, "sample_size": 12},
            "drift": {"severity": "warning", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
        {
            "alert_id": "warning-limited",
            "category": "loop_risk",
            "severity": "warning",
            "metric": {"name": "loop_conversations", "value": 1, "sample_size": 2},
            "drift": {"severity": "warning", "confidence": "low", "persistent": False},
            "baseline_context": {"low_sample": True},
            "evidence": {},
        },
    ])

    assert [item["alert_id"] for item in prioritized] == ["warning-strong", "warning-moderate", "warning-limited"]
    assert prioritized[0]["priority_factors"]["evidence_level"] == "strong"
    assert prioritized[1]["priority_factors"]["evidence_level"] == "moderate"
    assert prioritized[2]["priority_factors"]["evidence_level"] == "limited"


def test_priority_reason_explains_low_sample_limitation():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "low-sample-alert",
            "category": "signature_specific_regression",
            "severity": "critical",
            "related_signature": "sig:c",
            "metric": {"name": "signature_avg_score", "value": -0.6, "observation_count": 2},
            "drift": {"severity": "critical", "confidence": "low", "persistent": False},
            "baseline_context": {"low_sample": True},
            "evidence": {},
        }
    ])

    reason = prioritized[0]["priority_reason"].lower()
    assert "baja muestra" in reason
    assert "evidencia" in reason
    assert "prioridad" in reason


def test_priority_reason_explains_scope_evidence_and_drift():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "family-strong",
            "category": "family_specific_degradation",
            "severity": "critical",
            "related_family": "domain_override:prefer_hybrid",
            "metric": {"name": "family_avg_score", "value": -0.65, "observation_count": 11},
            "recommended_action": "Revisar family.",
            "drift": {"severity": "critical", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        }
    ])

    reason = prioritized[0]["priority_reason"].lower()
    assert reason.startswith("alta prioridad:")
    assert "familia especifica" in reason
    assert "evidencia" in reason
    assert "degradacion significativa" in reason
    assert "dentro de una tendencia global" not in reason


def test_priority_reason_includes_related_global_context_for_localized_drift():
    prioritized = priority_engine.enrich_alert_priorities([
        {
            "alert_id": "global-warning",
            "category": "loop_risk",
            "severity": "warning",
            "metric": {"name": "loop_conversations", "value": 4, "sample_size": 12},
            "drift": {"severity": "warning", "confidence": "medium", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
        {
            "alert_id": "signature-critical",
            "category": "signature_specific_regression",
            "severity": "critical",
            "related_signature": "sig:ctx",
            "metric": {"name": "signature_avg_score", "value": -0.7, "observation_count": 12},
            "drift": {"severity": "critical", "confidence": "high", "persistent": True},
            "baseline_context": {"low_sample": False},
            "evidence": {"deduped_alert_count": 2},
        },
    ])

    reason = next(item["priority_reason"] for item in prioritized if item["alert_id"] == "signature-critical").lower()
    assert "dentro de una tendencia global" in reason


def test_live_alert_snapshot_exposes_baseline_drift_and_priority(tmp_path, fixed_now, stable_monitors):
    db = _build_session(tmp_path)
    now = fixed_now
    log_path = tmp_path / "conversations.jsonl"

    rows = [
        _turn(conversation_id="base-1", turn_number=1, timestamp=now - timedelta(days=2, hours=8), output_mode="advice", case_domain="alimentos", progress_delta=1, no_progress=False),
        _turn(conversation_id="base-2", turn_number=1, timestamp=now - timedelta(days=1, hours=8), output_mode="advice", case_domain="alimentos", progress_delta=1, no_progress=False),
        _turn(conversation_id="base-3", turn_number=1, timestamp=now - timedelta(hours=20), output_mode="advice", case_domain="alimentos", progress_delta=1, no_progress=False),
        _turn(conversation_id="base-4", turn_number=1, timestamp=now - timedelta(hours=19), output_mode="advice", case_domain="alimentos", progress_delta=1, no_progress=False),
        _turn(conversation_id="base-5", turn_number=1, timestamp=now - timedelta(hours=18, minutes=30), output_mode="advice", case_domain="alimentos", progress_delta=1, no_progress=False),
        _turn(conversation_id="recent-1", turn_number=1, timestamp=now - timedelta(minutes=50), output_mode="clarification", case_domain="alimentos", question_asked="¿Ingresos?", no_progress=True),
        _turn(conversation_id="recent-2", turn_number=1, timestamp=now - timedelta(minutes=40), output_mode="clarification", case_domain="alimentos", question_asked="¿Ingresos?", repeat_question=True, no_progress=True),
        _turn(conversation_id="recent-3", turn_number=1, timestamp=now - timedelta(minutes=30), output_mode="clarification", case_domain="alimentos", question_asked="¿Gastos?", no_progress=True),
    ]
    _write_turns(log_path, rows)

    for created_at in [now - timedelta(days=2), now - timedelta(days=1, hours=4), now - timedelta(hours=18), now - timedelta(hours=12)]:
        _add_impact_entry(db, recommendation=_domain_recommendation(), status="improved", created_at=created_at, confidence_score=0.85)
    db.commit()

    snapshot = live_alert_service.get_live_alert_snapshot(
        db,
        last_hours=6,
        event_limit=50,
        baseline_days=3,
        log_path=log_path,
    )

    resolution_alert = next(item for item in snapshot["alerts"] if item["category"] == "resolution_drop")
    assert "summary" in snapshot
    assert "baseline_summary" in snapshot
    assert "drift_summary" in snapshot
    assert "top_prioritized_alerts" in snapshot
    assert resolution_alert["baseline_context"]
    assert resolution_alert["drift"]
    assert resolution_alert["priority_score"] is not None
    assert resolution_alert["priority_level"] in {"high", "medium", "low"}
    assert snapshot["top_prioritized_alerts"][0]["alert_id"] == snapshot["alerts"][0]["alert_id"]


def test_live_alert_snapshot_ignores_invalid_timestamps_in_logs(tmp_path, fixed_now, stable_monitors):
    db = _build_session(tmp_path)
    now = fixed_now
    log_path = tmp_path / "conversations_invalid.jsonl"
    rows = [
        _turn(conversation_id="valid-1", turn_number=1, timestamp=now - timedelta(days=1), output_mode="advice", progress_delta=1, no_progress=False),
        {**_turn(conversation_id="invalid-1", turn_number=1, timestamp=now - timedelta(hours=1), output_mode="clarification"), "timestamp": "not-a-date"},
        {**_turn(conversation_id="missing-1", turn_number=1, timestamp=now - timedelta(hours=1), output_mode="clarification"), "timestamp": ""},
    ]
    _write_turns(log_path, rows)

    snapshot = live_alert_service.get_live_alert_snapshot(
        db,
        last_hours=6,
        event_limit=50,
        baseline_days=3,
        log_path=log_path,
    )

    assert snapshot["sources"]["recent_turn_count"] == 0
    assert snapshot["window"]["recent_event_count"] == 0


def test_alert_id_is_stable_between_equivalent_snapshots():
    evaluated_at = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    first = live_alert_policy.build_alert(
        category="resolution_drop",
        severity="critical",
        title="Caida reciente de resolucion",
        description="desc",
        detected_at=evaluated_at,
        window={"mode": "mixed", "last_hours": 6},
        metric={"name": "resolution_rate", "value": 0.2},
        threshold={"critical_threshold": 0.4},
        recommended_action="Revisar flujo.",
        should_surface_to_ui=True,
        dedupe_key="resolution_drop",
    )
    second = live_alert_policy.build_alert(
        category="resolution_drop",
        severity="critical",
        title="Caida reciente de resolucion",
        description="desc",
        detected_at=evaluated_at + timedelta(minutes=10),
        window={"mode": "mixed", "last_hours": 6},
        metric={"name": "resolution_rate", "value": 0.2},
        threshold={"critical_threshold": 0.4},
        recommended_action="Revisar flujo.",
        should_surface_to_ui=True,
        dedupe_key="resolution_drop",
    )

    assert first["alert_id"] == second["alert_id"]


def test_detected_at_represents_snapshot_evaluation_time():
    evaluated_at = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    alert = live_alert_policy.build_alert(
        category="resolution_drop",
        severity="critical",
        title="Caida reciente de resolucion",
        description="desc",
        detected_at=evaluated_at,
        window={"mode": "mixed", "last_hours": 6},
        metric={"name": "resolution_rate", "value": 0.2},
        threshold={"critical_threshold": 0.4},
        recommended_action="Revisar flujo.",
        should_surface_to_ui=True,
        dedupe_key="resolution_drop",
    )

    assert alert["detected_at"] == evaluated_at.isoformat()
