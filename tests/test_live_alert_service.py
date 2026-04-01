from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_current_user
from app.db.database import Base, get_db
import app.models.auto_healing_event  # noqa: F401
import app.models.learning_action_log  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_review  # noqa: F401
import app.models.system_safety_event  # noqa: F401
from app.api.learning_observability import router
from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.services import live_alert_policy, live_alert_service
from app.services.impact_memory_service import (
    SIGNATURE_METADATA_VERSION,
    build_impact_signature,
    build_impact_signature_family,
)


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'live_alerts.db'}",
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
        "proposed_changes": {"threshold_review": {"low_confidence_threshold": 0.55}},
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
    question_asked: str = "",
    case_domain: str = "divorcio",
    missing_information: list[str] | None = None,
    progress_delta: int = 0,
    repeat_question: bool = False,
    no_progress: bool = True,
    loop_detected: bool = False,
    unnecessary_clarification: bool = False,
) -> dict:
    return {
        "conversation_id": conversation_id,
        "turn_number": turn_number,
        "output_mode": output_mode,
        "question_asked": question_asked,
        "case_domain": case_domain,
        "missing_information": list(missing_information or []),
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
            "unnecessary_clarification": unnecessary_clarification,
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
def stable_monitors(monkeypatch):
    monkeypatch.setattr(live_alert_service, "get_safety_snapshot", _neutral_safety_snapshot)
    monkeypatch.setattr(live_alert_service, "_get_previous_safety_snapshot", lambda *args, **kwargs: _neutral_safety_snapshot())
    monkeypatch.setattr(live_alert_service, "get_review_snapshot", _neutral_review_snapshot)
    monkeypatch.setattr(live_alert_service, "get_auto_healing_snapshot", _neutral_auto_healing_snapshot)


@pytest.fixture
def fixed_now(monkeypatch):
    now = datetime(2026, 3, 31, 12, 0, 0)
    monkeypatch.setattr(live_alert_service, "utc_now", lambda: now)
    return now


def test_alert_triggered_by_absolute_threshold(tmp_path, stable_monitors, fixed_now):
    db = _build_session(tmp_path)
    now = fixed_now
    log_path = tmp_path / "conversations.jsonl"

    recent_rows = [
        _turn(conversation_id="c1", turn_number=1, timestamp=now - timedelta(minutes=50), output_mode="clarification", question_asked="¿Hay hijos?", missing_information=["Hay hijos"], no_progress=True),
        _turn(conversation_id="c1", turn_number=2, timestamp=now - timedelta(minutes=45), output_mode="clarification", question_asked="¿Hay hijos?", missing_information=["Hay hijos"], repeat_question=True, no_progress=True),
        _turn(conversation_id="c2", turn_number=1, timestamp=now - timedelta(minutes=40), output_mode="clarification", question_asked="¿Hay bienes?", missing_information=["Bienes"], no_progress=True),
        _turn(conversation_id="c3", turn_number=1, timestamp=now - timedelta(minutes=35), output_mode="clarification", question_asked="¿Hay convenio?", missing_information=["Convenio"], no_progress=True),
    ]
    _write_turns(log_path, recent_rows)

    snapshot = live_alert_service.get_live_alert_snapshot(db, last_hours=6, event_limit=50, log_path=log_path)

    categories = {alert["category"] for alert in snapshot["alerts"]}
    assert "resolution_drop" in categories
    resolution_alert = next(alert for alert in snapshot["alerts"] if alert["category"] == "resolution_drop")
    assert resolution_alert["severity"] in {"warning", "critical"}
    assert resolution_alert["metric"]["value"] <= 0.45


def test_alert_triggered_by_relative_degradation(tmp_path, stable_monitors, fixed_now):
    db = _build_session(tmp_path)
    now = fixed_now
    log_path = tmp_path / "conversations.jsonl"

    rows = [
        _turn(conversation_id="prev-1", turn_number=1, timestamp=now - timedelta(hours=10), output_mode="clarification", question_asked="Q1", case_domain="alimentos", progress_delta=1, no_progress=False),
        _turn(conversation_id="prev-2", turn_number=1, timestamp=now - timedelta(hours=9, minutes=30), output_mode="advice", case_domain="alimentos", progress_delta=1, no_progress=False),
        _turn(conversation_id="prev-3", turn_number=1, timestamp=now - timedelta(hours=9), output_mode="clarification", question_asked="Q2", case_domain="alimentos", progress_delta=1, no_progress=False),
        _turn(conversation_id="recent-1", turn_number=1, timestamp=now - timedelta(minutes=50), output_mode="clarification", question_asked="¿Ingresos?", case_domain="alimentos", missing_information=["Ingresos"], no_progress=True),
        _turn(conversation_id="recent-2", turn_number=1, timestamp=now - timedelta(minutes=45), output_mode="clarification", question_asked="¿Ingresos?", case_domain="alimentos", missing_information=["Ingresos"], repeat_question=True, no_progress=True),
        _turn(conversation_id="recent-3", turn_number=1, timestamp=now - timedelta(minutes=40), output_mode="clarification", question_asked="¿Gastos?", case_domain="alimentos", missing_information=["Gastos"], no_progress=True),
    ]
    _write_turns(log_path, rows)

    snapshot = live_alert_service.get_live_alert_snapshot(db, last_hours=6, event_limit=50, log_path=log_path)

    resolution_alert = next(alert for alert in snapshot["alerts"] if alert["category"] == "resolution_drop")
    assert resolution_alert["metric"]["previous_value"] is not None
    assert resolution_alert["metric"]["delta"] >= 0.2


def test_severity_and_review_queue_pressure_are_correct(tmp_path, monkeypatch, stable_monitors, fixed_now):
    db = _build_session(tmp_path)
    now = fixed_now
    log_path = tmp_path / "conversations.jsonl"
    _write_turns(log_path, [])

    monkeypatch.setattr(
        live_alert_service,
        "get_review_snapshot",
        lambda *args, **kwargs: {
            "review_queue_size": 10,
            "pending_reviews": 9,
            "pending_reviews_by_priority": {"high": 5, "medium": 3, "low": 1},
            "stale_reviews_count": 4,
            "oldest_pending_review_hours": 80.0,
            "approval_rate": 0.0,
            "rejection_rate": 0.0,
            "override_rate": 0.0,
            "recent_human_actions_summary": {},
        },
    )

    snapshot = live_alert_service.get_live_alert_snapshot(db, last_hours=6, event_limit=50, log_path=log_path)
    alert = next(alert for alert in snapshot["alerts"] if alert["category"] == "high_review_queue_pressure")
    assert alert["severity"] == "critical"
    assert alert["metric"]["value"] == 9


def test_deduplication_compacts_same_alerts():
    now = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    window = {"mode": "mixed", "last_hours": 6, "event_limit": 100, "recent_event_count": 10}
    duplicate_a = live_alert_policy.build_alert(
        category="family_specific_degradation",
        severity="warning",
        title="Family degradada",
        description="La family alimentos esta peor.",
        detected_at=now,
        window=window,
        metric={"name": "family_avg_score", "value": -0.4},
        threshold={"warning_avg_score": -0.25},
        related_family="domain_override:prefer_hybrid",
        recommended_action="Revisar family.",
        should_surface_to_ui=True,
        dedupe_key="family_specific_degradation:domain_override:prefer_hybrid",
    )
    duplicate_b = live_alert_policy.build_alert(
        category="family_specific_degradation",
        severity="critical",
        title="Family degradada",
        description="La family alimentos esta mucho peor.",
        detected_at=now,
        window=window,
        metric={"name": "family_avg_score", "value": -0.8},
        threshold={"critical_avg_score": -0.5},
        related_family="domain_override:prefer_hybrid",
        event_type="domain_override",
        recommended_action="Revisar family.",
        should_surface_to_ui=True,
        dedupe_key="family_specific_degradation:domain_override:prefer_hybrid",
    )

    alerts = live_alert_policy.dedupe_and_compact_alerts([duplicate_a, duplicate_b])

    assert len(alerts) == 1
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["evidence"]["deduped_alert_count"] == 2


def test_empty_window_returns_no_alerts(tmp_path, stable_monitors, fixed_now):
    db = _build_session(tmp_path)
    log_path = tmp_path / "conversations.jsonl"
    _write_turns(log_path, [])

    snapshot = live_alert_service.get_live_alert_snapshot(db, last_hours=6, event_limit=50, log_path=log_path)

    assert snapshot["has_data"] is False
    assert snapshot["summary"]["total_alerts"] == 0
    assert snapshot["alerts"] == []


def test_no_alerts_when_recent_state_is_healthy(tmp_path, stable_monitors, fixed_now):
    db = _build_session(tmp_path)
    now = fixed_now
    log_path = tmp_path / "conversations.jsonl"
    _write_turns(
        log_path,
        [
            _turn(conversation_id="ok-1", turn_number=1, timestamp=now - timedelta(minutes=40), output_mode="clarification", case_domain="divorcio", progress_delta=1, no_progress=False),
            _turn(conversation_id="ok-1", turn_number=2, timestamp=now - timedelta(minutes=35), output_mode="advice", case_domain="divorcio", progress_delta=1, no_progress=False),
            _turn(conversation_id="ok-2", turn_number=1, timestamp=now - timedelta(minutes=30), output_mode="clarification", case_domain="alimentos", progress_delta=1, no_progress=False),
            _turn(conversation_id="ok-2", turn_number=2, timestamp=now - timedelta(minutes=25), output_mode="advice", case_domain="alimentos", progress_delta=1, no_progress=False),
        ],
    )

    rec_threshold = _threshold_recommendation()
    rec_domain = _domain_recommendation()
    _add_impact_entry(db, recommendation=rec_threshold, status="improved", created_at=now - timedelta(minutes=20), confidence_score=0.8)
    _add_impact_entry(db, recommendation=rec_domain, status="improved", created_at=now - timedelta(minutes=10), confidence_score=0.85)
    db.commit()

    snapshot = live_alert_service.get_live_alert_snapshot(db, last_hours=6, event_limit=50, log_path=log_path)
    assert snapshot["alerts"] == []
    assert snapshot["summary"]["total_alerts"] == 0


def test_backend_endpoint_is_backward_compatible(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    now = datetime(2026, 3, 31, 12, 0, 0)
    rec_threshold = _threshold_recommendation()
    _add_impact_entry(db, recommendation=rec_threshold, status="improved", created_at=now - timedelta(hours=1))
    db.commit()

    test_app = FastAPI()
    test_app.include_router(router)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    class FakeUser:
        id = "user-1"
        email = "tester@example.com"
        is_active = True

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_current_user] = lambda: FakeUser()

    monkeypatch.setattr(
        live_alert_service,
        "get_live_alert_snapshot",
        lambda *args, **kwargs: {
            "generated_at": "2026-03-31T12:00:00+00:00",
            "source": "live_alert_service",
            "window": {"mode": "mixed", "last_hours": 6, "event_limit": 200, "recent_event_count": 12},
            "has_data": True,
            "summary": {
                "total_alerts": 1,
                "surfaced_alerts": 1,
                "by_severity": {"warning": 1},
                "by_category": {"loop_risk": 1},
                "active_categories": ["loop_risk"],
            },
            "alerts": [
                {
                    "alert_id": "abc123",
                    "category": "loop_risk",
                    "severity": "warning",
                    "title": "Riesgo de loop",
                    "description": "Hay repreguntas recientes.",
                    "detected_at": "2026-03-31T12:00:00+00:00",
                    "window": {"mode": "mixed", "last_hours": 6, "event_limit": 200, "recent_event_count": 12},
                    "metric": {"name": "loop_conversations", "value": 1},
                    "threshold": {"warning_loop_conversations": 1},
                    "related_family": None,
                    "related_signature": None,
                    "event_type": None,
                    "output_mode": "clarification",
                    "recommended_action": "Revisar repreguntas.",
                    "should_surface_to_ui": True,
                    "dedupe_key": "loop_risk",
                    "evidence": {},
                    "source": "live_alert_service",
                }
            ],
            "sources": {
                "conversation_log_path": str(tmp_path / "conversations.jsonl"),
                "recent_turn_count": 3,
                "recent_action_count": 1,
                "recent_family_metric_count": 1,
                "recent_signature_metric_count": 1,
            },
        },
    )

    client = TestClient(test_app)
    overview = client.get("/api/learning/observability/overview")
    live = client.get("/api/learning/observability/live-alerts")

    assert overview.status_code == 200
    assert overview.json()["total_observations"] == 1
    assert live.status_code == 200
    assert live.json()["summary"]["total_alerts"] == 1
    assert live.json()["alerts"][0]["category"] == "loop_risk"
