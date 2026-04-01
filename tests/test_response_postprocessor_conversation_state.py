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


def _payload(
    *,
    conversation_id: str = "conv-post",
    should_ask_first: bool = True,
    query: str = "Quiero reclamar alimentos por mi hija",
    practical: bool = False,
) -> tuple[dict, dict]:
    normalized_input = {
        "query": query,
        "facts": {"hay_hijos": True},
        "metadata": {
            "conversation_id": conversation_id,
        },
    }
    pipeline_payload = {
        "query": query,
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
        "output_modes": {
            "user": {
                "title": "Orientacion inicial para alimentos",
                "summary": "Hay base para orientar el reclamo.",
                "what_this_means": "Hay base para orientar el reclamo.",
                "next_steps": ["Preparar inicio del reclamo."],
                "missing_information": ["ingresos_otro_progenitor"],
            },
            "professional": {
                "title": "Encuadre estrategico de alimentos",
                "summary": "Encuadre inicial.",
            },
        },
    }
    if practical:
        pipeline_payload["quick_start"] = "Primer paso recomendado: Preparar presentacion inicial de divorcio con encuadre y competencia correctos."
        pipeline_payload["classification"] = {"action_slug": "divorcio_unilateral", "case_domain": "divorcio"}
        pipeline_payload["case_profile"] = {
            "case_domain": "divorcio",
            "missing_critical_facts": ["domicilio_relevante"],
        }
        pipeline_payload["case_strategy"] = {
            "strategy_mode": "conservadora",
            "recommended_actions": [
                "Preparar presentacion inicial de divorcio con encuadre y competencia correctos.",
                "Redactar propuesta reguladora con los efectos necesarios del divorcio.",
                "Pedir cuota provisoria en el mismo inicio si corresponde.",
            ],
            "procedural_focus": ["Verificar competencia y ultimo domicilio conyugal."],
            "ordinary_missing_information": ["Completar propuesta reguladora y documentacion basica."],
        }
        pipeline_payload["procedural_strategy"] = {
            "next_steps": [
                "Reunir prueba documental basica.",
                "Definir juzgado competente segun domicilios relevantes.",
            ],
            "missing_information": ["Documentacion basica y comprobantes relevantes."],
        }
        pipeline_payload["output_modes"] = {
            "user": {
                "next_steps": [
                    "Definir la via procesal aplicable.",
                    "Reunir prueba documental basica.",
                ],
                "missing_information": [
                    "Completar acuerdo o propuesta reguladora.",
                    "Reunir documentacion basica.",
                ],
            },
        }
        pipeline_payload["conversational"]["question"] = "¿El divorcio seria de comun acuerdo o unilateral?"
    return normalized_input, pipeline_payload


def test_pipeline_adjunta_conversational_intelligence_y_policy_modulada(db_session):
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

    dialogue_policy = final_output.api_payload["dialogue_policy"]
    assert dialogue_policy["action"] == "ask"
    assert dialogue_policy["priority_missing_keys"] == ["ingresos_otro_progenitor"]
    assert dialogue_policy["dominant_missing_key"] == "ingresos_otro_progenitor"
    assert dialogue_policy["dominant_missing_purpose"] == "quantify"
    assert dialogue_policy["dominant_missing_importance"] == "core"

    conversational_intelligence = final_output.api_payload["conversational_intelligence"]
    assert conversational_intelligence["conversation_status"] in {"stable", "fragile"}
    assert conversational_intelligence["recommended_adjustment"] == "keep_policy"
    assert conversational_intelligence["conversational_pressure_score"] == 0
    assert isinstance(conversational_intelligence["signals"], dict)
    assert final_output.api_payload["intent_resolution"]["intent_type"] == "general_information"
    assert final_output.api_payload["execution_output"]["applies"] is False


def test_pipeline_adjunta_intent_resolution_y_execution_output_practico(db_session):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-practical",
        should_ask_first=True,
        query="Que tengo que hacer mañana para empezar mi divorcio?",
        practical=True,
    )

    final_output = processor.postprocess(
        request_id="req-practical",
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

    assert "intent_resolution" in final_output.api_payload
    assert final_output.api_payload["intent_resolution"]["intent_type"] == "action_now"
    assert "execution_output" in final_output.api_payload
    assert final_output.api_payload["execution_output"]["applies"] is True
    assert "Manana podrias hacer esto:" in final_output.response_text
    assert "Si no tenes abogado:" in final_output.response_text
    assert "Para ajustar el paso siguiente" in final_output.response_text


def test_inteligencia_reduce_questions_no_rompe_respuesta(db_session):
    processor = ResponsePostprocessor()

    normalized_input_1, pipeline_payload_1 = _payload(
        conversation_id="conv-stalled",
        should_ask_first=True,
        query="Quiero reclamar alimentos",
    )
    processor.postprocess(
        request_id="req-stalled-1",
        normalized_input=normalized_input_1,
        pipeline_payload=pipeline_payload_1,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    normalized_input_2, pipeline_payload_2 = _payload(
        conversation_id="conv-stalled",
        should_ask_first=True,
        query="No se",
    )
    final_output = processor.postprocess(
        request_id="req-stalled-2",
        normalized_input=normalized_input_2,
        pipeline_payload=pipeline_payload_2,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert final_output.response_text
    assert "dialogue_policy" in final_output.api_payload
    assert "conversational_intelligence" in final_output.api_payload


def test_pipeline_evita_loop_de_orientacion_inicial_y_avanza_output_mode(db_session):
    processor = ResponsePostprocessor()

    normalized_input_1, pipeline_payload_1 = _payload(
        conversation_id="conv-progress",
        should_ask_first=False,
        query="Quiero reclamar alimentos por mi hija",
    )
    first_output = processor.postprocess(
        request_id="req-progress-1",
        normalized_input=normalized_input_1,
        pipeline_payload=pipeline_payload_1,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    normalized_input_2, pipeline_payload_2 = _payload(
        conversation_id="conv-progress",
        should_ask_first=False,
        query="No me pasa alimentos",
    )
    second_output = processor.postprocess(
        request_id="req-progress-2",
        normalized_input=normalized_input_2,
        pipeline_payload=pipeline_payload_2,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert first_output.api_payload["output_modes"]["user"]["title"] == "Orientacion inicial para alimentos"
    assert second_output.api_payload["progression_policy"]["output_mode"] == "estructuracion"
    assert second_output.api_payload["output_modes"]["user"]["title"] == "Estructuracion del caso de alimentos"
    assert second_output.api_payload["conversation_state"]["progression_stage"] == "structuring_case"
    assert "Con lo que contas, el caso queda asi:" in second_output.response_text
    assert "Lo que falta para definir bien el encuadre:" in second_output.response_text
    assert first_output.response_text != second_output.response_text


def test_estructuracion_lista_hechos_y_no_repite_explicacion_basica(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-structuring",
        should_ask_first=False,
        query="No me pasa alimentos",
    )

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estructuracion",
            "progression_stage": "structuring_case",
            "missing_focus": ["ingresos del otro progenitor"],
            "progression_state": {
                "facts_collected": ["hay_hijos"],
                "questions_asked": [],
                "topics_covered": ["alimentos"],
                "last_output_mode": "estructuracion",
                "progression_stage": "structuring_case",
                "recent_turns": [],
                "last_intent_type": "general_information",
                "current_turn": {"output_mode": "estructuracion", "topics_covered": ["alimentos"]},
            },
            "rendered_response_text": "",
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)

    final_output = processor.postprocess(
        request_id="req-structuring",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "Con lo que contas, el caso queda asi:" in final_output.response_text
    assert "Lo que falta para definir bien el encuadre:" in final_output.response_text
    assert "es un derecho" not in final_output.response_text.lower()


def test_estrategia_compara_opciones_y_no_contiene_explicacion_basica(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-strategy",
        should_ask_first=False,
        query="No me pasa alimentos",
    )
    pipeline_payload["case_strategy"]["recommended_actions"] = [
        "Iniciar el reclamo principal con pedido de cuota provisoria.",
        "Reunir primero mas prueba de ingresos antes de presentar.",
    ]
    pipeline_payload["case_strategy"]["risk_analysis"] = [
        "permite pedir una cuota provisoria mas rapido",
        "demora mas el inicio si esperas toda la prueba",
    ]
    pipeline_payload["quick_start"] = "Primer paso recomendado: Iniciar el reclamo principal con pedido de cuota provisoria."

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estrategia",
            "progression_stage": "strategy",
            "missing_focus": ["ingresos del otro progenitor"],
            "progression_state": {
                "facts_collected": ["hay_hijos"],
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

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)

    final_output = processor.postprocess(
        request_id="req-strategy",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "En este caso, lo mas conveniente es:" in final_output.response_text
    assert "La accion prioritaria ahora es:" in final_output.response_text
    assert "Otra opcion seria" in final_output.response_text
    assert "porque" in final_output.response_text
    assert "es un derecho" not in final_output.response_text.lower()
    assert "strategic_decision" in final_output.api_payload
    assert final_output.api_payload["strategic_decision"]["recommended_path"]
    assert final_output.api_payload["strategic_decision"]["priority_action"]


def test_estrategia_siempre_prioriza_una_opcion_concreta(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-strategy-priority",
        should_ask_first=False,
        query="Quiero divorciarme y pedir alimentos para mi hija de 3 meses",
        practical=True,
    )
    pipeline_payload["facts"] = {"hay_hijos": True, "hay_acuerdo": False}

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estrategia",
            "progression_stage": "strategy",
            "missing_focus": ["modalidad del divorcio"],
            "decision_required": True,
            "decision_focus": "definir el camino principal del caso",
            "progression_state": {
                "facts_collected": ["hay_hijos"],
                "questions_asked": [],
                "topics_covered": ["divorcio", "alimentos"],
                "last_output_mode": "estrategia",
                "progression_stage": "strategy",
                "recent_turns": [],
                "last_intent_type": "general_information",
                "current_turn": {"output_mode": "estrategia", "topics_covered": ["divorcio", "alimentos"]},
            },
            "rendered_response_text": "",
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)

    final_output = processor.postprocess(
        request_id="req-strategy-priority",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "En este caso, lo mas conveniente es:" in final_output.response_text
    assert "divorcio unilateral" in final_output.response_text.lower()
    assert "Otra opcion seria" in final_output.response_text
    assert "manual" not in final_output.response_text.lower()


def test_ejecucion_contiene_pasos_accionables_y_no_repite_orientacion_basica(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-execution-transform",
        should_ask_first=False,
        query="Que hago manana?",
        practical=True,
    )

    def _progression(*args, **kwargs):
        return {
            "output_mode": "ejecucion",
            "progression_stage": "execution",
            "missing_focus": ["modalidad del divorcio"],
            "progression_state": {
                "facts_collected": ["hay_hijos"],
                "questions_asked": [],
                "topics_covered": ["divorcio"],
                "last_output_mode": "ejecucion",
                "progression_stage": "execution",
                "recent_turns": [],
                "last_intent_type": "action_now",
                "current_turn": {"output_mode": "ejecucion", "topics_covered": ["divorcio"]},
            },
            "rendered_response_text": "",
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)

    final_output = processor.postprocess(
        request_id="req-execution-transform",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "Manana podrias hacer esto:" in final_output.response_text
    assert "Donde ir:" in final_output.response_text
    assert "Que presentar:" in final_output.response_text
    assert "Que pedir:" in final_output.response_text
    assert "Si no tenes abogado:" in final_output.response_text
    assert "es un derecho" not in final_output.response_text.lower()


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

    assert "Hay base para orientar el reclamo." in final_output.response_text
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
    assert "conversational_intelligence" not in final_output.api_payload


def test_no_rompe_respuesta_si_conversational_intelligence_falla(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(conversation_id="conv-intelligence-fail", should_ask_first=True)

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(response_postprocessor_module, "resolve_conversational_intelligence", _raise)

    final_output = processor.postprocess(
        request_id="req-intelligence-fail",
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
    assert "dialogue_policy" in final_output.api_payload
    assert "conversational_intelligence" not in final_output.api_payload
    assert "intent_resolution" not in final_output.api_payload
    assert "execution_output" not in final_output.api_payload


def test_no_rompe_respuesta_si_intent_resolution_falla(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-intent-fail",
        should_ask_first=True,
        query="Que tengo que hacer mañana para empezar mi divorcio?",
        practical=True,
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(response_postprocessor_module, "resolve_intent_resolution", _raise)

    final_output = processor.postprocess(
        request_id="req-intent-fail",
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
    assert "dialogue_policy" in final_output.api_payload
    assert "intent_resolution" not in final_output.api_payload
    assert "execution_output" not in final_output.api_payload


def test_no_rompe_respuesta_si_execution_output_falla(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-execution-fail",
        should_ask_first=True,
        query="Que tengo que hacer mañana para empezar mi divorcio?",
        practical=True,
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(response_postprocessor_module, "build_execution_output", _raise)

    final_output = processor.postprocess(
        request_id="req-execution-fail",
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
    assert "dialogue_policy" in final_output.api_payload
    assert "intent_resolution" in final_output.api_payload
    assert "execution_output" not in final_output.api_payload


def test_no_rompe_respuesta_si_progression_policy_falla(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progression-fail",
        should_ask_first=False,
        query="No me pasa alimentos",
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _raise)

    final_output = processor.postprocess(
        request_id="req-progression-fail",
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
    assert "dialogue_policy" in final_output.api_payload
    assert "progression_policy" not in final_output.api_payload


def test_no_rompe_respuesta_si_strategic_decision_falla(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-strategy-fail",
        should_ask_first=False,
        query="No me pasa alimentos",
    )
    pipeline_payload["case_strategy"]["recommended_actions"] = [
        "Iniciar el reclamo principal con pedido de cuota provisoria.",
        "Reunir primero mas prueba antes de presentar.",
    ]

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estrategia",
            "progression_stage": "strategy",
            "missing_focus": ["ingresos del otro progenitor"],
            "decision_required": True,
            "decision_focus": "definir el camino principal del caso",
            "progression_state": {
                "facts_collected": ["hay_hijos"],
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

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)
    monkeypatch.setattr(response_postprocessor_module, "resolve_strategic_decision", _raise)

    final_output = processor.postprocess(
        request_id="req-strategy-fail",
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

    assert final_output.response_text
    assert "strategic_decision" not in final_output.api_payload
