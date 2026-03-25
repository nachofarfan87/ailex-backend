from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.legal_query_log_models import LegalQueryLog
from app.services import query_logging_service
from legal_engine.orchestrator_schema import (
    FinalOutput,
    NormalizedOrchestratorInput,
    OrchestratorClassification,
    OrchestratorResult,
    OrchestratorTimings,
    RetrievalBundle,
    StrategyBundle,
)


def _build_result() -> OrchestratorResult:
    api_payload = {
        "request_id": "req-service",
        "pipeline_version": "beta-orchestrator-v1",
        "query": "consulta de alimentos",
        "case_domain": "alimentos",
        "action_slug": "alimentos_hijos",
        "source_mode": "normative_only",
        "documents_considered": 2,
        "strategy_mode": "conservadora",
        "dominant_factor": "norma",
        "blocking_factor": "none",
        "execution_readiness": "requiere_impulso_procesal",
        "confidence_score": 0.61,
        "confidence_label": "medium",
        "fallback_used": False,
        "fallback_reason": "",
        "response_text": "Respuesta final prudente.",
        "warnings": ["Advertencia prudente para usuario."],
    }
    return OrchestratorResult(
        pipeline_version="beta-orchestrator-v1",
        normalized_input=NormalizedOrchestratorInput(
            request_id="req-service",
            query="consulta de alimentos",
            jurisdiction="jujuy",
            forum="familia",
            facts={"monto": 123},
            metadata={"request_id": "req-service"},
        ),
        classification=OrchestratorClassification(
            action_slug="alimentos_hijos",
            action_label="Alimentos",
            case_domain="alimentos",
            jurisdiction="jujuy",
            forum="familia",
        ),
        retrieval=RetrievalBundle(
            source_mode="normative_only",
            sources_used=["CCyC"],
            normative_references=[{"source": "CCyC", "article": "658"}],
            jurisprudence_references=[],
            documents_considered=2,
            top_retrieval_scores=[0.81, 0.78],
        ),
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
            request_id="req-service",
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
            warnings=["Advertencia prudente para usuario."],
            api_payload=api_payload,
        ),
        timings=OrchestratorTimings(
            normalization_ms=1,
            pipeline_ms=2,
            classification_ms=3,
            retrieval_ms=4,
            strategy_ms=5,
            postprocess_ms=6,
            final_assembly_ms=7,
            total_ms=28,
        ),
        pipeline_payload=api_payload,
    )


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'query_logging_service.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()


def test_create_processing_log_persists_initial_status(tmp_path):
    db = _build_session(tmp_path)
    log = query_logging_service.create_processing_log(
        db,
        request_id="req-processing",
        pipeline_version="beta-orchestrator-v1",
        user_query_original="consulta original",
        user_query_normalized="consulta original",
        jurisdiction_requested="jujuy",
        forum_requested="familia",
        facts={"hecho": True},
        metadata={"request_id": "req-processing"},
    )

    stored = db.get(LegalQueryLog, log.id)
    assert stored is not None
    assert stored.status == "processing"
    assert stored.request_id == "req-processing"


def test_complete_log_marks_completed_with_orchestrator_data(tmp_path):
    db = _build_session(tmp_path)
    processing = query_logging_service.create_processing_log(
        db,
        request_id="req-service",
        pipeline_version="beta-orchestrator-v1",
        user_query_original="consulta original",
        user_query_normalized="consulta original",
    )

    completed = query_logging_service.complete_log(db, log_id=processing.id, result=_build_result())

    assert completed.status == "completed"
    assert completed.case_domain == "alimentos"
    assert completed.documents_considered == 2
    assert completed.total_ms == 28


def test_fail_log_marks_failed_when_orchestrator_errors(tmp_path):
    db = _build_session(tmp_path)
    failed = query_logging_service.fail_log(
        db,
        request_id="req-failed",
        pipeline_version="beta-orchestrator-v1",
        user_query_original="consulta fallida",
        user_query_normalized="consulta fallida",
        error_message="fallo controlado",
    )

    assert failed.status == "failed"
    assert failed.error_message == "fallo controlado"
