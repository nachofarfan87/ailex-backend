# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_response_postprocessor_conversation_state.py
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
import app.models.conversation_state_snapshot  # noqa: F401
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


def _payload(*, conversation_id: str = "conv-post", should_ask_first: bool = True) -> tuple[dict, dict]:
    normalized_input = {
        "query": "Quiero reclamar alimentos por mi hija",
        "facts": {"hay_hijos": True},
        "metadata": {
            "conversation_id": conversation_id,
        },
    }
    pipeline_payload = {
        "query": "Quiero reclamar alimentos por mi hija",
        "pipeline_version": "beta-orchestrator-v1",
        "facts": {"hay_hijos": True},
        "reasoning": {"short_answer": "Hay base para orientar el reclamo."},
        "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
        "case_profile": {
            "case_domain": "alimentos",
            "missing_critical_facts": ["ingresos_otro_progenitor"],
        },
        "case_strategy": {"strategy_mode": "conservadora"},
        "legal_decision": {
            "dominant_factor": "norma",
            "confidence_score": 0.7,
            "execution_readiness": "requiere_impulso_procesal",
        },
        "procedural_case_state": {"blocking_factor": "none"},
        "conversational": {
            "should_ask_first": should_ask_first,
            "question": "El otro progenitor esta aportando algo actualmente?" if should_ask_first else "",
        },
    }
    return normalized_input, pipeline_payload


def test_pipeline_adjunta_snapshot_si_todo_sale_bien(db_session):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload()

    final_output = processor.postprocess(
        request_id="req-conv-state",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(
            strategy_mode="conservadora",
            dominant_factor="norma",
            confidence_score=0.7,
            confidence_label="medium",
        ),
        db=db_session,
    )

    snapshot = final_output.api_payload["conversation_state"]
    assert snapshot["conversation_id"] == "conv-post"
    assert snapshot["turn_count"] == 1
    assert snapshot["working_case_type"] == "alimentos_hijos"
    assert snapshot["working_domain"] == "alimentos"
    assert snapshot["progress_signals"]["known_fact_count"] == 1
    assert snapshot["progress_signals"]["missing_fact_count"] == 1
    assert snapshot["known_facts"][0]["fact_type"] == "structural"
    assert snapshot["known_facts"][0]["importance"] == "core"
    assert snapshot["missing_facts"][0]["purpose"] == "quantify"
    assert snapshot["progress_signals"]["blocking_missing"] is True
    assert snapshot["progress_signals"]["case_completeness"] == "low"

    dialogue_policy = final_output.api_payload["dialogue_policy"]
    assert dialogue_policy["action"] == "ask"
    assert dialogue_policy["priority_missing_keys"] == ["ingresos_otro_progenitor"]
    assert dialogue_policy["dominant_missing_key"] == "ingresos_otro_progenitor"
    assert dialogue_policy["dominant_missing_purpose"] == "quantify"
    assert dialogue_policy["dominant_missing_importance"] == "core"
    assert dialogue_policy["guidance_strength"] == "medium"
    assert dialogue_policy["should_ask_first"] is True


def test_no_rompe_respuesta_si_el_servicio_falla(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(conversation_id="conv-fail", should_ask_first=False)

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(response_postprocessor_module.conversation_state_service, "update_conversation_state", _raise)

    final_output = processor.postprocess(
        request_id="req-conv-state-fail",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(
            strategy_mode="conservadora",
            dominant_factor="norma",
            confidence_score=0.7,
            confidence_label="medium",
        ),
        db=db_session,
    )

    assert final_output.response_text == "Hay base para orientar el reclamo."
    assert "conversation_state" not in final_output.api_payload


def test_no_rompe_respuesta_si_dialogue_policy_falla(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(conversation_id="conv-policy-fail", should_ask_first=True)

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(response_postprocessor_module, "resolve_dialogue_policy", _raise)

    final_output = processor.postprocess(
        request_id="req-dialogue-policy-fail",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(
            strategy_mode="conservadora",
            dominant_factor="norma",
            confidence_score=0.7,
            confidence_label="medium",
        ),
        db=db_session,
    )

    assert "conversation_state" in final_output.api_payload
    assert "dialogue_policy" not in final_output.api_payload
