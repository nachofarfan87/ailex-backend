from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
import app.models.case_state  # noqa: F401
import app.models.conversation_state_snapshot  # noqa: F401
from app.services.case_state_service import case_state_service
from legal_engine.orchestrator_schema import RetrievalBundle, StrategyBundle
from legal_engine.response_postprocessor import ResponsePostprocessor
import legal_engine.response_postprocessor as response_postprocessor_module


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _postprocess_turn(
    db_session,
    *,
    conversation_id: str,
    query: str,
    facts: dict | None = None,
    missing_facts: list | None = None,
    critical_missing: list | None = None,
    output_mode: str = "",
):
    processor = ResponsePostprocessor()
    normalized_input = {
        "query": query,
        "facts": facts or {},
        "metadata": {"conversation_id": conversation_id},
    }
    pipeline_payload = {
        "query": query,
        "pipeline_version": "beta-orchestrator-v1",
        "facts": facts or {},
        "missing_facts": list(missing_facts or []),
        "critical_missing": list(critical_missing or []),
        "reasoning": {"short_answer": "Respuesta base."},
        "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
        "case_profile": {"case_domain": "alimentos"},
        "case_strategy": {"strategy_mode": "conservadora"},
        "legal_decision": {"confidence_score": 0.7, "execution_readiness": "requiere_impulso_procesal"},
        "procedural_case_state": {"blocking_factor": "none"},
    }
    if output_mode:
        pipeline_payload["output_mode"] = output_mode

    final_output = processor.postprocess(
        request_id=f"req-{conversation_id}-{query[:8]}",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7, confidence_label="medium"),
        db=db_session,
    )
    return final_output.api_payload["case_state_snapshot"]


def test_resolucion_de_need_en_multi_turno(db_session):
    first_snapshot = _postprocess_turn(
        db_session,
        conversation_id="conv-resolve-need",
        query="Quiero reclamar alimentos",
        missing_facts=["ingresos_otro_progenitor"],
    )
    second_snapshot = _postprocess_turn(
        db_session,
        conversation_id="conv-resolve-need",
        query="El otro progenitor gana 200000",
        facts={"ingresos_otro_progenitor": 200000},
    )

    assert first_snapshot["open_needs"][0]["need_key"] == "hecho::ingresos_otro_progenitor"
    assert second_snapshot["open_needs"] == []

    stored_need = case_state_service.get_case_needs(db_session, "conv-resolve-need")[0]
    assert stored_need.status == "resolved"
    assert stored_need.resolved_by_fact_key == "ingresos_otro_progenitor"


def test_stage_progression_multi_turno(db_session, monkeypatch):
    first_snapshot = _postprocess_turn(
        db_session,
        conversation_id="conv-stage-progress",
        query="Necesito ayuda con alimentos",
    )
    second_snapshot = _postprocess_turn(
        db_session,
        conversation_id="conv-stage-progress",
        query="Tengo una hija y necesito reclamar alimentos",
        facts={"hay_hijos": True},
        missing_facts=["ingresos_otro_progenitor"],
    )
    def _progression_strategy(*args, **kwargs):
        return {
            "output_mode": "estrategia",
            "progression_stage": "strategy",
            "missing_focus": [],
            "progression_state": {
                "facts_collected": ["hay_hijos", "ingresos_otro_progenitor"],
                "questions_asked": [],
                "topics_covered": ["alimentos"],
                "last_output_mode": "estrategia",
                "progression_stage": "strategy",
                "recent_turns": [],
                "last_intent_type": "general_information",
                "current_turn": {"output_mode": "estrategia", "topics_covered": ["alimentos"]},
            },
            "rendered_response_text": "",
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression_strategy)

    third_snapshot = _postprocess_turn(
        db_session,
        conversation_id="conv-stage-progress",
        query="El otro progenitor gana 200000 y ya tengo sus ingresos",
        facts={"hay_hijos": True, "ingresos_otro_progenitor": 200000},
        output_mode="estrategia",
    )

    assert first_snapshot["case_state"]["case_stage"] == "consulta_inicial"
    assert second_snapshot["case_state"]["case_stage"] == "recopilacion_hechos"
    assert third_snapshot["case_state"]["case_stage"] == "analisis_estrategico"


def test_namespace_en_need_key(db_session):
    snapshot = _postprocess_turn(
        db_session,
        conversation_id="conv-need-namespace",
        query="Quiero reclamar alimentos",
        missing_facts=["ingresos"],
    )

    assert snapshot["open_needs"][0]["need_key"] == "hecho::ingresos"


def test_compatibilidad_backward_need_sin_namespace(db_session):
    case_state_service.upsert_case_need(
        db_session,
        conversation_id="conv-backward-need",
        need_key="ingresos_otro_progenitor",
        category="economico",
        priority="critical",
        status="open",
    )

    snapshot = _postprocess_turn(
        db_session,
        conversation_id="conv-backward-need",
        query="Ahora si tengo el dato de ingresos",
        facts={"ingresos_otro_progenitor": 200000},
    )

    assert snapshot["open_needs"] == []
    stored_need = case_state_service.get_case_needs(db_session, "conv-backward-need")[0]
    assert stored_need.need_key == "ingresos_otro_progenitor"
    assert stored_need.status == "resolved"
