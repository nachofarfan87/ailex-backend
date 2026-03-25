from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import legal_query as legal_query_module
from app.main import app
from app.db.database import Base
from app.db.legal_query_log_models import LegalQueryLog
from app.models.learning_log import LearningLog
from app.models.system_safety_event import SystemSafetyEvent
from app.services.usage_guardrail_service import reset_usage_guardrails
import app.models.system_safety_event as _system_safety_event  # noqa: F401
import app.models.learning_log as _learning_log  # noqa: F401
import app.models.learning_action_log as _learning_action_log  # noqa: F401
import app.models.learning_human_audit as _learning_human_audit  # noqa: F401
import app.models.learning_review as _learning_review  # noqa: F401
import app.models.learning_impact_log as _learning_impact_log  # noqa: F401
import app.models.learning_decision_audit_log as _learning_decision_audit_log  # noqa: F401
from legal_engine.orchestrator_schema import (
    FinalOutput,
    NormalizedOrchestratorInput,
    OrchestratorClassification,
    OrchestratorResult,
    OrchestratorTimings,
    RetrievalBundle,
    StrategyBundle,
)
from legal_engine.query_orchestrator import QueryOrchestratorError


def _build_result(
    *,
    request_id: str = "req-safety",
    query: str = "consulta de alimentos",
    fallback_used: bool = False,
) -> OrchestratorResult:
    api_payload = {
        "request_id": request_id,
        "pipeline_version": "beta-orchestrator-v1",
        "query": query,
        "jurisdiction": "jujuy",
        "forum": "familia",
        "case_domain": "alimentos",
        "action_slug": "alimentos_hijos",
        "source_mode": "fallback" if fallback_used else "normative_only",
        "strategy_mode": "conservadora",
        "dominant_factor": "norma",
        "blocking_factor": "none",
        "execution_readiness": "requiere_impulso_procesal",
        "confidence_score": 0.61,
        "confidence_label": "medium",
        "confidence": 0.61,
        "fallback_used": fallback_used,
        "fallback_reason": "fallback_controlado" if fallback_used else "",
        "response_text": "Respuesta final prudente.",
        "documents_considered": 2,
        "retrieval_bundle": {"source_mode": "fallback" if fallback_used else "normative_only", "documents_considered": 2},
        "warnings": ["Advertencia prudente para usuario."],
        "classification": {"action_slug": "alimentos_hijos"},
        "reasoning": {"short_answer": "Respuesta final prudente."},
        "case_structure": {},
        "normative_reasoning": {},
        "citation_validation": {},
        "hallucination_guard": {},
        "procedural_strategy": {},
        "question_engine_result": {},
        "case_theory": {},
        "case_evaluation": {},
        "conflict_evidence": {},
        "evidence_reasoning_links": {},
        "jurisprudence_analysis": {},
        "case_profile": {"case_domain": "alimentos"},
        "case_strategy": {"strategy_mode": "conservadora"},
        "legal_strategy": {},
        "retrieved_items": [],
        "context": {},
        "generated_document": None,
        "case_domains": ["alimentos"],
    }
    return OrchestratorResult(
        pipeline_version="beta-orchestrator-v1",
        normalized_input=NormalizedOrchestratorInput(
            request_id=request_id,
            query=query,
            jurisdiction="jujuy",
            forum="familia",
            metadata={"request_id": request_id},
        ),
        classification=OrchestratorClassification(
            action_slug="alimentos_hijos",
            action_label="Alimentos",
            case_domain="alimentos",
            jurisdiction="jujuy",
            forum="familia",
        ),
        retrieval=RetrievalBundle(source_mode=api_payload["source_mode"], documents_considered=2),
        strategy=StrategyBundle(
            strategy_mode="conservadora",
            dominant_factor="norma",
            blocking_factor="none",
            execution_readiness="requiere_impulso_procesal",
            confidence_score=0.61,
            confidence_label="medium",
            fallback_used=fallback_used,
            fallback_reason=api_payload["fallback_reason"],
        ),
        final_output=FinalOutput(
            request_id=request_id,
            response_text="Respuesta final prudente.",
            pipeline_version="beta-orchestrator-v1",
            case_domain="alimentos",
            action_slug="alimentos_hijos",
            source_mode=api_payload["source_mode"],
            documents_considered=2,
            strategy_mode="conservadora",
            dominant_factor="norma",
            blocking_factor="none",
            execution_readiness="requiere_impulso_procesal",
            confidence_score=0.61,
            confidence_label="medium",
            fallback_used=fallback_used,
            fallback_reason=api_payload["fallback_reason"],
            warnings=["Advertencia prudente para usuario."],
            api_payload=api_payload,
        ),
        timings=OrchestratorTimings(total_ms=12),
        pipeline_payload=api_payload,
    )


@pytest.fixture
def safety_db(client, monkeypatch, tmp_path: Path):
    reset_usage_guardrails()
    db_path = tmp_path / "safety_layer.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[legal_query_module.get_db] = _override_get_db
    app.dependency_overrides[legal_query_module.get_current_user] = lambda: SimpleNamespace(
        id="user-safety",
        username="tester",
        email="tester@example.com",
        is_active=True,
    )
    monkeypatch.setattr(
        legal_query_module.consulta_service,
        "save_consulta",
        lambda **kwargs: SimpleNamespace(id="consulta-1", created_at=datetime.now(timezone.utc)),
    )
    monkeypatch.setattr(legal_query_module, "build_chat_log_entry", lambda **kwargs: kwargs)
    monkeypatch.setattr(legal_query_module, "log_chat_interaction", lambda entry: None)

    yield testing_session

    reset_usage_guardrails()
    app.dependency_overrides.pop(legal_query_module.get_db, None)
    app.dependency_overrides.pop(legal_query_module.get_current_user, None)


@pytest.mark.asyncio
async def test_input_garbage_is_rejected_cleanly(client, safety_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result())

    response = await client.post("/api/legal-query", json={"query": "!!!!", "jurisdiction": "jujuy"})

    assert response.status_code == 422
    payload = response.json()
    assert payload["safety_status"] == "input_rejected"
    assert payload["dominant_safety_reason"] == "input_too_short"
    assert payload["fallback_type"] == "input_invalid"
    assert payload["excluded_from_learning"] is True
    with safety_db() as db:
        assert db.query(SystemSafetyEvent).filter(SystemSafetyEvent.event_type == "input_rejected").count() == 1
        assert db.query(LearningLog).count() == 0


@pytest.mark.asyncio
async def test_input_too_long_is_degraded_and_excluded_from_learning(client, safety_db, monkeypatch):
    seen = {}

    def _run(**kwargs):
        seen["query"] = kwargs["query"]
        return _build_result(request_id="req-long", query=kwargs["query"])

    monkeypatch.setattr(legal_query_module._orchestrator, "run", _run)
    long_query = "consulta " + " ".join(f"hecho_{index}" for index in range(900))

    response = await client.post("/api/legal-query", json={"query": long_query, "jurisdiction": "jujuy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["safety_status"] == "degraded"
    assert payload["dominant_safety_reason"] == "input_truncated_for_safety"
    assert payload["fallback_type"] == "degraded_mode"
    assert payload["excluded_from_learning"] is True
    assert payload["learning_log_id"] is None
    assert len(seen["query"]) <= 3500
    with safety_db() as db:
        assert db.query(SystemSafetyEvent).filter(SystemSafetyEvent.event_type == "request_degraded").count() == 1
        assert db.query(SystemSafetyEvent).filter(SystemSafetyEvent.event_type == "excluded_from_learning").count() == 1


@pytest.mark.asyncio
async def test_normal_input_passes_and_keeps_learning_enabled(client, safety_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-normal"))

    response = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["safety_status"] == "normal"
    assert payload["dominant_safety_reason"] is None
    assert payload["fallback_type"] is None
    assert payload["excluded_from_learning"] is False
    with safety_db() as db:
        assert db.query(LearningLog).count() == 1


@pytest.mark.asyncio
async def test_rate_limit_returns_consistent_response(client, safety_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-rate"))
    monkeypatch.setitem(legal_query_module.evaluate_usage_guardrail.__globals__["USAGE_GUARDRAIL_LIMITS"], "heavy_query", {"limit": 1, "window_seconds": 60})

    first = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})
    second = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})

    assert first.status_code == 200
    assert second.status_code == 429
    payload = second.json()
    assert payload["safety_status"] == "rate_limited"
    assert payload["dominant_safety_reason"] == "rate_limit_exceeded_user"
    assert payload["fallback_type"] == "rate_limited"
    assert payload["retry_after_seconds"] >= 1
    assert payload["detail"]["request_id"]


@pytest.mark.asyncio
async def test_small_burst_is_allowed_before_longer_rate_limit_blocks(client, safety_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-burst"))
    monkeypatch.setitem(
        legal_query_module.evaluate_usage_guardrail.__globals__["USAGE_GUARDRAIL_LIMITS"],
        "heavy_query",
        {"limit": 10, "window_seconds": 60, "burst_limit": 3, "burst_window_seconds": 3},
    )

    first = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})
    second = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})
    third = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200


@pytest.mark.asyncio
async def test_sustained_burst_is_blocked_with_burst_reason(client, safety_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-burst-block"))
    monkeypatch.setitem(
        legal_query_module.evaluate_usage_guardrail.__globals__["USAGE_GUARDRAIL_LIMITS"],
        "heavy_query",
        {"limit": 10, "window_seconds": 60, "burst_limit": 3, "burst_window_seconds": 3},
    )

    for _ in range(3):
        response = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})
        assert response.status_code == 200
    blocked = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})

    assert blocked.status_code == 429
    payload = blocked.json()
    assert payload["dominant_safety_reason"] == "burst_limit_exceeded_user"
    assert payload["fallback_type"] == "rate_limited"


@pytest.mark.asyncio
async def test_controlled_error_activates_safe_fallback_response(client, safety_db, monkeypatch):
    def _raise(**kwargs):
        raise QueryOrchestratorError("req-safety-error", "Fallo controlado durante la orquestacion juridica.")

    monkeypatch.setattr(legal_query_module._orchestrator, "run", _raise)

    response = await client.post("/api/legal-query", json={"query": "consulta rota", "jurisdiction": "jujuy"})

    assert response.status_code == 500
    payload = response.json()
    assert payload["safety_status"] == "degraded"
    assert payload["dominant_safety_reason"] == "controlled_orchestrator_error"
    assert payload["fallback_type"] == "internal_error"
    assert payload["excluded_from_learning"] is True
    assert payload["detail"]["request_id"] == "req-safety-error"


@pytest.mark.asyncio
async def test_pipeline_fallback_is_excluded_from_learning(client, safety_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-fallback", fallback_used=True))

    response = await client.post("/api/legal-query", json={"query": "consulta abierta", "jurisdiction": "jujuy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["excluded_from_learning"] is True
    assert payload["safety_status"] == "degraded"
    assert payload["dominant_safety_reason"] == "fallback_controlado"
    assert payload["fallback_type"] == "degraded_mode"
    with safety_db() as db:
        assert db.query(LearningLog).count() == 0
        assert db.query(SystemSafetyEvent).filter(SystemSafetyEvent.event_type == "fallback_triggered").count() >= 1


@pytest.mark.asyncio
async def test_dominant_safety_state_is_unique_and_prioritized(client, safety_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-priority", fallback_used=True))
    long_query = "consulta " + " ".join(f"hecho_{index}" for index in range(900))

    response = await client.post("/api/legal-query", json={"query": long_query, "jurisdiction": "jujuy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["safety_status"] == "degraded"
    assert payload["dominant_safety_reason"] == "input_truncated_for_safety"
    assert payload["fallback_type"] == "degraded_mode"
    assert "fallback_controlado" in payload["safety_reasons"]
    assert "input_truncated_for_safety" in payload["safety_reasons"]


@pytest.mark.asyncio
async def test_safety_summary_exposes_metrics_and_recent_events(client, safety_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-summary", fallback_used=True))

    await client.post("/api/legal-query", json={"query": "!!!!", "jurisdiction": "jujuy"})
    await client.post("/api/legal-query", json={"query": "consulta abierta", "jurisdiction": "jujuy"})
    response = await client.get("/api/safety/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rejected_inputs_count"] >= 1
    assert payload["degraded_requests_count"] >= 0
    assert payload["excluded_from_learning_count"] >= 1
    assert payload["dominant_safety_reason"] is not None
    assert payload["recent_safety_events"]
    assert payload["top_safety_reasons"]
