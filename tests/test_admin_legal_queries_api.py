from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import legal_query as legal_query_module
from app.api.routes import admin_legal_queries as admin_legal_queries_module
from app.main import app
from app.db.database import Base
from app.db.legal_query_log_models import LegalQueryLog
import app.models.system_safety_event as _system_safety_event  # noqa: F401
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


def _build_result(*, request_id: str = "req-admin", blocking_factor: str = "none") -> OrchestratorResult:
    api_payload = {
        "request_id": request_id,
        "pipeline_version": "beta-orchestrator-v1",
        "query": "consulta de alimentos",
        "jurisdiction": "jujuy",
        "forum": "familia",
        "case_domain": "alimentos",
        "action_slug": "alimentos_hijos",
        "source_mode": "normative_only",
        "documents_considered": 2,
        "strategy_mode": "conservadora",
        "dominant_factor": "norma",
        "blocking_factor": blocking_factor,
        "execution_readiness": "bloqueado_procesalmente" if blocking_factor != "none" else "requiere_impulso_procesal",
        "confidence_score": 0.61,
        "confidence_label": "medium",
        "confidence": 0.61,
        "fallback_used": False,
        "fallback_reason": "",
        "response_text": "Respuesta final prudente.",
        "retrieval_bundle": {"source_mode": "normative_only", "documents_considered": 2},
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
            query="consulta de alimentos",
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
        retrieval=RetrievalBundle(source_mode="normative_only", documents_considered=2),
        strategy=StrategyBundle(
            strategy_mode="conservadora",
            dominant_factor="norma",
            blocking_factor=blocking_factor,
            execution_readiness=api_payload["execution_readiness"],
            confidence_score=0.61,
            confidence_label="medium",
            fallback_used=False,
            fallback_reason="",
        ),
        final_output=FinalOutput(
            request_id=request_id,
            response_text="Respuesta final prudente.",
            pipeline_version="beta-orchestrator-v1",
            case_domain="alimentos",
            action_slug="alimentos_hijos",
            source_mode="normative_only",
            documents_considered=2,
            strategy_mode="conservadora",
            dominant_factor="norma",
            blocking_factor=blocking_factor,
            execution_readiness=api_payload["execution_readiness"],
            confidence_score=0.61,
            confidence_label="medium",
            warnings=["Advertencia prudente para usuario."],
            api_payload=api_payload,
        ),
        timings=OrchestratorTimings(total_ms=12),
        pipeline_payload=api_payload,
    )


@pytest.fixture
def logged_db(client, monkeypatch, tmp_path: Path):
    reset_usage_guardrails()
    db_path = tmp_path / "admin_legal_queries.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[legal_query_module.get_db] = _override_get_db
    app.dependency_overrides[admin_legal_queries_module.get_db] = _override_get_db
    app.dependency_overrides[legal_query_module.get_current_user] = lambda: SimpleNamespace(
        id="user-1",
        username="tester",
        email="tester@example.com",
        is_active=True,
    )
    app.dependency_overrides[admin_legal_queries_module.get_current_user] = lambda: SimpleNamespace(
        id="user-1",
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

    yield TestingSessionLocal

    reset_usage_guardrails()
    app.dependency_overrides.pop(legal_query_module.get_db, None)
    app.dependency_overrides.pop(admin_legal_queries_module.get_db, None)
    app.dependency_overrides.pop(legal_query_module.get_current_user, None)
    app.dependency_overrides.pop(admin_legal_queries_module.get_current_user, None)


@pytest.mark.asyncio
async def test_legal_query_creates_processing_and_completes_log(client, logged_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-complete"))

    response = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})

    assert response.status_code == 200
    with logged_db() as db:
        log = db.query(LegalQueryLog).filter(LegalQueryLog.request_id == "req-complete").one()
        assert log.status == "completed"
        assert log.documents_considered == 2
        assert log.action_slug == "alimentos_hijos"


@pytest.mark.asyncio
async def test_legal_query_marks_failed_log_when_orchestrator_errors(client, logged_db, monkeypatch):
    def _raise(**kwargs):
        raise QueryOrchestratorError("req-failed-api", "Fallo controlado durante la orquestacion juridica.")

    monkeypatch.setattr(legal_query_module._orchestrator, "run", _raise)

    response = await client.post("/api/legal-query", json={"query": "consulta rota", "jurisdiction": "jujuy"})

    assert response.status_code == 500
    with logged_db() as db:
        log = db.query(LegalQueryLog).filter(LegalQueryLog.request_id == "req-failed-api").one()
        assert log.status == "failed"
        assert "Fallo controlado" in (log.error_message or "")


@pytest.mark.asyncio
async def test_logging_persistence_failure_does_not_break_main_response(client, logged_db, monkeypatch):
    monkeypatch.setattr(legal_query_module.query_logging_service, "create_processing_log", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(legal_query_module.query_logging_service, "complete_log", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-safe"))
    monkeypatch.setattr(
        legal_query_module.consulta_service,
        "save_consulta",
        lambda **kwargs: SimpleNamespace(id="consulta-1", created_at=datetime.now(timezone.utc)),
    )
    monkeypatch.setattr(legal_query_module, "build_chat_log_entry", lambda **kwargs: kwargs)
    monkeypatch.setattr(legal_query_module, "log_chat_interaction", lambda entry: None)

    response = await client.post("/api/legal-query", json={"query": "consulta segura", "jurisdiction": "jujuy"})

    assert response.status_code == 200
    assert response.json()["request_id"] == "req-safe"


@pytest.mark.asyncio
async def test_admin_listing_filters_and_review_creation(client, logged_db, monkeypatch):
    monkeypatch.setattr(legal_query_module._orchestrator, "run", lambda **kwargs: _build_result(request_id="req-admin-list"))
    response = await client.post("/api/legal-query", json={"query": "consulta de alimentos", "jurisdiction": "jujuy"})
    assert response.status_code == 200

    list_response = await client.get("/api/admin/legal-queries", params={"status": "completed", "case_domain": "alimentos"})
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["status"] == "completed"

    with logged_db() as db:
        log = db.query(LegalQueryLog).filter(LegalQueryLog.request_id == "req-admin-list").one()
        log_id = log.id

    review_response = await client.post(
        f"/api/admin/legal-queries/{log_id}/reviews",
        json={
            "reviewer": "qa-lawyer",
            "review_status": "approved",
            "feedback_signal": "positive",
            "quality_score": 0.9,
            "legal_accuracy_score": 0.95,
            "clarity_score": 0.88,
            "usefulness_score": 0.9,
            "notes": "Buena respuesta",
            "corrected_answer": "",
            "detected_issue_tags": ["none"],
        },
    )
    assert review_response.status_code == 201
    review_payload = review_response.json()
    assert review_payload["review_status"] == "approved"

    detail_response = await client.get(f"/api/admin/legal-queries/{log_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["review_status"] == "approved"
    assert detail_payload["reviews"][0]["reviewer"] == "qa-lawyer"
