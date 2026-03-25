from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_log  # noqa: F401
import app.models.orchestrator_config_snapshot  # noqa: F401
import app.models.orchestrator_tuning_event  # noqa: F401
from app.models.orchestrator_config_snapshot import OrchestratorConfigSnapshot
from app.models.orchestrator_tuning_event import OrchestratorTuningEvent
from app.services import adaptive_learning_service, learning_log_service, orchestrator_config_service
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
from legal_engine.query_orchestrator import QueryOrchestrator


class _Payload:
    def __init__(self, query: str = "consulta de alimentos") -> None:
        self.query = query
        self.jurisdiction = "jujuy"
        self.forum = "familia"


def _build_result(
    *,
    query: str = "consulta de alimentos",
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
            request_id=f"req-{query.replace(' ', '-')}",
            query=query,
            jurisdiction="jujuy",
            forum="familia",
            facts={},
            metadata={},
        ),
        decision=OrchestratorDecision(
            retrieval_mode="offline",
            strategy_mode=strategy_mode,
            pipeline_mode="full",
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
            raw={},
        ),
        final_output=FinalOutput(
            request_id=f"req-{query.replace(' ', '-')}",
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
        pipeline_payload={},
    )


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'adaptive_learning_service.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()


def _persist_log(
    db: Session,
    *,
    query: str,
    fallback_used: bool,
    confidence_score: float,
    orchestrator_version: str,
    warnings: list[str] | None = None,
    case_domain: str = "alimentos",
    strategy_mode: str = "conservative",
) -> object:
    log = learning_log_service.save_learning_log(
        db,
        user_id="user-1",
        session_id="session-1",
        conversation_id="conversation-1",
        payload=_Payload(query),
        orchestrator_result=_build_result(
            query=query,
            fallback_used=fallback_used,
            confidence_score=confidence_score,
            warnings=warnings,
            case_domain=case_domain,
            strategy_mode=strategy_mode,
        ),
        response_time_ms=100,
        orchestrator_version=orchestrator_version,
    )
    db.flush()
    return log


def _create_domain_override_event(db: Session) -> OrchestratorTuningEvent:
    event = next(
        item
        for item in adaptive_learning_service.analyze_learning_system(db)
        if item.event_type == "domain_override"
    )
    adaptive_learning_service.approve_tuning_event(db, event.id)
    db.refresh(event)
    return event


def test_recommendation_includes_affected_queries_and_percentage(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.61,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    event = next(
        item for item in adaptive_learning_service.analyze_learning_system(db) if item.event_type == "domain_override"
    )
    evidence = event.to_dict()["evidence_json"]

    assert evidence["affected_queries"] == 3
    assert evidence["affected_percentage"] == 1.0


def test_tuning_event_persists_priority(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.61,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    event = next(
        item for item in adaptive_learning_service.analyze_learning_system(db) if item.event_type == "domain_override"
    )

    assert event.priority > 0.0


def test_events_are_listed_ordered_by_priority(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    low = OrchestratorTuningEvent(
        event_type="domain_review",
        status="proposed",
        title="Low priority",
        description="low",
        evidence_json="{}",
        proposed_changes_json="{}",
        confidence_score=0.4,
        priority=0.3,
        source_version="v1",
        target_version="v1-proposal",
    )
    high = OrchestratorTuningEvent(
        event_type="version_alert",
        status="approved",
        title="High priority",
        description="high",
        evidence_json="{}",
        proposed_changes_json="{}",
        confidence_score=0.8,
        priority=0.9,
        source_version="v1",
        target_version="v2",
    )
    db.add(low)
    db.add(high)
    db.commit()

    items = adaptive_learning_service.list_tuning_events(db, limit=10)

    assert items[0]["title"] == "High priority"
    assert items[1]["title"] == "Low priority"


def test_events_apply_priority_decay_over_time(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    now = datetime.utcnow()
    older = OrchestratorTuningEvent(
        event_type="domain_review",
        status="proposed",
        title="Older high raw priority",
        description="older",
        evidence_json="{}",
        proposed_changes_json="{}",
        confidence_score=0.9,
        priority=0.9,
        source_version="v1",
        target_version="v2",
    )
    newer = OrchestratorTuningEvent(
        event_type="domain_review",
        status="proposed",
        title="Newer medium raw priority",
        description="newer",
        evidence_json="{}",
        proposed_changes_json="{}",
        confidence_score=0.7,
        priority=0.7,
        source_version="v1",
        target_version="v2",
    )
    db.add(older)
    db.add(newer)
    db.commit()

    older.created_at = now - timedelta(hours=72)
    newer.created_at = now
    db.commit()

    items = adaptive_learning_service.list_tuning_events(db, limit=10)

    assert items[0]["title"] == "Newer medium raw priority"
    assert items[0]["effective_priority"] > items[1]["effective_priority"]


def test_applying_event_stores_baseline_evaluation_seed_data(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.61,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    event = _create_domain_override_event(db)
    result = adaptive_learning_service.apply_tuning_event(db, event.id)
    observed = result["event"]["observed_effect_json"]

    assert result["event"]["status"] == "applied"
    assert result["event"]["evaluation_status"] == "pending"
    assert observed["pre_apply_summary"]["total_queries"] >= 3
    assert "applied_at" in observed
    assert "pre_apply_time_series_excerpt" in observed


def test_evaluate_tuning_event_effect_marks_insufficient_data_when_post_sample_is_small(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.44,
            orchestrator_version="beta-orchestrator-v1",
            warnings=["a", "b", "c"],
        )
    db.commit()

    event = _create_domain_override_event(db)
    adaptive_learning_service.apply_tuning_event(db, event.id)
    evaluated = adaptive_learning_service.evaluate_tuning_event_effect(db, event.id, window_hours=24)

    assert evaluated["evaluation_status"] == "insufficient_data"
    assert evaluated["observed_effect_json"]["evaluation_block_reason"] in {
        "minimum_time_lag_not_reached",
        "insufficient_post_apply_samples",
    }


def test_evaluate_tuning_event_effect_respects_minimum_time_lag(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.44,
            orchestrator_version="beta-orchestrator-v1",
            warnings=["a", "b", "c"],
        )
    db.commit()

    event = _create_domain_override_event(db)
    applied = adaptive_learning_service.apply_tuning_event(db, event.id)
    evaluated = adaptive_learning_service.evaluate_tuning_event_effect(db, event.id, window_hours=24)

    assert evaluated["evaluation_status"] == "insufficient_data"
    assert evaluated["observed_effect_json"]["evaluation_block_reason"] == "minimum_time_lag_not_reached"
    assert applied["event"]["observed_effect_json"]["applied_at"] == evaluated["observed_effect_json"]["applied_at"]


def test_evaluate_tuning_event_effect_can_mark_improved(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta critica {idx}",
            fallback_used=True,
            confidence_score=0.44,
            orchestrator_version="beta-orchestrator-v1",
            warnings=["a", "b", "c"],
        )
    db.commit()

    event = _create_domain_override_event(db)
    applied = adaptive_learning_service.apply_tuning_event(db, event.id)
    applied_at = adaptive_learning_service._parse_iso_datetime(  # noqa: SLF001
        applied["event"]["observed_effect_json"]["applied_at"]
    )
    assert applied_at is not None
    applied_event = db.get(OrchestratorTuningEvent, event.id)
    assert applied_event is not None
    observed_effect = adaptive_learning_service._json_loads(applied_event.observed_effect_json)  # noqa: SLF001
    observed_effect["applied_at"] = (applied_at - timedelta(hours=7)).isoformat()
    applied_event.observed_effect_json = adaptive_learning_service._json_dumps(observed_effect)  # noqa: SLF001

    for idx in range(20):
        log = _persist_log(
            db,
            query=f"consulta mejorada {idx}",
            fallback_used=False,
            confidence_score=0.85,
            orchestrator_version="beta-orchestrator-v1",
        )
        log.created_at = applied_at + timedelta(minutes=idx)
    db.commit()

    evaluated = adaptive_learning_service.evaluate_tuning_event_effect(db, event.id, window_hours=24)

    assert evaluated["evaluation_status"] == "improved"
    assert evaluated["observed_effect_json"]["metric_deltas"]["average_severity_delta"] < 0.0


def test_evaluate_tuning_event_effect_can_mark_regressed(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta estable {idx}",
            fallback_used=False,
            confidence_score=0.85,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    event = OrchestratorTuningEvent(
        event_type="threshold_adjustment",
        status="approved",
        title="Regresion controlada",
        description="Evento manual para evaluar regresion.",
        evidence_json="{}",
        proposed_changes_json='{"low_confidence_threshold": 0.55}',
        confidence_score=0.7,
        priority=0.6,
        source_version="v1",
        target_version="v2",
    )
    db.add(event)
    db.commit()
    applied = adaptive_learning_service.apply_tuning_event(db, event.id)
    applied_at = adaptive_learning_service._parse_iso_datetime(  # noqa: SLF001
        applied["event"]["observed_effect_json"]["applied_at"]
    )
    assert applied_at is not None
    applied_event = db.get(OrchestratorTuningEvent, event.id)
    assert applied_event is not None
    observed_effect = adaptive_learning_service._json_loads(applied_event.observed_effect_json)  # noqa: SLF001
    observed_effect["applied_at"] = (applied_at - timedelta(hours=7)).isoformat()
    applied_event.observed_effect_json = adaptive_learning_service._json_dumps(observed_effect)  # noqa: SLF001

    for idx in range(20):
        log = _persist_log(
            db,
            query=f"consulta empeorada {idx}",
            fallback_used=True,
            confidence_score=0.44,
            orchestrator_version="beta-orchestrator-v1",
            warnings=["a", "b", "c"],
        )
        log.created_at = applied_at + timedelta(minutes=idx)
    db.commit()

    evaluated = adaptive_learning_service.evaluate_tuning_event_effect(db, event.id, window_hours=24)

    assert evaluated["evaluation_status"] == "regressed"
    assert evaluated["observed_effect_json"]["metric_deltas"]["average_severity_delta"] > 0.0


def test_tuning_event_dict_includes_priority_and_evaluation_fields(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    event = OrchestratorTuningEvent(
        event_type="domain_review",
        status="proposed",
        title="Event fields",
        description="event fields",
        evidence_json="{}",
        proposed_changes_json="{}",
        confidence_score=0.6,
        priority=0.7,
        evaluation_status="pending",
        observed_effect_json='{"seed":true}',
        source_version="v1",
        target_version="v2",
    )
    db.add(event)
    db.commit()

    item = adaptive_learning_service.list_tuning_events(db, limit=1)[0]

    assert item["priority"] == 0.7
    assert "effective_priority" in item
    assert item["evaluation_status"] == "pending"
    assert item["observed_effect_json"] == {"seed": True}


def test_regressed_event_locks_similar_future_recommendations(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    locked = OrchestratorTuningEvent(
        event_type="domain_override",
        status="applied",
        title="Locked domain override",
        description="locked",
        evidence_json='{"domain":"alimentos"}',
        proposed_changes_json='{"prefer_hybrid_domains_add":["alimentos"]}',
        confidence_score=0.8,
        priority=0.8,
        evaluation_status="regressed",
        observed_effect_json="{}",
        source_version="v1",
        target_version="v2",
    )
    db.add(locked)
    db.commit()

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.61,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    events = adaptive_learning_service.analyze_learning_system(db)

    assert not any(
        event.event_type == "domain_override" and event.id != locked.id
        for event in events
    )


def test_drift_summary_aggregates_improvements_and_regressions(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    improved = OrchestratorTuningEvent(
        event_type="domain_review",
        status="applied",
        title="Improved",
        description="improved",
        evidence_json="{}",
        proposed_changes_json="{}",
        confidence_score=0.6,
        priority=0.6,
        evaluation_status="improved",
        observed_effect_json="{}",
        source_version="v1",
        target_version="v2",
    )
    regressed = OrchestratorTuningEvent(
        event_type="domain_review",
        status="applied",
        title="Regressed",
        description="regressed",
        evidence_json="{}",
        proposed_changes_json="{}",
        confidence_score=0.6,
        priority=0.6,
        evaluation_status="regressed",
        observed_effect_json="{}",
        source_version="v1",
        target_version="v2",
    )
    db.add(improved)
    db.add(regressed)
    db.commit()

    summary = adaptive_learning_service.get_adaptive_drift_summary(db)

    assert summary["applied_events"] == 2
    assert summary["evaluation_counts"]["improved"] == 1
    assert summary["evaluation_counts"]["regressed"] == 1
    assert summary["improvement_rate"] == 0.5
    assert summary["regression_rate"] == 0.5


def test_high_severity_version_generates_version_alert(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta estable {idx}",
            fallback_used=False,
            confidence_score=0.8,
            orchestrator_version="beta-orchestrator-v1",
            warnings=[],
        )
        _persist_log(
            db,
            query=f"consulta inestable {idx}",
            fallback_used=True,
            confidence_score=0.44,
            orchestrator_version="beta-orchestrator-v2",
            warnings=["a", "b", "c"],
        )
    db.commit()

    events = adaptive_learning_service.analyze_learning_system(db)

    assert any(event.event_type == "version_alert" for event in events)


def test_duplicate_recommendations_are_not_duplicated_repeatedly(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.61,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    adaptive_learning_service.analyze_learning_system(db)
    first = adaptive_learning_service.list_tuning_events(db)
    adaptive_learning_service.analyze_learning_system(db)
    second = adaptive_learning_service.list_tuning_events(db)

    assert len(first) == len(second)


def test_invalid_config_change_is_rejected(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    event = OrchestratorTuningEvent(
        event_type="threshold_adjustment",
        status="approved",
        title="Cambio invalido",
        description="Debe rechazarse por thresholds fuera de rango.",
        evidence_json="{}",
        proposed_changes_json='{"low_confidence_threshold": 0.99}',
        confidence_score=0.8,
        priority=0.8,
        source_version="v1",
        target_version="v1-invalid",
    )
    db.add(event)
    db.commit()

    try:
        adaptive_learning_service.apply_tuning_event(db, event.id)
        assert False, "Se esperaba ValueError"
    except ValueError as exc:
        assert "low_confidence_threshold" in str(exc)

    persisted = db.get(OrchestratorTuningEvent, event.id)
    assert persisted is not None
    assert persisted.status == "invalidated"


def test_applied_event_can_be_rolled_back(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.61,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    event = _create_domain_override_event(db)
    adaptive_learning_service.apply_tuning_event(db, event.id)
    result = adaptive_learning_service.rollback_tuning_event(db, event.id)

    assert result["event"]["status"] == "rolled_back"
    assert "alimentos" not in result["config"]["prefer_hybrid_domains"]


def test_rollback_restores_previous_config(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    base_config = orchestrator_config_service.load_orchestrator_config()
    base_config.force_full_pipeline_domains.append("familia")
    orchestrator_config_service.save_orchestrator_config(base_config)

    event = OrchestratorTuningEvent(
        event_type="domain_override",
        status="approved",
        title="Agregar alimentos",
        description="Agregar preferencia hibrida.",
        evidence_json='{"domain":"alimentos"}',
        proposed_changes_json='{"prefer_hybrid_domains_add":["alimentos"]}',
        confidence_score=0.8,
        priority=0.8,
        source_version="v1",
        target_version="v2",
    )
    db.add(event)
    db.commit()

    adaptive_learning_service.apply_tuning_event(db, event.id)
    rollback = adaptive_learning_service.rollback_tuning_event(db, event.id)

    assert rollback["config"]["force_full_pipeline_domains"] == ["familia"]
    assert rollback["config"]["prefer_hybrid_domains"] == []


def test_duplicate_domain_override_recommendation_is_not_duplicated_semantically(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    first = OrchestratorTuningEvent(
        event_type="domain_override",
        status="approved",
        title="Preferir retrieval hibrido en alimentos",
        description="Existente",
        evidence_json='{"domain":"ALIMENTOS"}',
        proposed_changes_json='{"prefer_hybrid_domains_add":["alimentos"]}',
        confidence_score=0.8,
        priority=0.8,
        source_version="v1",
        target_version="v1-proposal",
    )
    db.add(first)
    db.commit()

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.61,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    events = adaptive_learning_service.analyze_learning_system(db)
    domain_events = [event for event in events if event.event_type == "domain_override"]

    assert len(domain_events) == 1
    assert domain_events[0].id == first.id


def test_event_status_transitions_behave_correctly(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    event = OrchestratorTuningEvent(
        event_type="threshold_adjustment",
        status="proposed",
        title="Revisar thresholds",
        description="Transiciones validas e invalidas.",
        evidence_json="{}",
        proposed_changes_json='{"low_confidence_threshold": 0.55}',
        confidence_score=0.7,
        priority=0.6,
        source_version="v1",
        target_version="v2",
    )
    db.add(event)
    db.commit()

    approved = adaptive_learning_service.approve_tuning_event(db, event.id)
    assert approved["status"] == "approved"

    try:
        adaptive_learning_service.approve_tuning_event(db, event.id)
        assert False, "Se esperaba ValueError por transicion invalida"
    except ValueError as exc:
        assert "proposed" in str(exc)

    applied = adaptive_learning_service.apply_tuning_event(db, event.id)
    assert applied["event"]["status"] == "applied"

    try:
        adaptive_learning_service.reject_tuning_event(db, event.id)
        assert False, "Se esperaba ValueError por transicion invalida"
    except ValueError as exc:
        assert "proposed o approved" in str(exc)


def test_low_feedback_domain_generates_domain_review_recommendation(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    created_ids: list[str] = []
    for idx in range(3):
        log = _persist_log(
            db,
            query=f"consulta familia {idx}",
            fallback_used=False,
            confidence_score=0.7,
            orchestrator_version="beta-orchestrator-v1",
            case_domain="familia",
        )
        created_ids.append(log.id)
    db.commit()

    for log_id in created_ids:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=2,
            is_user_feedback_positive=False,
        )

    events = adaptive_learning_service.analyze_learning_system(db)

    assert any(event.event_type == "domain_review" for event in events)


def test_negative_feedback_domain_review_includes_feedback_evidence(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    created_ids: list[str] = []
    for idx in range(3):
        log = _persist_log(
            db,
            query=f"consulta feedback {idx}",
            fallback_used=False,
            confidence_score=0.7,
            orchestrator_version="beta-orchestrator-v1",
            case_domain="familia",
        )
        created_ids.append(log.id)
    db.commit()

    for log_id in created_ids:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=2,
            is_user_feedback_positive=False,
        )

    event = next(
        item
        for item in adaptive_learning_service.analyze_learning_system(db)
        if item.event_type == "domain_review"
    )
    evidence = event.to_dict()["evidence_json"]

    assert evidence["negative_feedback_rate"] == 1.0
    assert evidence["affected_queries"] == 3
    assert evidence["affected_percentage"] == 1.0


def test_repeated_corrected_strategy_generates_strategy_recalibration_recommendation(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    created_ids: list[str] = []
    for idx in range(3):
        log = _persist_log(
            db,
            query=f"consulta estrategia {idx}",
            fallback_used=False,
            confidence_score=0.7,
            orchestrator_version="beta-orchestrator-v1",
            strategy_mode="conservative",
        )
        created_ids.append(log.id)
    db.commit()

    for log_id in created_ids:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=2,
            corrected_strategy_mode="cautious",
        )

    events = adaptive_learning_service.analyze_learning_system(db)

    assert any(event.event_type == "strategy_recalibration" for event in events)


def test_repeated_corrected_domain_generates_classification_review_recommendation(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    created_ids: list[str] = []
    for idx in range(3):
        log = _persist_log(
            db,
            query=f"consulta dominio {idx}",
            fallback_used=False,
            confidence_score=0.7,
            orchestrator_version="beta-orchestrator-v1",
            case_domain="familia",
        )
        created_ids.append(log.id)
    db.commit()

    for log_id in created_ids:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=2,
            corrected_domain="alimentos",
        )

    events = adaptive_learning_service.analyze_learning_system(db)

    assert any(event.event_type == "classification_review" for event in events)


def test_worse_version_feedback_strengthens_version_alert_logic(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    v1_ids: list[str] = []
    v2_ids: list[str] = []
    for idx in range(3):
        v1_log = _persist_log(
            db,
            query=f"consulta buena {idx}",
            fallback_used=False,
            confidence_score=0.8,
            orchestrator_version="beta-orchestrator-v1",
        )
        v2_log = _persist_log(
            db,
            query=f"consulta mala {idx}",
            fallback_used=False,
            confidence_score=0.8,
            orchestrator_version="beta-orchestrator-v2",
        )
        v1_ids.append(v1_log.id)
        v2_ids.append(v2_log.id)
    db.commit()

    for log_id in v1_ids:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=5,
            is_user_feedback_positive=True,
        )
    for log_id in v2_ids:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=2,
            is_user_feedback_positive=False,
        )

    events = adaptive_learning_service.analyze_learning_system(db)
    version_alerts = [event for event in events if event.event_type == "version_alert"]

    assert any("Feedback real bajo en beta-orchestrator-v2" == event.title for event in version_alerts)


def test_feedback_version_alert_includes_real_feedback_deltas(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    v1_ids: list[str] = []
    v2_ids: list[str] = []
    for idx in range(3):
        v1_log = _persist_log(
            db,
            query=f"consulta base buena {idx}",
            fallback_used=False,
            confidence_score=0.8,
            orchestrator_version="beta-orchestrator-v1",
        )
        v2_log = _persist_log(
            db,
            query=f"consulta base mala {idx}",
            fallback_used=False,
            confidence_score=0.8,
            orchestrator_version="beta-orchestrator-v2",
        )
        v1_ids.append(v1_log.id)
        v2_ids.append(v2_log.id)
    db.commit()

    for log_id in v1_ids:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=5,
            is_user_feedback_positive=True,
        )
    for log_id in v2_ids:
        learning_log_service.submit_learning_feedback(
            db,
            log_id=log_id,
            user_feedback_score=2,
            is_user_feedback_positive=False,
        )

    event = next(
        item
        for item in adaptive_learning_service.analyze_learning_system(db)
        if item.event_type == "version_alert" and item.title == "Feedback real bajo en beta-orchestrator-v2"
    )
    evidence = event.to_dict()["evidence_json"]

    assert evidence["negative_feedback_delta"] == 1.0
    assert evidence["positive_confirmation_delta"] == 1.0
    assert evidence["affected_queries"] == 3


def test_approved_event_can_be_applied_to_config_and_snapshots_persist(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    for idx in range(3):
        _persist_log(
            db,
            query=f"consulta alimentos {idx}",
            fallback_used=True,
            confidence_score=0.61,
            orchestrator_version="beta-orchestrator-v1",
        )
    db.commit()

    event = _create_domain_override_event(db)
    result = adaptive_learning_service.apply_tuning_event(db, event.id)

    assert result["event"]["status"] == "applied"
    assert "alimentos" in result["config"]["prefer_hybrid_domains"]

    snapshots = (
        db.query(OrchestratorConfigSnapshot)
        .filter(OrchestratorConfigSnapshot.event_id == event.id)
        .order_by(OrchestratorConfigSnapshot.created_at.asc())
        .all()
    )
    assert [item.snapshot_type for item in snapshots] == ["before_apply", "after_apply"]


def test_applied_config_influences_orchestrator_compatible_config_structure(tmp_path, monkeypatch):
    db = _build_session(tmp_path)
    config_path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(orchestrator_config_service, "_CONFIG_PATH", config_path)

    base_config = orchestrator_config_service.load_orchestrator_config()
    base_config.prefer_hybrid_domains.append("alimentos")
    orchestrator_config_service.save_orchestrator_config(base_config)

    orchestrator = QueryOrchestrator()
    result = orchestrator.run(
        query="Quiero reclamar alimentos para mi hijo",
        jurisdiction="jujuy",
        forum="familia",
        top_k=5,
        document_mode=None,
        facts={},
        metadata={},
        db=object(),
    )

    assert result.decision.retrieval_mode == "hybrid"
