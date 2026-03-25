"""
AILEX - Tests del servicio de insights interpretativos.

Cubre:
1. Generacion de insights de drift
2. Generacion de insights de signatures
3. Generacion de insights de families
4. Generacion de insights de decisiones
5. Ordenamiento por severidad
6. DB vacia (sin insights)
7. Endpoint API /insights
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_action_log  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_log  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.services import learning_insights_service
from app.services.impact_memory_service import (
    SIGNATURE_METADATA_VERSION,
    build_impact_signature,
    build_impact_signature_family,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'insights.db'}",
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
    applied: bool = True,
    reason: str = "historical",
    impact_score: float = 0.0,
    confidence_score: float | None = None,
) -> str:
    sig = build_impact_signature(recommendation)
    fam = build_impact_signature_family(recommendation)
    payload = {
        "impact_metadata_version": SIGNATURE_METADATA_VERSION,
        "impact_signature": sig,
        "impact_signature_family": fam,
        "impact_decision_level": "signature",
        "impact_decision_reason": reason,
        "impact_decision_source": "signature",
        "impact_score_reference": {
            "metadata_version": SIGNATURE_METADATA_VERSION,
            "signature": sig,
            "signature_family": fam,
            "decision_level": "signature",
            "decision_source": "signature",
            "decision_mode": "boosted" if applied else "blocked",
            "signature_evidence": {
                "key": sig,
                "scope": "signature",
                "score": 0.5 if status == "improved" else -0.5,
                "available": True,
                "strong_enough": True,
                "raw_total": 5,
                "weighted_total": 4.0,
                "dominant_signal": status,
                "memory_confidence": 0.8,
            },
            "signature_family_evidence": {
                "key": fam,
                "scope": "signature_family",
                "score": 0.3,
                "available": True,
                "strong_enough": False,
                "raw_total": 2,
                "weighted_total": 1.0,
                "dominant_signal": "neutral",
                "memory_confidence": 0.3,
            },
            "event_type_evidence": {
                "key": recommendation["event_type"],
                "scope": "event_type",
                "score": 0.0,
                "available": False,
                "strong_enough": False,
                "raw_total": 0,
                "weighted_total": 0.0,
                "dominant_signal": "none",
                "memory_confidence": 0.0,
            },
            "decision_path": [],
            "conflict_summary": {"has_conflict": False, "conflicts": []},
            "temporal_weighting": {
                "strategy": "exponential_half_life",
                "half_life_days": 30.0,
            },
        },
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
            impact_score=impact_score,
            impact_label=status,
        )
    )
    return action_log.id


# ---------------------------------------------------------------------------
# 1. Test insights vacio
# ---------------------------------------------------------------------------


class TestEmptyInsights:
    def test_empty_db_returns_no_insights(self, tmp_path):
        db = _build_session(tmp_path)
        insights = learning_insights_service.generate_insights(db)
        assert insights == []


# ---------------------------------------------------------------------------
# 2. Test insights de drift
# ---------------------------------------------------------------------------


class TestDriftInsights:
    def test_score_delta_drift_generates_insight(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()

        # Previous: all improved
        for i in range(5):
            _add_impact_entry(db, recommendation=rec, status="improved", created_at=now - timedelta(days=i + 15))
        # Recent: all regressed
        for i in range(5):
            _add_impact_entry(db, recommendation=rec, status="regressed", created_at=now - timedelta(days=i + 1))
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        drift_insights = [i for i in insights if i["type"] == "drift"]
        assert len(drift_insights) >= 1

        messages = " ".join(i["message"] for i in drift_insights)
        assert "deterioro" in messages or "inversion" in messages

    def test_trend_inversion_generates_high_severity(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _domain_recommendation()

        for i in range(4):
            _add_impact_entry(db, recommendation=rec, status="improved", created_at=now - timedelta(days=i + 15))
        _add_impact_entry(db, recommendation=rec, status="neutral", created_at=now - timedelta(days=20))
        for i in range(4):
            _add_impact_entry(db, recommendation=rec, status="regressed", created_at=now - timedelta(days=i + 1))
        _add_impact_entry(db, recommendation=rec, status="neutral", created_at=now - timedelta(days=6))
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        inversion_insights = [i for i in insights if "inversion" in i["message"]]
        assert len(inversion_insights) >= 1
        assert inversion_insights[0]["severity"] == "high"

    def test_no_drift_no_insights(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()

        for i in range(6):
            _add_impact_entry(db, recommendation=rec, status="improved", created_at=now - timedelta(days=i + 1))
        for i in range(6):
            _add_impact_entry(db, recommendation=rec, status="improved", created_at=now - timedelta(days=i + 15))
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        drift_insights = [i for i in insights if i["type"] == "drift"]
        assert len(drift_insights) == 0


# ---------------------------------------------------------------------------
# 3. Test insights de signatures
# ---------------------------------------------------------------------------


class TestSignatureInsights:
    def test_critical_signature_detected(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _domain_recommendation()

        # 6 regressed = score ~ -1.0, obs >= 5
        for i in range(6):
            _add_impact_entry(
                db, recommendation=rec, status="regressed",
                created_at=now - timedelta(days=i + 1), impact_score=-0.5,
            )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        sig_insights = [i for i in insights if i["type"] == "signature"]
        assert len(sig_insights) >= 1
        assert sig_insights[0]["severity"] == "high"
        assert "critico" in sig_insights[0]["message"].lower()

    def test_no_signature_insight_for_positive_pattern(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()

        for i in range(6):
            _add_impact_entry(
                db, recommendation=rec, status="improved",
                created_at=now - timedelta(days=i + 1), impact_score=0.5,
            )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        sig_insights = [i for i in insights if i["type"] == "signature"]
        assert len(sig_insights) == 0


# ---------------------------------------------------------------------------
# 4. Test insights de families
# ---------------------------------------------------------------------------


class TestFamilyInsights:
    def test_sustained_regression_detected(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _domain_recommendation()

        for i in range(5):
            _add_impact_entry(
                db, recommendation=rec, status="regressed",
                created_at=now - timedelta(days=i + 1), impact_score=-0.4,
            )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        fam_insights = [i for i in insights if i["type"] == "family"]
        assert len(fam_insights) >= 1
        assert "deterioro" in fam_insights[0]["message"]

    def test_sustained_improvement_detected(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()

        for i in range(5):
            _add_impact_entry(
                db, recommendation=rec, status="improved",
                created_at=now - timedelta(days=i + 1), impact_score=0.5,
            )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        fam_insights = [i for i in insights if i["type"] == "family"]
        improvement_insights = [i for i in fam_insights if "mejora" in i["message"]]
        assert len(improvement_insights) >= 1
        assert improvement_insights[0]["severity"] == "low"


# ---------------------------------------------------------------------------
# 5. Test insights de decisiones
# ---------------------------------------------------------------------------


class TestDecisionInsights:
    def test_high_block_rate_detected(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()

        # 4 blocked, 1 applied => block_rate = 0.8
        for i in range(4):
            _add_impact_entry(
                db, recommendation=rec, status="regressed",
                created_at=now - timedelta(days=i + 1),
                applied=False, reason="blocked_by_negative_signature_impact",
            )
        _add_impact_entry(
            db, recommendation=rec, status="improved",
            created_at=now - timedelta(days=5),
        )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        dec_insights = [i for i in insights if i["type"] == "decisions"]
        block_insights = [i for i in dec_insights if "bloqueo" in i["message"]]
        assert len(block_insights) >= 1

    def test_low_confidence_decisions_detected(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()

        for i in range(5):
            _add_impact_entry(
                db, recommendation=rec, status="neutral",
                created_at=now - timedelta(days=i + 1),
                confidence_score=0.3,
            )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        dec_insights = [i for i in insights if i["type"] == "decisions"]
        conf_insights = [i for i in dec_insights if "confianza" in i["message"]]
        assert len(conf_insights) >= 1


# ---------------------------------------------------------------------------
# 6. Test ordenamiento
# ---------------------------------------------------------------------------


class TestInsightOrdering:
    def test_high_severity_comes_first(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _domain_recommendation()

        # Create enough data for both high and low severity insights
        for i in range(6):
            _add_impact_entry(
                db, recommendation=rec, status="regressed",
                created_at=now - timedelta(days=i + 1), impact_score=-0.5,
            )
        # Also some improved for a different family
        rec2 = _threshold_recommendation()
        for i in range(5):
            _add_impact_entry(
                db, recommendation=rec2, status="improved",
                created_at=now - timedelta(days=i + 1), impact_score=0.5,
            )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)

        if len(insights) >= 2:
            severities = [i["severity"] for i in insights]
            severity_order = {"high": 0, "medium": 1, "low": 2}
            numeric = [severity_order.get(s, 3) for s in severities]
            assert numeric == sorted(numeric), "Insights deben estar ordenados por severidad"


# ---------------------------------------------------------------------------
# 7. Test estructura de insight
# ---------------------------------------------------------------------------


class TestInsightStructure:
    def test_insight_has_required_fields(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _domain_recommendation()

        for i in range(6):
            _add_impact_entry(
                db, recommendation=rec, status="regressed",
                created_at=now - timedelta(days=i + 1), impact_score=-0.5,
            )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)
        assert len(insights) > 0

        for insight in insights:
            assert "type" in insight
            assert "severity" in insight
            assert "message" in insight
            assert "human_summary" in insight
            assert "recommended_target" in insight
            assert "generated_at" in insight
            assert "heuristic_key" in insight
            assert "insight_key" in insight
            assert "metrics" in insight
            assert "explanation" in insight
            assert insight["type"] in ("drift", "signature", "family", "decisions")
            assert insight["severity"] in ("low", "medium", "high")
            assert isinstance(insight["message"], str)
            assert isinstance(insight["human_summary"], str)
            assert isinstance(insight["recommended_target"], str)
            assert isinstance(insight["metrics"], dict)
            assert isinstance(insight["explanation"], dict)
            assert "version" in insight["explanation"]
            assert "source" in insight["explanation"]
            assert "summary" in insight["explanation"]
            assert "conditions" in insight["explanation"]
            assert "thresholds" in insight["explanation"]
            assert "evidence" in insight["explanation"]
            assert "interpretation" in insight["explanation"]

    def test_explanation_is_consistent_with_insight_type(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _domain_recommendation()

        for i in range(6):
            _add_impact_entry(
                db, recommendation=rec, status="regressed",
                created_at=now - timedelta(days=i + 1), impact_score=-0.5,
            )
        db.commit()

        insights = learning_insights_service.generate_insights(db, date_to=now)
        signature_insight = next(i for i in insights if i["type"] == "signature")

        assert "signature" in signature_insight["explanation"]["evidence"]
        assert "critical_score_threshold" in signature_insight["explanation"]["thresholds"]
        assert signature_insight["recommended_target"] == "signatures"
        assert signature_insight["human_summary"]
        assert signature_insight["explanation"]["version"] == "v1"
        assert signature_insight["explanation"]["source"] == "learning_insights_service"


# ---------------------------------------------------------------------------
# 8. Test endpoint API
# ---------------------------------------------------------------------------


class TestInsightsAPI:
    @pytest.fixture
    def client_and_db(self, tmp_path):
        from fastapi import FastAPI
        from app.api.learning_observability import router

        engine = create_engine(
            f"sqlite:///{tmp_path / 'api_insights.db'}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

        app = FastAPI()
        app.include_router(router)

        db_session = session_local()

        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        class FakeUser:
            id = "test-user"
            email = "test@test.com"
            is_active = True

        def override_get_current_user():
            return FakeUser()

        from app.db.database import get_db
        from app.auth.dependencies import get_current_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        client = TestClient(app)
        return client, db_session

    def test_insights_endpoint_empty(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/insights")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_insights_endpoint_with_data(self, client_and_db):
        client, db = client_and_db
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _domain_recommendation()

        for i in range(6):
            _add_impact_entry(
                db, recommendation=rec, status="regressed",
                created_at=now - timedelta(days=i + 1), impact_score=-0.5,
            )
        db.commit()

        response = client.get("/api/learning/observability/insights")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

        for item in data:
            assert "type" in item
            assert "severity" in item
            assert "message" in item
            assert "human_summary" in item
            assert "recommended_target" in item
            assert "generated_at" in item
            assert "heuristic_key" in item
            assert "insight_key" in item
            assert "metrics" in item
            assert "explanation" in item
            assert "version" in item["explanation"]
            assert "source" in item["explanation"]
            assert "summary" in item["explanation"]

    def test_insights_endpoint_with_date_filter(self, client_and_db):
        client, db = client_and_db
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _domain_recommendation()

        for i in range(6):
            _add_impact_entry(
                db, recommendation=rec, status="regressed",
                created_at=now - timedelta(days=i + 1), impact_score=-0.5,
            )
        db.commit()

        response = client.get(
            "/api/learning/observability/insights",
            params={"date_to": "2026-03-23T12:00:00"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
