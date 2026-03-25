from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.legal_query import LegalQueryResponse
from app.db.database import Base
import app.models.learning_log  # noqa: F401
from app.models.learning_log import LearningLog
from app.services import learning_log_service, learning_metrics_service
from legal_engine.orchestrator_schema import (
    FinalOutput,
    NormalizedOrchestratorInput,
    OrchestratorClassification,
    OrchestratorDecision,
    OrchestratorResult,
    OrchestratorTimings,
    RetrievalBundle,
    StrategyBundle,
)


class _Payload:
    def __init__(self, query: str = "consulta de alimentos") -> None:
        self.query = query
        self.jurisdiction = "jujuy"
        self.forum = "familia"


def _build_result(
    *,
    confidence_score: float = 0.61,
    decision_confidence: float = 0.72,
    fallback_used: bool = False,
    documents_considered: int = 2,
    warnings: list[str] | None = None,
    case_domain: str = "alimentos",
    strategy_mode: str = "conservative",
) -> OrchestratorResult:
    warnings = warnings or []
    return OrchestratorResult(
        pipeline_version="beta-orchestrator-v1",
        normalized_input=NormalizedOrchestratorInput(
            request_id="req-learning",
            query="consulta de alimentos",
            jurisdiction="jujuy",
            forum="familia",
            facts={"monto": 100},
            metadata={"request_id": "req-learning"},
        ),
        decision=OrchestratorDecision(
            retrieval_mode="offline",
            strategy_mode=strategy_mode,
            pipeline_mode="light" if documents_considered == 0 else "full",
            use_jurisprudence=False,
            use_argument_generation=True,
            decision_confidence=decision_confidence,
        ),
        classification=OrchestratorClassification(
            action_slug="alimentos_hijos",
            action_label="Alimentos",
            case_domain=case_domain,
            jurisdiction="jujuy",
            forum="familia",
        ),
        retrieval=RetrievalBundle(
            source_mode="offline",
            documents_considered=documents_considered,
        ),
        strategy=StrategyBundle(
            strategy_mode=strategy_mode,
            dominant_factor="norma",
            blocking_factor="none",
            execution_readiness="lista",
            confidence_score=confidence_score,
            confidence_label="medium" if confidence_score >= 0.5 else "low",
            fallback_used=fallback_used,
            fallback_reason="fallback interno" if fallback_used else "",
            raw={"ambiguity_risk": decision_confidence < 0.5},
        ),
        final_output=FinalOutput(
            request_id="req-learning",
            response_text="Respuesta final.",
            pipeline_version="beta-orchestrator-v1",
            case_domain=case_domain,
            action_slug="alimentos_hijos",
            source_mode="offline",
            documents_considered=documents_considered,
            strategy_mode=strategy_mode,
            dominant_factor="norma",
            blocking_factor="none",
            execution_readiness="lista",
            confidence_score=confidence_score,
            confidence_label="medium" if confidence_score >= 0.5 else "low",
            fallback_used=fallback_used,
            fallback_reason="fallback interno" if fallback_used else "",
            warnings=warnings,
            api_payload={},
        ),
        timings=OrchestratorTimings(total_ms=18),
        pipeline_payload={"query": "consulta de alimentos"},
    )


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning_log_service.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def test_build_quality_flags_detects_low_confidence():
    flags = learning_log_service.build_quality_flags(_build_result(confidence_score=0.4))

    assert flags["low_confidence"] is True
    assert flags["severity_score"] == 0.3
    assert flags["manual_review_recommended"] is False


def test_build_quality_flags_detects_fallback():
    flags = learning_log_service.build_quality_flags(_build_result(fallback_used=True))

    assert flags["used_fallback"] is True
    assert flags["severity_score"] == 0.2
    assert flags["manual_review_recommended"] is False


def test_build_quality_flags_detects_empty_retrieval():
    flags = learning_log_service.build_quality_flags(_build_result(documents_considered=0))

    assert flags["empty_retrieval"] is True
    assert flags["light_mode_used"] is True


def test_manual_review_recommended_becomes_true_when_expected():
    flags = learning_log_service.build_quality_flags(
        _build_result(confidence_score=0.44, fallback_used=True)
    )

    assert flags["severity_score"] == 0.5
    assert flags["manual_review_recommended"] is True
    assert flags["review_reasons"] == ["low_confidence", "used_fallback"]


def test_save_learning_log_stores_normalized_structured_fields(tmp_path):
    db = _build_session(tmp_path)
    result = _build_result(
        confidence_score=0.44,
        decision_confidence=0.72,
        fallback_used=True,
        warnings=["a", "b", "c"],
    )

    stored = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=result,
        response_time_ms=123,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    persisted = db.get(LearningLog, stored.id)
    assert persisted is not None
    assert persisted.request_id == "req-learning"
    assert persisted.user_id == "user-1"
    assert persisted.case_domain == "alimentos"
    assert persisted.action_slug == "alimentos_hijos"
    assert persisted.strategy_mode == "conservative"
    assert persisted.decision_confidence == 0.72
    assert persisted.confidence_score == 0.44
    assert persisted.fallback_used is True
    assert persisted.documents_considered == 2
    assert persisted.warnings_count == 3
    assert persisted.processing_time_ms == 123
    assert persisted.severity_score == 0.6
    assert persisted.reviewed_by_user is False
    assert persisted.reviewed_by_admin is False
    assert persisted.learning_version == "v1"
    assert persisted.orchestrator_version == "beta-orchestrator-v1"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{2}", persisted.time_bucket) is not None
    payload = persisted.to_dict()
    assert payload["quality_flags_json"]["low_confidence"] is True
    assert payload["quality_flags_json"]["used_fallback"] is True
    assert payload["quality_flags_json"]["severity_score"] == 0.6
    assert payload["quality_flags_json"]["review_reasons"] == [
        "low_confidence",
        "used_fallback",
        "high_warning_count",
    ]


def test_time_bucket_is_timestamp_based_and_not_response_time_based(tmp_path):
    db = _build_session(tmp_path)
    result = _build_result()

    stored_fast = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=result,
        response_time_ms=10,
        orchestrator_version="beta-orchestrator-v1",
    )
    stored_slow = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=result,
        response_time_ms=999999,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{2}", stored_fast.time_bucket) is not None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{2}", stored_slow.time_bucket) is not None


def test_recalibrated_severity_preserves_granularity():
    flags = learning_log_service.build_quality_flags(
        _build_result(confidence_score=0.44, fallback_used=True, warnings=["a", "b", "c"])
    )

    assert flags["severity_score"] == 0.6
    assert flags["severity_score"] < 1.0


def test_ambiguous_query_increases_severity():
    result = _build_result(confidence_score=0.61, decision_confidence=0.72)
    result.strategy.raw["ambiguity_risk"] = True

    flags = learning_log_service.build_quality_flags(result)

    assert flags["ambiguous_query"] is True
    assert flags["severity_score"] == 0.2
    assert flags["manual_review_recommended"] is False
    assert flags["review_reasons"] == ["ambiguous_query"]


def test_ambiguous_query_no_longer_depends_on_low_decision_confidence():
    result = _build_result(confidence_score=0.61, decision_confidence=0.41)
    result.strategy.raw["ambiguity_risk"] = False
    flags = learning_log_service.build_quality_flags(result)

    assert flags["low_decision_confidence"] is True
    assert flags["ambiguous_query"] is False
    assert flags["severity_score"] == 0.3
    assert flags["review_reasons"] == ["low_decision_confidence"]


def test_low_confidence_plus_fallback_reaches_manual_review_threshold():
    flags = learning_log_service.build_quality_flags(
        _build_result(confidence_score=0.44, fallback_used=True)
    )

    assert flags["severity_score"] == 0.5
    assert flags["manual_review_recommended"] is True


def test_review_reasons_are_sorted_by_impact():
    result = _build_result(
        confidence_score=0.44,
        decision_confidence=0.41,
        fallback_used=True,
        warnings=["a", "b", "c"],
    )
    result.strategy.raw["ambiguity_risk"] = True

    flags = learning_log_service.build_quality_flags(result)

    assert flags["review_reasons"] == [
        "low_confidence",
        "low_decision_confidence",
        "ambiguous_query",
        "used_fallback",
        "high_warning_count",
    ]


def test_manual_review_recommended_is_false_for_ambiguous_query_alone():
    result = _build_result(confidence_score=0.61, decision_confidence=0.72)
    result.strategy.raw["ambiguity_risk"] = True

    flags = learning_log_service.build_quality_flags(result)

    assert flags["severity_score"] == 0.2
    assert flags["low_confidence"] is False
    assert flags["manual_review_recommended"] is False


def test_submit_feedback_rejects_empty_payload(tmp_path):
    db = _build_session(tmp_path)
    stored = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    try:
        learning_log_service.submit_learning_feedback(db, log_id=stored.id)
        assert False, "Se esperaba ValueError por payload vacio"
    except ValueError as exc:
        assert "al menos un campo de feedback" in str(exc)


def test_submit_feedback_updates_explicit_feedback_fields(tmp_path):
    db = _build_session(tmp_path)
    stored = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    updated = learning_log_service.submit_learning_feedback(
        db,
        log_id=stored.id,
        user_feedback_score=4,
        is_user_feedback_positive=True,
        feedback_comment="Buena respuesta.",
    )

    assert updated is not None
    assert updated.user_feedback_score == 4
    assert updated.is_user_feedback_positive is True
    assert updated.feedback_comment == "Buena respuesta."
    assert updated.reviewed_by_user is True
    assert updated.reviewed_by_admin is False
    assert updated.feedback_submitted_at is not None


def test_submit_feedback_stores_derived_feedback_signals(tmp_path):
    db = _build_session(tmp_path)
    stored = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(case_domain="familia", strategy_mode="conservative"),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    updated = learning_log_service.submit_learning_feedback(
        db,
        log_id=stored.id,
        user_feedback_score=2,
        is_user_feedback_positive=False,
        corrected_domain="alimentos",
        corrected_strategy_mode="cautious",
        feedback_comment="Clasificacion ajustada.",
        reviewed_by_admin=True,
    )

    assert updated is not None
    payload = updated.to_dict()["quality_flags_json"]["review_feedback"]
    assert payload["corrected_domain"] == "alimentos"
    assert payload["corrected_strategy_mode"] == "cautious"
    assert payload["feedback_comment"] == "Clasificacion ajustada."
    assert payload["feedback_is_negative"] is True
    assert payload["feedback_has_domain_correction"] is True
    assert payload["feedback_has_strategy_correction"] is True
    assert payload["feedback_is_strong_signal"] is True
    assert payload["feedback_is_positive_confirmation"] is False


def test_positive_feedback_confirmation_is_derived_without_corrections(tmp_path):
    db = _build_session(tmp_path)
    stored = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(case_domain="alimentos", strategy_mode="conservative"),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    updated = learning_log_service.submit_learning_feedback(
        db,
        log_id=stored.id,
        user_feedback_score=5,
        is_user_feedback_positive=True,
        feedback_comment="Correcto",
    )

    payload = updated.to_dict()["quality_flags_json"]["review_feedback"]
    assert payload["feedback_is_negative"] is False
    assert payload["feedback_has_domain_correction"] is False
    assert payload["feedback_has_strategy_correction"] is False
    assert payload["feedback_is_strong_signal"] is False
    assert payload["feedback_is_positive_confirmation"] is True


def test_feedback_score_validation_works(tmp_path):
    db = _build_session(tmp_path)
    stored = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    try:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=stored.id,
            user_feedback_score=6,
        )
        assert False, "Se esperaba ValueError por score invalido"
    except ValueError as exc:
        assert "user_feedback_score" in str(exc)


def test_severity_distribution_matches_expected_buckets(tmp_path):
    db = _build_session(tmp_path)
    low = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    medium = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    high = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True, warnings=["a", "b", "c"]),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    assert low.severity_score == 0.0
    assert medium.severity_score == 0.5
    assert high.severity_score == 0.6
    assert learning_metrics_service.get_severity_distribution(db) == {
        "low": 1,
        "medium": 1,
        "high": 1,
    }


def test_learning_summary_supports_temporal_filter(tmp_path):
    db = _build_session(tmp_path)
    recent = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    older = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v2",
    )
    db.commit()

    older.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db.commit()

    summary = learning_metrics_service.get_learning_summary(db, last_hours=24)

    assert recent.orchestrator_version == "beta-orchestrator-v1"
    assert older.orchestrator_version == "beta-orchestrator-v2"
    assert summary["total_queries"] == 1
    assert summary["window_hours"] == 24
    assert summary["by_orchestrator_version"] == {"beta-orchestrator-v1": 1}


def test_learning_summary_includes_orchestrator_version_summary(tmp_path):
    db = _build_session(tmp_path)
    learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True, warnings=["a", "b", "c"]),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v2",
    )
    db.commit()

    summary = learning_metrics_service.get_learning_summary(db)

    assert summary["orchestrator_version_summary"]["versions"] == {
        "beta-orchestrator-v1": 1,
        "beta-orchestrator-v2": 1,
    }
    assert summary["orchestrator_version_summary"]["average_severity_by_version"] == {
        "beta-orchestrator-v1": 0.5,
        "beta-orchestrator-v2": 0.6,
    }
    assert summary["orchestrator_version_summary"]["version_share"] == {
        "beta-orchestrator-v1": 0.5,
        "beta-orchestrator-v2": 0.5,
    }
    assert summary["orchestrator_version_summary"]["severity_ranking"] == [
        {"version": "beta-orchestrator-v2", "average_severity": 0.6, "count": 1},
        {"version": "beta-orchestrator-v1", "average_severity": 0.5, "count": 1},
    ]


def test_feedback_summary_includes_new_rates_and_bucket_success_metrics(tmp_path):
    db = _build_session(tmp_path)
    first = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(case_domain="alimentos", strategy_mode="conservative"),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    second = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(case_domain="familia", strategy_mode="cautious"),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v2",
    )
    db.commit()

    learning_log_service.submit_learning_feedback(
        db,
        log_id=first.id,
        user_feedback_score=5,
        is_user_feedback_positive=True,
    )
    learning_log_service.submit_learning_feedback(
        db,
        log_id=second.id,
        user_feedback_score=2,
        is_user_feedback_positive=False,
        corrected_domain="alimentos",
        corrected_strategy_mode="conservative",
    )

    summary = learning_metrics_service.get_feedback_summary(db)

    assert summary["total_feedback_items"] == 2
    assert summary["average_feedback_score"] == 3.5
    assert summary["success_rate"] == 0.5
    assert summary["negative_feedback_rate"] == 0.5
    assert summary["strong_signal_rate"] == 0.5
    assert summary["domain_correction_rate"] == 0.5
    assert summary["strategy_correction_rate"] == 0.5
    assert summary["domain_mismatch_rate"] == 0.5
    assert summary["strategy_mismatch_rate"] == 0.5
    assert summary["positive_confirmation_rate"] == 0.5
    assert summary["by_case_domain"] == {"alimentos": 1, "familia": 1}
    assert summary["by_orchestrator_version"] == {
        "beta-orchestrator-v1": 1,
        "beta-orchestrator-v2": 1,
    }
    assert summary["success_rate_by_domain"] == {"alimentos": 1.0, "familia": 0.0}
    assert summary["success_rate_by_orchestrator_version"] == {
        "beta-orchestrator-v1": 1.0,
        "beta-orchestrator-v2": 0.0,
    }


def test_get_time_series_severity_returns_bucketed_rows(tmp_path):
    db = _build_session(tmp_path)
    log_a = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    log_b = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True, warnings=["a", "b", "c"]),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    db.commit()

    log_a.time_bucket = "2026-03-23-14"
    log_b.time_bucket = "2026-03-23-14"
    db.commit()

    rows = learning_metrics_service.get_time_series_severity(db)

    assert rows == [
        {
            "time_bucket": "2026-03-23-14",
            "count": 2,
            "average_severity": 0.55,
            "fallback_rate": 1.0,
        }
    ]


def test_severity_ranking_orders_versions_by_average_severity_descending(tmp_path):
    db = _build_session(tmp_path)
    learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v1",
    )
    learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(),
        orchestrator_result=_build_result(confidence_score=0.44, fallback_used=True, warnings=["a", "b", "c"]),
        response_time_ms=100,
        orchestrator_version="beta-orchestrator-v2",
    )
    db.commit()

    summary = learning_metrics_service.get_orchestrator_version_summary(db)

    assert summary["severity_ranking"] == [
        {"version": "beta-orchestrator-v2", "average_severity": 0.6, "count": 1},
        {"version": "beta-orchestrator-v1", "average_severity": 0.5, "count": 1},
    ]


def test_legal_query_response_exposes_feedback_linkage_keys():
    fields = LegalQueryResponse.model_fields

    assert "learning_log_id" in fields
    assert "request_id" in fields
    assert "orchestrator_version" in fields
