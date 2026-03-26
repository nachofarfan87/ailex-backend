from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api import legal_query as legal_query_module
from app.main import app
from app.services.usage_guardrail_service import reset_usage_guardrails
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


def _build_result(*, blocking_factor: str = "none", fallback_used: bool = False) -> OrchestratorResult:
    api_payload = {
        "request_id": "req-test",
        "pipeline_version": "beta-orchestrator-v1",
        "query": "consulta de alimentos",
        "jurisdiction": "jujuy",
        "forum": "familia",
        "case_domain": "alimentos",
        "action_slug": "alimentos_hijos",
        "source_mode": "fallback" if fallback_used else "normative_only",
        "strategy_mode": "conservadora",
        "dominant_factor": "procesal" if blocking_factor != "none" else "norma",
        "blocking_factor": blocking_factor,
        "execution_readiness": "bloqueado_procesalmente" if blocking_factor != "none" else "requiere_impulso_procesal",
        "confidence_score": 0.61,
        "confidence_label": "medium",
        "confidence": 0.61,
        "fallback_used": fallback_used,
        "fallback_reason": "Se recurrió a fallback interno." if fallback_used else "",
        "response_text": "Respuesta final prudente." if blocking_factor == "none" else f"Respuesta final prudente.\n\nBloqueo procesal detectado: {blocking_factor}.",
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
        normalized_input=NormalizedOrchestratorInput(request_id="req-test", query="consulta de alimentos", jurisdiction="jujuy"),
        classification=OrchestratorClassification(action_slug="alimentos_hijos", action_label="Alimentos", case_domain="alimentos", jurisdiction="jujuy", forum="familia"),
        retrieval=RetrievalBundle(source_mode=api_payload["source_mode"], documents_considered=2),
        strategy=StrategyBundle(
            strategy_mode="conservadora",
            dominant_factor=api_payload["dominant_factor"],
            blocking_factor=blocking_factor,
            execution_readiness=api_payload["execution_readiness"],
            confidence_score=0.61,
            confidence_label="medium",
            fallback_used=fallback_used,
            fallback_reason=api_payload["fallback_reason"],
        ),
        final_output=FinalOutput(
            request_id="req-test",
            response_text=api_payload["response_text"],
            pipeline_version="beta-orchestrator-v1",
            case_domain="alimentos",
            action_slug="alimentos_hijos",
            source_mode=api_payload["source_mode"],
            documents_considered=2,
            strategy_mode="conservadora",
            dominant_factor=api_payload["dominant_factor"],
            blocking_factor=blocking_factor,
            execution_readiness=api_payload["execution_readiness"],
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
def api_overrides(monkeypatch):
    reset_usage_guardrails()
    tracked_cycles: list[dict[str, object]] = []
    tracked_errors: list[dict[str, object]] = []

    def _override_get_db():
        yield SimpleNamespace()

    app.dependency_overrides[legal_query_module.get_optional_user] = lambda: SimpleNamespace(
        id="user-1",
        username="tester",
        email="tester@example.com",
        is_active=True,
    )
    app.dependency_overrides[legal_query_module.get_db] = _override_get_db

    monkeypatch.setattr(
        legal_query_module.consulta_service,
        "save_consulta",
        lambda **kwargs: SimpleNamespace(id="consulta-1", created_at=datetime.now(timezone.utc)),
    )
    monkeypatch.setattr(
        legal_query_module.query_logging_service,
        "create_processing_log",
        lambda *args, **kwargs: SimpleNamespace(id="log-1"),
    )
    monkeypatch.setattr(
        legal_query_module.query_logging_service,
        "complete_log",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        legal_query_module.query_logging_service,
        "fail_log",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        legal_query_module.learning_log_service,
        "save_learning_log",
        lambda *args, **kwargs: SimpleNamespace(id="learning-log-1"),
    )
    monkeypatch.setattr(legal_query_module, "record_safety_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(legal_query_module, "build_chat_log_entry", lambda **kwargs: kwargs)
    monkeypatch.setattr(legal_query_module, "log_chat_interaction", lambda entry: None)
    monkeypatch.setattr(
        legal_query_module.session_tracking_service,
        "track_legal_query_cycle",
        lambda *args, **kwargs: tracked_cycles.append(kwargs),
    )
    monkeypatch.setattr(
        legal_query_module.session_tracking_service,
        "track_backend_error",
        lambda *args, **kwargs: tracked_errors.append(kwargs),
    )
    monkeypatch.setattr(
        legal_query_module.session_tracking_service,
        "ensure_session_id",
        lambda session_id=None: str(session_id or "generated-session-id"),
    )

    yield {"tracked_cycles": tracked_cycles, "tracked_errors": tracked_errors}
    reset_usage_guardrails()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_endpoint_delegates_to_single_orchestrator_and_serializes_response(client, api_overrides, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result())

    response = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req-test"
    assert payload["pipeline_version"] == "beta-orchestrator-v1"
    assert payload["action_slug"] == "alimentos_hijos"
    assert payload["source_mode"] == "normative_only"
    assert payload["documents_considered"] == 2
    assert payload["response_text"] == "Respuesta final prudente."


@pytest.mark.asyncio
async def test_endpoint_returns_clean_fallback_output(client, api_overrides, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(fallback_used=True))

    response = await client.post("/api/legal-query", json={"query": "consulta abierta", "jurisdiction": "jujuy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["fallback_reason"]
    assert all("fallback generico" not in warning.lower() for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_endpoint_reflects_procedural_block_without_manual_legal_logic(client, api_overrides, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(blocking_factor="service"))

    response = await client.post("/api/legal-query", json={"query": "consulta bloqueada", "jurisdiction": "jujuy"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["blocking_factor"] == "service"
    assert "Bloqueo procesal detectado: service." in payload["response_text"]
    assert not hasattr(legal_query_module, "_pipeline")
    assert hasattr(legal_query_module, "_orchestrator")


@pytest.mark.asyncio
async def test_endpoint_wraps_internal_orchestrator_errors(client, api_overrides, monkeypatch):
    def _raise(**kwargs):
        raise QueryOrchestratorError("req-error", "Fallo controlado durante la orquestacion juridica.")

    monkeypatch.setattr(legal_query_module._orchestrator, "run", _raise)

    response = await client.post("/api/legal-query", json={"query": "consulta rota", "jurisdiction": "jujuy"})

    assert response.status_code == 500
    payload = response.json()
    assert payload["detail"]["request_id"] == "req-error"


@pytest.mark.asyncio
async def test_endpoint_merges_clarification_context_before_running_orchestrator(client, api_overrides, monkeypatch):
    captured: dict[str, object] = {}

    def _run(**kwargs):
        captured.update(kwargs)
        return _build_result()

    monkeypatch.setattr(legal_query_module._orchestrator, "run", _run)

    response = await client.post(
        "/api/legal-query",
        json={
            "query": "Es unilateral y hay hijos",
            "jurisdiction": "jujuy",
            "metadata": {
                "clarification_context": {
                    "base_query": "Quiero divorciarme",
                    "case_domain": "divorcio",
                    "last_question": "¿El divorcio sera de comun acuerdo o unilateral?",
                    "asked_questions": ["¿El divorcio sera de comun acuerdo o unilateral?"],
                    "known_facts": {},
                }
            },
        },
    )

    assert response.status_code == 200
    assert captured["query"] == "Quiero divorciarme. Aclaraciones del usuario: divorcio unilateral; hay hijos; no hay acuerdo."
    assert captured["facts"]["divorcio_modalidad"] == "unilateral"
    assert captured["facts"]["hay_hijos"] is True
    assert captured["facts"]["hay_acuerdo"] is False


@pytest.mark.asyncio
async def test_endpoint_registers_tracking_cycle_events(client, api_overrides, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result())

    response = await client.post(
        "/api/legal-query",
        json={
            "query": "consulta de alimentos",
            "jurisdiction": "jujuy",
            "metadata": {"session_id": "sess-123"},
        },
    )

    assert response.status_code == 200
    tracked = api_overrides["tracked_cycles"]
    assert len(tracked) == 1
    assert tracked[0]["session_id"] == "sess-123"
    assert tracked[0]["query"] == "consulta de alimentos"
    assert tracked[0]["case_domain"] == "alimentos"
    assert tracked[0]["metadata"]["session_id"] == "sess-123"


@pytest.mark.asyncio
async def test_endpoint_tracking_failure_does_not_break_legal_query(client, api_overrides, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result())
    monkeypatch.setattr(
        legal_query_module.session_tracking_service,
        "track_legal_query_cycle",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tracking failed")),
    )

    response = await client.post(
        "/api/legal-query",
        json={
            "query": "consulta de alimentos",
            "jurisdiction": "jujuy",
            "metadata": {"session_id": "sess-safe"},
        },
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "sess-safe"
