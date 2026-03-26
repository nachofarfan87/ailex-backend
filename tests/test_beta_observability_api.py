from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api import legal_query as legal_query_module
from app.main import app
from app.services.beta_observability_helpers import load_recent_snapshots
from app.services.beta_observability_service import start_beta_observability_context
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


def _build_result() -> OrchestratorResult:
    api_payload = {
        "request_id": "req-observability-api",
        "pipeline_version": "beta-orchestrator-v1",
        "query": "consulta de alimentos",
        "jurisdiction": "jujuy",
        "forum": "familia",
        "case_domain": "alimentos",
        "case_domains": ["alimentos"],
        "action_slug": "alimentos_hijos",
        "source_mode": "normative_only",
        "strategy_mode": "conservadora",
        "dominant_factor": "norma",
        "blocking_factor": "none",
        "execution_readiness": "requiere_impulso_procesal",
        "confidence_score": 0.61,
        "confidence_label": "medium",
        "confidence": 0.61,
        "fallback_used": False,
        "fallback_reason": "",
        "response_text": "Respuesta final prudente.",
        "documents_considered": 2,
        "retrieval_bundle": {"source_mode": "normative_only", "documents_considered": 2},
        "warnings": ["Advertencia prudente para usuario."],
        "classification": {"action_slug": "alimentos_hijos"},
        "reasoning": {"short_answer": "Respuesta final prudente."},
        "case_profile": {"case_domain": "alimentos", "case_domains": ["alimentos"]},
        "citation_validation": {},
        "hallucination_guard": {},
    }
    return OrchestratorResult(
        pipeline_version="beta-orchestrator-v1",
        normalized_input=NormalizedOrchestratorInput(
            request_id="req-observability-api",
            query="consulta de alimentos",
            jurisdiction="jujuy",
            metadata={"request_id": "req-observability-api"},
        ),
        classification=OrchestratorClassification(
            action_slug="alimentos_hijos",
            action_label="Alimentos",
            case_domain="alimentos",
            jurisdiction="jujuy",
            forum="familia",
        ),
        retrieval=RetrievalBundle(source_mode="normative_only", documents_considered=2),
        strategy=StrategyBundle(
            strategy_mode="conservadora",
            dominant_factor="norma",
            blocking_factor="none",
            execution_readiness="requiere_impulso_procesal",
            confidence_score=0.61,
            confidence_label="medium",
            fallback_used=False,
            fallback_reason="",
        ),
        final_output=FinalOutput(
            request_id="req-observability-api",
            response_text="Respuesta final prudente.",
            pipeline_version="beta-orchestrator-v1",
            case_domain="alimentos",
            action_slug="alimentos_hijos",
            source_mode="normative_only",
            documents_considered=2,
            strategy_mode="conservadora",
            dominant_factor="norma",
            blocking_factor="none",
            execution_readiness="requiere_impulso_procesal",
            confidence_score=0.61,
            confidence_label="medium",
            fallback_used=False,
            fallback_reason="",
            sanitized_output=True,
            warnings=["Advertencia prudente para usuario."],
            api_payload=api_payload,
        ),
        timings=OrchestratorTimings(total_ms=12, pipeline_ms=5, classification_ms=1, retrieval_ms=1, strategy_ms=1),
        pipeline_payload=api_payload,
    )


@pytest.fixture
def observability_api_overrides(monkeypatch, tmp_path):
    reset_usage_guardrails()

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
        legal_query_module,
        "start_beta_observability_context",
        lambda **kwargs: start_beta_observability_context(**kwargs, storage_dir=tmp_path),
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
        legal_query_module.consulta_service,
        "save_consulta",
        lambda **kwargs: SimpleNamespace(id="consulta-1", created_at=datetime.now(timezone.utc)),
    )
    monkeypatch.setattr(
        legal_query_module.learning_log_service,
        "save_learning_log",
        lambda *args, **kwargs: SimpleNamespace(id="learning-log-1"),
    )
    monkeypatch.setattr(legal_query_module, "build_chat_log_entry", lambda **kwargs: kwargs)
    monkeypatch.setattr(legal_query_module, "log_chat_interaction", lambda entry: None)
    monkeypatch.setattr(legal_query_module, "record_safety_event", lambda *args, **kwargs: None)

    yield tmp_path
    reset_usage_guardrails()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_observability_snapshot_does_not_expose_internal_data_to_user_payload(client, observability_api_overrides, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result())

    response = await client.post(
        "/api/legal-query",
        json={
            "query": "consulta de alimentos",
            "jurisdiction": "jujuy",
            "metadata": {"request_id": "req-observability-api"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "internal_warnings" not in payload
    assert "response_status" not in payload
    assert "selected_model" not in payload
    assert "stage_durations_ms" not in payload

    snapshots = load_recent_snapshots(storage_dir=observability_api_overrides, limit=1, days=1)
    assert snapshots[0]["request_id"] == "req-observability-api"
    assert snapshots[0]["sanitized_output"] is True


@pytest.mark.asyncio
async def test_observability_snapshot_records_error_status_on_exception_e2e(client, observability_api_overrides, monkeypatch):
    def _raise(**kwargs):
        raise QueryOrchestratorError("req-observability-error", "Fallo controlado durante la orquestacion juridica.")

    monkeypatch.setattr(legal_query_module._orchestrator, "run", _raise)

    response = await client.post(
        "/api/legal-query",
        json={
            "query": "consulta rota",
            "jurisdiction": "jujuy",
            "metadata": {"request_id": "req-observability-error"},
        },
    )

    assert response.status_code == 500
    snapshots = load_recent_snapshots(storage_dir=observability_api_overrides, limit=1, days=1)
    assert snapshots[0]["request_id"] == "req-observability-error"
    assert snapshots[0]["response_status"] == "blocked"
    assert snapshots[0]["error_message"] == "Fallo controlado durante la orquestacion juridica."
