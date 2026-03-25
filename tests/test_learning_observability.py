"""
AILEX - Tests del servicio de observabilidad del aprendizaje adaptativo.

Cubre:
1. Agregacion overview
2. Agregacion por signature
3. Agregacion por family
4. Agregacion por event_type
5. Evolucion temporal
6. Drift detection
7. Trazabilidad de decisiones
8. Endpoints API read-only
9. Consistencia UTC (FASE 4.0.1)
10. Ausencia de truncamiento silencioso (FASE 4.0.1)
11. dominant_signal enriquecido (FASE 4.0.1)
12. Pesos centralizados (FASE 4.0.1)
"""

from __future__ import annotations

import json
import warnings
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
from app.services import learning_observability_service
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
        f"sqlite:///{tmp_path / 'observability.db'}",
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
        confidence_score=recommendation.get("confidence_score"),
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


def _populate_test_data(db: Session, now: datetime) -> None:
    """Crea un conjunto representativo de datos para los tests."""
    rec_threshold = _threshold_recommendation()
    rec_domain = _domain_recommendation()

    # 3 improved, 1 regressed para threshold
    _add_impact_entry(db, recommendation=rec_threshold, status="improved", created_at=now - timedelta(days=5), impact_score=0.6)
    _add_impact_entry(db, recommendation=rec_threshold, status="improved", created_at=now - timedelta(days=3), impact_score=0.4)
    _add_impact_entry(db, recommendation=rec_threshold, status="improved", created_at=now - timedelta(days=1), impact_score=0.5)
    _add_impact_entry(db, recommendation=rec_threshold, status="regressed", created_at=now - timedelta(days=2), reason="blocked_by_negative_signature_impact", applied=False, impact_score=-0.3)

    # 2 regressed, 1 neutral para domain
    _add_impact_entry(db, recommendation=rec_domain, status="regressed", created_at=now - timedelta(days=4), impact_score=-0.5)
    _add_impact_entry(db, recommendation=rec_domain, status="regressed", created_at=now - timedelta(days=2), impact_score=-0.4)
    _add_impact_entry(db, recommendation=rec_domain, status="neutral", created_at=now - timedelta(days=1), impact_score=0.0)

    db.commit()


# ---------------------------------------------------------------------------
# 1. Test overview global
# ---------------------------------------------------------------------------


class TestOverview:
    def test_overview_counts(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        overview = learning_observability_service.get_overview(db, date_to=now)

        assert overview["total_observations"] == 7
        assert overview["total_adaptive_decisions"] == 7
        assert overview["unique_signatures"] >= 2
        assert overview["unique_signature_families"] >= 2
        assert overview["unique_event_types"] == 2
        assert overview["reinforced_decisions"] + overview["blocked_decisions"] + overview["neutral_decisions"] == 7

    def test_overview_empty_db(self, tmp_path):
        db = _build_session(tmp_path)
        overview = learning_observability_service.get_overview(db)

        assert overview["total_observations"] == 0
        assert overview["total_adaptive_decisions"] == 0
        assert overview["avg_impact_score"] == 0.0
        assert overview["recency_weighted_avg_score"] == 0.0

    def test_overview_date_filter(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        overview = learning_observability_service.get_overview(
            db,
            date_from=now - timedelta(days=2),
            date_to=now,
        )

        assert overview["total_observations"] < 7
        assert overview["total_observations"] > 0


# ---------------------------------------------------------------------------
# 2. Test metricas por signature
# ---------------------------------------------------------------------------


class TestSignatureMetrics:
    def test_signature_aggregation(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_signature(db, date_to=now)

        assert len(metrics) >= 2
        sig_map = {m["signature"]: m for m in metrics}

        threshold_sig = "threshold_adjustment:low_confidence"
        domain_sig = "domain_override:prefer_hybrid:alimentos"
        assert threshold_sig in sig_map
        assert domain_sig in sig_map

        threshold_m = sig_map[threshold_sig]
        assert threshold_m["positive_count"] == 3
        assert threshold_m["negative_count"] == 1
        assert threshold_m["observation_count"] == 4
        assert threshold_m["avg_score"] > 0

        domain_m = sig_map[domain_sig]
        assert domain_m["negative_count"] == 2
        assert domain_m["neutral_count"] == 1
        assert domain_m["avg_score"] < 0

    def test_signature_filter(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_signature(
            db,
            date_to=now,
            signature_filter="threshold_adjustment:low_confidence",
        )

        assert len(metrics) == 1
        assert metrics[0]["signature"] == "threshold_adjustment:low_confidence"

    def test_signature_status_interpretation(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_signature(db, date_to=now)
        for m in metrics:
            assert m["status"] in ("reinforced", "blocked", "watch", "neutral")

    def test_signature_recency_weighted_score(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_signature(db, date_to=now)
        for m in metrics:
            assert isinstance(m["recency_weighted_score"], float)


# ---------------------------------------------------------------------------
# 3. Test metricas por family
# ---------------------------------------------------------------------------


class TestFamilyMetrics:
    def test_family_aggregation(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_family(db, date_to=now)

        assert len(metrics) >= 2
        fam_map = {m["signature_family"]: m for m in metrics}
        assert "threshold_adjustment:thresholds" in fam_map
        assert "domain_override:prefer_hybrid" in fam_map

    def test_family_filter(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_family(
            db,
            date_to=now,
            family_filter="domain_override:prefer_hybrid",
        )

        assert len(metrics) == 1
        assert metrics[0]["signature_family"] == "domain_override:prefer_hybrid"

    def test_family_has_unique_signatures_count(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_family(db, date_to=now)
        for m in metrics:
            assert "unique_signatures" in m
            assert m["unique_signatures"] >= 1


# ---------------------------------------------------------------------------
# 4. Test metricas por event_type
# ---------------------------------------------------------------------------


class TestEventTypeMetrics:
    def test_event_type_aggregation(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_event_type(db, date_to=now)

        assert len(metrics) == 2
        et_map = {m["event_type"]: m for m in metrics}
        assert "threshold_adjustment" in et_map
        assert "domain_override" in et_map

        ta = et_map["threshold_adjustment"]
        assert ta["observation_count"] == 4
        assert ta["positive_count"] == 3
        assert ta["negative_count"] == 1

    def test_event_type_filter(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        metrics = learning_observability_service.get_metrics_by_event_type(
            db, date_to=now, event_type_filter="domain_override"
        )

        assert len(metrics) == 1
        assert metrics[0]["event_type"] == "domain_override"


# ---------------------------------------------------------------------------
# 5. Test evolucion temporal
# ---------------------------------------------------------------------------


class TestTimeline:
    def test_timeline_daily(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        timeline = learning_observability_service.get_timeline(db, date_to=now)

        assert len(timeline) > 0
        for bucket in timeline:
            assert "date" in bucket
            assert "observations" in bucket
            assert "net_score" in bucket
            assert "reinforced_count" in bucket
            assert "blocked_count" in bucket
            assert "neutral_count" in bucket
            assert bucket["observations"] == bucket["reinforced_count"] + bucket["blocked_count"] + bucket["neutral_count"]

    def test_timeline_weekly(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        timeline = learning_observability_service.get_timeline(
            db, date_to=now, bucket_days=7
        )

        assert len(timeline) > 0
        assert len(timeline) <= 2  # data spans ~5 days, so 1-2 weekly buckets

    def test_timeline_signature_filter(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        timeline = learning_observability_service.get_timeline(
            db,
            date_to=now,
            signature_filter="threshold_adjustment:low_confidence",
        )

        total_obs = sum(b["observations"] for b in timeline)
        assert total_obs == 4  # solo threshold entries

    def test_timeline_empty_db(self, tmp_path):
        db = _build_session(tmp_path)
        timeline = learning_observability_service.get_timeline(db)
        assert timeline == []

    def test_timeline_sorted_by_date(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        timeline = learning_observability_service.get_timeline(db, date_to=now)
        dates = [b["date"] for b in timeline]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# 6. Test drift detection
# ---------------------------------------------------------------------------


class TestDriftDetection:
    def test_no_drift_with_stable_data(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)

        rec = _threshold_recommendation()
        for i in range(6):
            _add_impact_entry(db, recommendation=rec, status="improved", created_at=now - timedelta(days=i + 1))
        for i in range(6):
            _add_impact_entry(db, recommendation=rec, status="improved", created_at=now - timedelta(days=i + 15))
        db.commit()

        drift = learning_observability_service.detect_drift(
            db, recent_days=14, previous_days=14, reference_time=now
        )

        assert drift["drift_detected"] is False
        assert drift["drift_level"] == "none"
        assert drift["drift_signals"] == []

    def test_score_delta_drift(self, tmp_path):
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

        drift = learning_observability_service.detect_drift(
            db, recent_days=14, previous_days=14, reference_time=now
        )

        assert drift["drift_detected"] is True
        assert drift["drift_level"] in ("medium", "high")
        signal_types = {s["type"] for s in drift["drift_signals"]}
        assert "score_delta" in signal_types or "trend_inversion" in signal_types

    def test_trend_inversion_detected(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)

        rec = _domain_recommendation()
        # Previous: positive
        for i in range(4):
            _add_impact_entry(db, recommendation=rec, status="improved", created_at=now - timedelta(days=i + 15))
        _add_impact_entry(db, recommendation=rec, status="neutral", created_at=now - timedelta(days=20))
        # Recent: negative
        for i in range(4):
            _add_impact_entry(db, recommendation=rec, status="regressed", created_at=now - timedelta(days=i + 1))
        _add_impact_entry(db, recommendation=rec, status="neutral", created_at=now - timedelta(days=6))
        db.commit()

        drift = learning_observability_service.detect_drift(
            db, recent_days=14, previous_days=14, reference_time=now
        )

        assert drift["drift_detected"] is True
        signal_types = {s["type"] for s in drift["drift_signals"]}
        assert "trend_inversion" in signal_types

    def test_drift_compared_windows_structure(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        drift = learning_observability_service.detect_drift(
            db, recent_days=14, previous_days=14, reference_time=now
        )

        assert "compared_windows" in drift
        assert "recent" in drift["compared_windows"]
        assert "previous" in drift["compared_windows"]
        for window in ("recent", "previous"):
            w = drift["compared_windows"][window]
            assert "start" in w
            assert "end" in w
            assert "days" in w
            assert "total_observations" in w
            assert "avg_score" in w
            assert "block_rate" in w

    def test_drift_empty_db(self, tmp_path):
        db = _build_session(tmp_path)
        drift = learning_observability_service.detect_drift(db)

        assert drift["drift_detected"] is False
        assert drift["drift_level"] == "none"


# ---------------------------------------------------------------------------
# 7. Test trazabilidad de decisiones
# ---------------------------------------------------------------------------


class TestDecisionTraceability:
    def test_recent_decisions_structure(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)

        assert len(decisions) > 0
        for d in decisions:
            assert "id" in d
            assert "base_decision" in d
            assert "final_decision" in d
            assert "decision_mode" in d
            assert "dominant_signal" in d
            assert "explanation_layers" in d
            assert "thresholds_used" in d
            assert "impact_decision_reason" in d
            assert "impact_score_reference" in d

    def test_explanation_layers_present(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)

        decisions_with_layers = [d for d in decisions if d["explanation_layers"]]
        assert len(decisions_with_layers) > 0

        for d in decisions_with_layers:
            for layer in d["explanation_layers"]:
                assert "layer" in layer
                assert layer["layer"] in ("signature", "signature_family", "event_type")
                assert "score" in layer
                assert "effect" in layer
                assert layer["effect"] in ("reinforce", "block", "neutral")
                assert "weight" in layer

    def test_thresholds_exposed(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)
        assert len(decisions) > 0

        thresholds = decisions[0]["thresholds_used"]
        assert "signature" in thresholds
        assert "signature_family" in thresholds
        assert "event_type" in thresholds
        for level in ("signature", "signature_family", "event_type"):
            assert "negative_threshold" in thresholds[level]
            assert "positive_threshold" in thresholds[level]

    def test_decision_filter_by_event_type(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(
            db, date_to=now, event_type_filter="domain_override"
        )

        for d in decisions:
            assert d["event_type"] == "domain_override"

    def test_decision_limit(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(
            db, date_to=now, limit=2
        )

        assert len(decisions) <= 2

    def test_blocked_decision_mode(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()
        _add_impact_entry(
            db,
            recommendation=rec,
            status="regressed",
            created_at=now - timedelta(days=1),
            applied=False,
            reason="blocked_by_negative_signature_impact",
        )
        db.commit()

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)
        blocked = [d for d in decisions if d["decision_mode"] == "blocked"]
        assert len(blocked) >= 1


# ---------------------------------------------------------------------------
# 8. Test top patterns
# ---------------------------------------------------------------------------


class TestTopPatterns:
    def test_top_patterns_structure(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        patterns = learning_observability_service.get_top_patterns(db, date_to=now)

        assert "top_positive_signatures" in patterns
        assert "top_negative_signatures" in patterns
        assert "top_positive_families" in patterns
        assert "top_negative_families" in patterns

    def test_top_positive_contains_threshold(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        patterns = learning_observability_service.get_top_patterns(db, date_to=now)

        positive_sigs = [p["signature"] for p in patterns["top_positive_signatures"]]
        assert "threshold_adjustment:low_confidence" in positive_sigs

    def test_top_negative_contains_domain(self, tmp_path):
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        patterns = learning_observability_service.get_top_patterns(db, date_to=now)

        negative_sigs = [p["signature"] for p in patterns["top_negative_signatures"]]
        assert "domain_override:prefer_hybrid:alimentos" in negative_sigs


# ---------------------------------------------------------------------------
# 9. Test endpoints API
# ---------------------------------------------------------------------------


class TestAPIEndpoints:
    @pytest.fixture
    def client_and_db(self, tmp_path):
        """Crea un TestClient con DB temporal y auth bypass."""
        from fastapi import FastAPI
        from app.api.learning_observability import router

        engine = create_engine(
            f"sqlite:///{tmp_path / 'api_obs.db'}",
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

        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db_session, now)

        client = TestClient(app)
        return client, db_session

    def test_overview_endpoint(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/overview")
        assert response.status_code == 200
        data = response.json()
        assert "total_observations" in data
        assert "total_adaptive_decisions" in data
        assert data["total_observations"] == 7

    def test_signatures_endpoint(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/signatures")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_signatures_endpoint_with_filter(self, client_and_db):
        client, _ = client_and_db
        response = client.get(
            "/api/learning/observability/signatures",
            params={"event_type": "domain_override"},
        )
        assert response.status_code == 200
        data = response.json()
        for item in data:
            assert item["event_type"] == "domain_override"

    def test_families_endpoint(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/families")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_events_endpoint(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/events")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_timeline_endpoint(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/timeline")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_timeline_endpoint_weekly(self, client_and_db):
        client, _ = client_and_db
        response = client.get(
            "/api/learning/observability/timeline",
            params={"bucket_days": 7},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_drift_endpoint(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/drift")
        assert response.status_code == 200
        data = response.json()
        assert "drift_detected" in data
        assert "drift_level" in data
        assert "drift_signals" in data
        assert "compared_windows" in data

    def test_decisions_endpoint(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/decisions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_decisions_endpoint_with_limit(self, client_and_db):
        client, _ = client_and_db
        response = client.get(
            "/api/learning/observability/decisions",
            params={"limit": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 2

    def test_top_patterns_endpoint(self, client_and_db):
        client, _ = client_and_db
        response = client.get("/api/learning/observability/top-patterns")
        assert response.status_code == 200
        data = response.json()
        assert "top_positive_signatures" in data
        assert "top_negative_signatures" in data
        assert "top_positive_families" in data
        assert "top_negative_families" in data

    def test_decisions_endpoint_dominant_signal_is_dict(self, client_and_db):
        """El endpoint /decisions devuelve dominant_signal como objeto con layer/direction/score/reference."""
        client, _ = client_and_db
        response = client.get("/api/learning/observability/decisions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        for d in data:
            ds = d["dominant_signal"]
            assert isinstance(ds, dict), f"dominant_signal debe ser dict, got {type(ds)}"
            assert "layer" in ds
            assert "direction" in ds
            assert "score" in ds
            assert "reference" in ds
            assert ds["direction"] in ("positive", "negative", "neutral")


# ---------------------------------------------------------------------------
# 10. Test consistencia UTC (FASE 4.0.1-A)
# ---------------------------------------------------------------------------


class TestUTCConsistency:
    def test_utc_now_returns_naive_datetime(self):
        """utc_now() devuelve datetime naive (sin tzinfo) para compatibilidad DB."""
        from app.services.utc import utc_now

        result = utc_now()
        assert isinstance(result, datetime)
        assert result.tzinfo is None, "utc_now() debe retornar datetime naive"

    def test_utc_now_no_deprecation_warning(self):
        """utc_now() no dispara DeprecationWarning (a diferencia de datetime.utcnow())."""
        from app.services.utc import utc_now

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            utc_now()

        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0, "utc_now() no deberia emitir DeprecationWarning"

    def test_service_uses_utc_now_not_utcnow(self):
        """El servicio de observabilidad importa utc_now, no datetime.utcnow."""
        import inspect

        source = inspect.getsource(learning_observability_service)
        assert "datetime.utcnow()" not in source, "No debe haber llamadas a datetime.utcnow()"
        assert "utc_now" in source, "Debe importar y usar utc_now"

    def test_model_defaults_use_utc_now(self):
        """Los modelos de learning usan utc_now como default, no datetime.utcnow."""
        import inspect
        from app.models import learning_action_log, learning_impact_log, learning_log

        for module in (learning_action_log, learning_impact_log, learning_log):
            source = inspect.getsource(module)
            assert "default=datetime.utcnow" not in source, (
                f"{module.__name__} no debe usar default=datetime.utcnow"
            )


# ---------------------------------------------------------------------------
# 11. Test ausencia de truncamiento silencioso (FASE 4.0.1-B)
# ---------------------------------------------------------------------------


class TestNoSilentTruncation:
    def test_batch_iteration_constant_exists(self):
        """QUERY_BATCH_SIZE esta definido como constante de modulo."""
        assert hasattr(learning_observability_service, "QUERY_BATCH_SIZE")
        assert isinstance(learning_observability_service.QUERY_BATCH_SIZE, int)
        assert learning_observability_service.QUERY_BATCH_SIZE > 0

    def test_iter_function_exists(self):
        """_iter_enriched_impact_rows existe como funcion interna."""
        assert hasattr(learning_observability_service, "_iter_enriched_impact_rows")
        assert callable(learning_observability_service._iter_enriched_impact_rows)

    def test_fetches_all_rows_beyond_old_limit(self, tmp_path):
        """Si hay mas filas que el antiguo limite (500), se traen todas via batch."""
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()

        # Insertar mas filas que el batch size
        original_batch = learning_observability_service.QUERY_BATCH_SIZE
        # Usamos un batch size pequeño para hacer viable el test
        learning_observability_service.QUERY_BATCH_SIZE = 3

        try:
            for i in range(10):
                _add_impact_entry(
                    db,
                    recommendation=rec,
                    status="improved" if i % 2 == 0 else "neutral",
                    created_at=now - timedelta(hours=i + 1),
                    impact_score=0.1 * i,
                )
            db.commit()

            rows = learning_observability_service._iter_enriched_impact_rows(
                db, date_to=now
            )

            assert len(rows) == 10, (
                f"Debe traer todas las filas (10), no truncar. Got {len(rows)}"
            )
        finally:
            learning_observability_service.QUERY_BATCH_SIZE = original_batch

    def test_overview_counts_all_without_truncation(self, tmp_path):
        """get_overview cuenta todo, sin limite oculto."""
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()

        for i in range(15):
            _add_impact_entry(
                db,
                recommendation=rec,
                status="improved",
                created_at=now - timedelta(hours=i + 1),
            )
        db.commit()

        overview = learning_observability_service.get_overview(db, date_to=now)
        assert overview["total_observations"] == 15


# ---------------------------------------------------------------------------
# 12. Test dominant_signal enriquecido (FASE 4.0.1-C)
# ---------------------------------------------------------------------------


class TestEnrichedDominantSignal:
    def test_dominant_signal_returns_dict(self, tmp_path):
        """dominant_signal es un dict con layer/direction/score/reference."""
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)
        assert len(decisions) > 0

        for d in decisions:
            ds = d["dominant_signal"]
            assert isinstance(ds, dict), f"dominant_signal debe ser dict, got {type(ds)}"
            assert "layer" in ds
            assert "direction" in ds
            assert "score" in ds
            assert "reference" in ds

    def test_dominant_signal_direction_values(self, tmp_path):
        """direction solo puede ser positive, negative o neutral."""
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)
        for d in decisions:
            assert d["dominant_signal"]["direction"] in ("positive", "negative", "neutral")

    def test_dominant_signal_layer_values(self, tmp_path):
        """layer solo puede ser signature, signature_family, event_type o none."""
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)
        valid_layers = {"signature", "signature_family", "event_type", "none"}
        for d in decisions:
            assert d["dominant_signal"]["layer"] in valid_layers

    def test_dominant_signal_improved_maps_to_positive(self, tmp_path):
        """Una entry con status improved genera dominant_signal direction=positive."""
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()
        _add_impact_entry(db, recommendation=rec, status="improved", created_at=now - timedelta(days=1))
        db.commit()

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)
        assert len(decisions) >= 1
        ds = decisions[0]["dominant_signal"]
        assert ds["direction"] == "positive"
        assert ds["layer"] == "signature"
        assert ds["score"] > 0

    def test_dominant_signal_regressed_maps_to_negative(self, tmp_path):
        """Una entry con status regressed genera dominant_signal direction=negative."""
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        rec = _threshold_recommendation()
        _add_impact_entry(
            db,
            recommendation=rec,
            status="regressed",
            created_at=now - timedelta(days=1),
            applied=False,
            reason="blocked_by_negative_signature_impact",
        )
        db.commit()

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)
        assert len(decisions) >= 1
        ds = decisions[0]["dominant_signal"]
        assert ds["direction"] == "negative"
        assert ds["layer"] == "signature"
        assert ds["score"] < 0

    def test_determine_dominant_signal_no_evidence(self):
        """Sin evidencia, retorna layer=none, direction=neutral."""
        result = learning_observability_service._determine_dominant_signal({})
        assert result == {
            "layer": "none",
            "direction": "neutral",
            "score": 0.0,
            "reference": "",
        }

    def test_determine_dominant_signal_prioritizes_signature_layer(self):
        """Si signature_evidence es strong_enough, se elige sobre family y event_type."""
        score_ref = {
            "signature_evidence": {
                "key": "test:sig",
                "available": True,
                "strong_enough": True,
                "score": 0.7,
                "dominant_signal": "improved",
            },
            "signature_family_evidence": {
                "key": "test:fam",
                "available": True,
                "strong_enough": True,
                "score": -0.3,
                "dominant_signal": "regressed",
            },
        }
        result = learning_observability_service._determine_dominant_signal(score_ref)
        assert result["layer"] == "signature"
        assert result["direction"] == "positive"

    def test_determine_dominant_signal_falls_through_to_family(self):
        """Si signature no es strong_enough, pasa a signature_family."""
        score_ref = {
            "signature_evidence": {
                "key": "test:sig",
                "available": True,
                "strong_enough": False,
                "score": 0.7,
                "dominant_signal": "improved",
            },
            "signature_family_evidence": {
                "key": "test:fam",
                "available": True,
                "strong_enough": True,
                "score": -0.5,
                "dominant_signal": "regressed",
            },
        }
        result = learning_observability_service._determine_dominant_signal(score_ref)
        assert result["layer"] == "signature_family"
        assert result["direction"] == "negative"


# ---------------------------------------------------------------------------
# 13. Test pesos centralizados (FASE 4.0.1-D)
# ---------------------------------------------------------------------------


class TestCentralizedWeights:
    def test_layer_weights_constant_exists(self):
        """LAYER_WEIGHTS esta definido como constante de modulo."""
        assert hasattr(learning_observability_service, "LAYER_WEIGHTS")
        weights = learning_observability_service.LAYER_WEIGHTS
        assert isinstance(weights, dict)
        assert "signature" in weights
        assert "signature_family" in weights
        assert "event_type" in weights

    def test_layer_weights_values(self):
        """Los pesos son signature=1.0, family=0.8, event_type=0.6."""
        weights = learning_observability_service.LAYER_WEIGHTS
        assert weights["signature"] == 1.0
        assert weights["signature_family"] == 0.8
        assert weights["event_type"] == 0.6

    def test_layer_evidence_keys_constant_exists(self):
        """LAYER_EVIDENCE_KEYS tiene la lista de (layer, evidence_key) tuples."""
        assert hasattr(learning_observability_service, "LAYER_EVIDENCE_KEYS")
        keys = learning_observability_service.LAYER_EVIDENCE_KEYS
        assert isinstance(keys, list)
        assert len(keys) == 3
        layer_names = [k[0] for k in keys]
        assert layer_names == ["signature", "signature_family", "event_type"]

    def test_explanation_layers_use_centralized_weights(self, tmp_path):
        """Los explanation_layers en las decisiones usan los pesos de LAYER_WEIGHTS."""
        db = _build_session(tmp_path)
        now = datetime(2026, 3, 23, 12, 0, 0)
        _populate_test_data(db, now)

        decisions = learning_observability_service.get_recent_decisions(db, date_to=now)
        decisions_with_layers = [d for d in decisions if d["explanation_layers"]]
        assert len(decisions_with_layers) > 0

        expected_weights = learning_observability_service.LAYER_WEIGHTS
        for d in decisions_with_layers:
            for layer in d["explanation_layers"]:
                layer_name = layer["layer"]
                expected_weight = expected_weights.get(layer_name, 0.5)
                assert layer["weight"] == expected_weight, (
                    f"Layer {layer_name} weight should be {expected_weight}, got {layer['weight']}"
                )

    def test_build_explanation_layers_applies_weights(self):
        """_build_explanation_layers aplica LAYER_WEIGHTS correctamente."""
        score_ref = {
            "signature_evidence": {
                "key": "sig:test",
                "score": 0.5,
                "available": True,
                "strong_enough": True,
                "raw_total": 5,
                "weighted_total": 4.0,
                "memory_confidence": 0.8,
            },
            "signature_family_evidence": {
                "key": "fam:test",
                "score": 0.3,
                "available": True,
                "strong_enough": False,
                "raw_total": 2,
                "weighted_total": 1.0,
                "memory_confidence": 0.3,
            },
            "event_type_evidence": {
                "key": "evt:test",
                "score": -0.1,
                "available": True,
                "strong_enough": False,
                "raw_total": 1,
                "weighted_total": 0.5,
                "memory_confidence": 0.1,
            },
        }

        layers = learning_observability_service._build_explanation_layers(score_ref)
        assert len(layers) == 3

        weight_map = {l["layer"]: l["weight"] for l in layers}
        assert weight_map["signature"] == 1.0
        assert weight_map["signature_family"] == 0.8
        assert weight_map["event_type"] == 0.6

    def test_weights_not_hardcoded_in_build_layers(self):
        """Si se modifica LAYER_WEIGHTS, _build_explanation_layers respeta el nuevo valor."""
        original = learning_observability_service.LAYER_WEIGHTS.copy()
        try:
            learning_observability_service.LAYER_WEIGHTS["signature"] = 0.99
            score_ref = {
                "signature_evidence": {
                    "key": "sig:test",
                    "score": 0.5,
                    "available": True,
                    "strong_enough": True,
                    "raw_total": 5,
                    "weighted_total": 4.0,
                    "memory_confidence": 0.8,
                },
            }
            layers = learning_observability_service._build_explanation_layers(score_ref)
            assert len(layers) == 1
            assert layers[0]["weight"] == 0.99
        finally:
            learning_observability_service.LAYER_WEIGHTS.update(original)
