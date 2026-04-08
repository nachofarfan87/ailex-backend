# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_response_postprocessor_conversation_state.py
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
    assert "Para avanzar de forma concreta, podes hacer esto:" in final_output.response_text or "Si quisieras mover esto ya, estos serian los pasos:" in final_output.response_text
    assert "Donde ir:" in final_output.response_text or "Que presentar:" in final_output.response_text
    assert "Para ajustar el paso siguiente" not in final_output.response_text


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
    assert "el caso ya se puede ordenar mejor" in second_output.response_text.lower()
    assert "con lo que me contaste hasta ahora" in second_output.response_text.lower()
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

    assert "el caso ya se puede ordenar mejor" in final_output.response_text.lower()
    assert "con lo que me contaste hasta ahora:" in final_output.response_text.lower()
    assert "lo que todavia falta definir" in final_output.response_text.lower()
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

    assert "hoy, lo mas solido es ir por este camino:" in final_output.response_text.lower() or "si ordenamos esto estrategicamente, la mejor via es:" in final_output.response_text.lower() or "con lo que hay hoy, conviene avanzar asi:" in final_output.response_text.lower()
    assert "el paso que priorizaria ahora es:" in final_output.response_text.lower() or "si tuviera que ordenar el siguiente movimiento" in final_output.response_text.lower()
    assert "la otra via existe, pero hoy queda mas atras:" in final_output.response_text.lower() or "como alternativa se puede pensar esta via, pero hoy queda en segundo plano:" in final_output.response_text.lower()
    assert "." in final_output.response_text
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

    assert "hoy, lo mas solido es ir por este camino:" in final_output.response_text.lower() or "si ordenamos esto estrategicamente, la mejor via es:" in final_output.response_text.lower() or "con lo que hay hoy, conviene avanzar asi:" in final_output.response_text.lower()
    assert "divorcio unilateral" in final_output.response_text.lower()
    assert "la otra via existe, pero hoy queda mas atras:" in final_output.response_text.lower() or "como alternativa se puede pensar esta via, pero hoy queda en segundo plano:" in final_output.response_text.lower()
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

    assert "Para avanzar de forma concreta, podes hacer esto:" in final_output.response_text or "Si quisieras mover esto ya, estos serian los pasos:" in final_output.response_text
    assert "Donde ir:" in final_output.response_text
    assert "Que presentar:" in final_output.response_text
    assert len(final_output.response_text) <= 600
    assert "es un derecho" not in final_output.response_text.lower()


def test_execution_no_pregunta_si_no_bloquea(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-execution-no-followup",
        should_ask_first=False,
        query="Que hago manana?",
        practical=True,
    )
    pipeline_payload["conversational"]["question"] = ""

    def _progression(*args, **kwargs):
        return {
            "output_mode": "ejecucion",
            "progression_stage": "execution",
            "missing_focus": [],
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

    def _build_execution_output(**kwargs):
        return {
            "applies": True,
            "rendered_response_text": "Para avanzar de forma concreta, podes hacer esto:\n1. Presentar escrito.\n\nDonde ir:\n- Juzgado competente.",
            "execution_output": {
                "what_to_do_now": ["Presentar escrito."],
                "where_to_go": ["Juzgado competente."],
                "what_to_request": [],
                "documents_needed": [],
            },
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)
    monkeypatch.setattr(response_postprocessor_module, "build_execution_output", _build_execution_output)

    final_output = processor.postprocess(
        request_id="req-execution-no-followup",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "?" not in final_output.response_text


def test_strategy_pregunta_solo_con_blocking():
    processor = ResponsePostprocessor()

    no_blocking = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "quantify",
                "dominant_missing_importance": "core",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": False,
                    "case_completeness": "medium",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Falta un dato clave?"}},
        output_mode="estrategia",
    )
    with_blocking = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "quantify",
                "dominant_missing_importance": "core",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": True,
                    "case_completeness": "medium",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Falta un dato clave?"}},
        output_mode="estrategia",
    )

    assert no_blocking == ""
    assert "dato clave" in with_blocking


def test_execution_incluye_pasos_concretos(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-execution-concrete",
        should_ask_first=False,
        query="Que hago manana?",
        practical=True,
    )

    def _progression(*args, **kwargs):
        return {
            "output_mode": "ejecucion",
            "progression_stage": "execution",
            "missing_focus": [],
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
        request_id="req-execution-concrete",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "1." in final_output.response_text
    assert "2." in final_output.response_text or "Donde ir:" in final_output.response_text


def test_no_duplica_quick_start_si_ya_hay_execution():
    processor = ResponsePostprocessor()

    response_text = processor._prepend_quick_start(  # noqa: SLF001
        "Para avanzar de forma concreta, podes hacer esto:\n1. Presentar escrito.",
        "Primer paso recomendado: Presentar escrito.",
        output_mode="orientacion_inicial",
    )

    assert response_text.startswith("Para avanzar de forma concreta, podes hacer esto:")
    assert response_text.count("Primer paso recomendado:") == 0


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
    import app.services.response_composition_service as response_composition_module

    monkeypatch.setattr(response_composition_module, "resolve_strategic_decision", _raise)

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


def test_pipeline_adjunta_case_state_snapshot_persistente(db_session):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-live",
        should_ask_first=False,
        query="Quiero reclamar alimentos para mi hija y no me esta pagando",
    )
    pipeline_payload["missing_facts"] = ["ingresos_otro_progenitor"]
    pipeline_payload["critical_missing"] = ["ingresos_otro_progenitor"]
    pipeline_payload["detected_facts"] = [
        {
            "key": "hay_hijos",
            "value": True,
            "source_type": "user_explicit",
            "status": "confirmed",
        }
    ]
    pipeline_payload["output_mode"] = "estrategia"

    final_output = processor.postprocess(
        request_id="req-case-live",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    snapshot = final_output.api_payload["case_state_snapshot"]
    assert snapshot["case_state"]["conversation_id"] == "conv-case-live"
    assert snapshot["case_state"]["case_type"] == "alimentos_hijos"
    assert snapshot["case_state"]["case_stage"] in {"analisis_estrategico", "recopilacion_hechos"}
    assert snapshot["confirmed_facts"]["hay_hijos"] is True
    assert snapshot["open_needs"][0]["need_key"] == "hecho::ingresos_otro_progenitor"


def test_api_payload_adjunta_case_summary_y_se_persiste(db_session):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-summary",
        should_ask_first=False,
        query="Quiero reclamar alimentos para mi hija",
    )
    pipeline_payload["missing_facts"] = ["ingresos_otro_progenitor"]

    final_output = processor.postprocess(
        request_id="req-case-summary",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "case_summary" in final_output.api_payload
    assert final_output.api_payload["case_summary"]["applies"] is True
    assert final_output.api_payload["case_summary"]["summary_text"]

    snapshot = final_output.api_payload["case_state_snapshot"]
    assert snapshot["case_state"]["summary_text"] == final_output.api_payload["case_summary"]["summary_text"]


def test_resumen_refleja_progreso_del_caso(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-summary-progress",
        should_ask_first=False,
        query="Quiero iniciar mi divorcio",
        practical=True,
    )
    pipeline_payload["missing_facts"] = [
        {
            "need_key": "estrategia::modalidad_divorcio",
            "category": "estrategia",
            "priority": "high",
            "suggested_question": "Â¿El divorcio seria unilateral o de comun acuerdo?",
        }
    ]

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estrategia",
            "progression_stage": "strategy",
            "missing_focus": ["modalidad del divorcio"],
            "progression_state": {
                "facts_collected": ["hay_hijos"],
                "questions_asked": [],
                "topics_covered": ["divorcio"],
                "last_output_mode": "estrategia",
                "progression_stage": "strategy",
                "recent_turns": [],
                "last_intent_type": "general_information",
                "current_turn": {"output_mode": "estrategia", "topics_covered": ["divorcio"]},
            },
            "rendered_response_text": "",
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)

    final_output = processor.postprocess(
        request_id="req-case-summary-progress",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    summary_text = final_output.api_payload["case_summary"]["summary_text"].lower()
    assert "divorcio" in summary_text
    assert "unilateral o de comun acuerdo" in summary_text or "via principal" in summary_text


def test_no_rompe_respuesta_principal_si_falla_case_summary_service(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-summary-fail",
        should_ask_first=False,
        query="Quiero reclamar alimentos",
    )

    def _explode(*args, **kwargs):
        raise RuntimeError("summary down")

    monkeypatch.setattr(response_postprocessor_module.case_summary_service, "build_case_summary", _explode)

    final_output = processor.postprocess(
        request_id="req-case-summary-fail",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert final_output.response_text
    assert "case_summary" not in final_output.api_payload


def test_api_payload_adjunta_case_followup(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-followup",
        should_ask_first=False,
        query="Quiero iniciar mi divorcio",
        practical=True,
    )
    pipeline_payload["missing_facts"] = [
        {
            "need_key": "estrategia::modalidad_divorcio",
            "category": "estrategia",
            "priority": "high",
            "suggested_question": "¿El divorcio sería unilateral o de común acuerdo?",
            "reason": "Define la vía estratégica inmediata.",
        }
    ]

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estrategia",
            "progression_stage": "strategy",
            "missing_focus": ["modalidad del divorcio"],
            "progression_state": {
                "facts_collected": ["hay_hijos"],
                "questions_asked": [],
                "topics_covered": ["divorcio"],
                "last_output_mode": "estrategia",
                "progression_stage": "strategy",
                "recent_turns": [],
                "last_intent_type": "general_information",
                "current_turn": {"output_mode": "estrategia", "topics_covered": ["divorcio"]},
            },
            "rendered_response_text": "",
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)

    final_output = processor.postprocess(
        request_id="req-case-followup",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "case_followup" in final_output.api_payload
    assert final_output.api_payload["case_followup"]["should_ask"] is True
    assert final_output.api_payload["case_followup"]["need_key"] == "estrategia::modalidad_divorcio"


def test_respuesta_se_siente_acumulativa_en_estructuracion(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progress-narrative-structuring",
        should_ask_first=False,
        query="No me pasa alimentos",
    )
    pipeline_payload["missing_facts"] = ["ingresos_otro_progenitor"]

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
        request_id="req-progress-narrative-structuring",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "case_progress_narrative" in final_output.api_payload
    assert "ya esta claro" in final_output.response_text.lower() or "con lo que ya sabemos" in final_output.response_text.lower()
    assert "todavia falta" in final_output.response_text.lower()


def test_respuesta_refleja_progreso_en_estrategia(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progress-narrative-strategy",
        should_ask_first=False,
        query="Quiero iniciar mi divorcio",
        practical=True,
    )
    pipeline_payload["missing_facts"] = [
        {
            "need_key": "estrategia::modalidad_divorcio",
            "category": "estrategia",
            "priority": "high",
            "suggested_question": "¿El divorcio seria unilateral o de comun acuerdo?",
        }
    ]

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estrategia",
            "progression_stage": "strategy",
            "missing_focus": ["modalidad del divorcio"],
            "progression_state": {
                "facts_collected": ["hay_hijos"],
                "questions_asked": [],
                "topics_covered": ["divorcio"],
                "last_output_mode": "estrategia",
                "progression_stage": "strategy",
                "recent_turns": [],
                "last_intent_type": "general_information",
                "current_turn": {"output_mode": "estrategia", "topics_covered": ["divorcio"]},
            },
            "rendered_response_text": "",
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)

    final_output = processor.postprocess(
        request_id="req-progress-narrative-strategy",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "case_progress_narrative" in final_output.api_payload
    assert "base suficiente" in final_output.response_text.lower() or "con la informacion reunida" in final_output.response_text.lower()


def test_priority_block_se_suprime_si_followup_ya_pregunta_lo_mismo(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progress-narrative-priority-dedupe",
        should_ask_first=False,
        query="Quiero reclamar alimentos",
    )
    pipeline_payload["missing_facts"] = [
        {
            "need_key": "hecho::ingresos_otro_progenitor",
            "category": "hecho",
            "priority": "high",
            "suggested_question": "¿Podés precisar los ingresos del otro progenitor?",
        }
    ]

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
        request_id="req-progress-priority-dedupe",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    narrative = final_output.api_payload["case_progress_narrative"]
    assert narrative["priority_block"] == ""
    assert "lo siguiente mas util es definir los ingresos del otro progenitor" not in final_output.response_text.lower()


def test_contradiction_block_aparece_en_estructuracion(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progress-narrative-contradiction",
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

    first_output = processor.postprocess(
        request_id="req-progress-contradiction-1",
        normalized_input=normalized_input,
        pipeline_payload={**pipeline_payload, "facts": {"hay_hijos": True, "ingresos_otro_progenitor": 200000}},
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )
    case_state_service.append_case_event(
        db_session,
        conversation_id="conv-progress-narrative-contradiction",
        event_type="fact_contradiction_detected",
        payload={
            "fact_key": "ingresos_otro_progenitor",
            "stored_value": 200000,
            "incoming_value": 500000,
        },
    )
    second_output = processor.postprocess(
        request_id="req-progress-contradiction-2",
        normalized_input=normalized_input,
        pipeline_payload={**pipeline_payload, "facts": {"hay_hijos": True, "ingresos_otro_progenitor": 500000}},
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "case_progress_narrative" in second_output.api_payload
    assert "inconsistente" in second_output.api_payload["case_progress_narrative"]["contradiction_block"].lower() or "contradictoria" in second_output.api_payload["case_progress_narrative"]["contradiction_block"].lower()
    assert "fact_key" not in second_output.response_text.lower()


def test_contradiction_block_no_se_fuerza_en_ejecucion(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progress-narrative-contradiction-execution",
        should_ask_first=False,
        query="Que hago manana?",
        practical=True,
    )

    def _progression(*args, **kwargs):
        return {
            "output_mode": "ejecucion",
            "progression_stage": "execution",
            "missing_focus": [],
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

    processor.postprocess(
        request_id="req-progress-contradiction-execution-1",
        normalized_input=normalized_input,
        pipeline_payload={**pipeline_payload, "facts": {"hay_hijos": True, "domicilio_relevante": "Cordoba"}},
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )
    final_output = processor.postprocess(
        request_id="req-progress-contradiction-execution-2",
        normalized_input=normalized_input,
        pipeline_payload={**pipeline_payload, "facts": {"hay_hijos": True, "domicilio_relevante": "Rosario"}},
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert final_output.api_payload["case_progress_narrative"]["contradiction_block"] == ""


def test_en_ejecucion_no_mete_narrativa_excesiva(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progress-narrative-execution",
        should_ask_first=False,
        query="Que hago manana?",
        practical=True,
    )

    def _progression(*args, **kwargs):
        return {
            "output_mode": "ejecucion",
            "progression_stage": "execution",
            "missing_focus": [],
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
        request_id="req-progress-narrative-execution",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert len(final_output.response_text) <= 600


def test_no_repregunta_facts_ya_confirmados(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progress-narrative-confirmed",
        should_ask_first=False,
        query="Quiero reclamar alimentos y ya se cuanto gana la otra parte",
    )
    pipeline_payload["facts"] = {
        "hay_hijos": True,
        "ingresos_otro_progenitor": 200000,
    }
    pipeline_payload["missing_facts"] = [
        {
            "need_key": "hecho::ingresos_otro_progenitor",
            "category": "hecho",
            "priority": "high",
            "suggested_question": "¿Podés precisar los ingresos del otro progenitor?",
        }
    ]

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estructuracion",
            "progression_stage": "structuring_case",
            "missing_focus": [],
            "progression_state": {
                "facts_collected": ["hay_hijos", "ingresos_otro_progenitor"],
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
        request_id="req-progress-narrative-confirmed",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "ingresos del otro progenitor" not in str(final_output.api_payload.get("case_followup", {}).get("question", "")).lower()


def test_followup_final_proviene_del_need_dominante_del_caso(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-followup-dominant",
        should_ask_first=False,
        query="Quiero iniciar mi divorcio",
        practical=True,
    )
    pipeline_payload["missing_facts"] = [
        {
            "need_key": "economico::ingresos_otro_progenitor",
            "category": "economico",
            "priority": "high",
            "suggested_question": "¿Podés precisar los ingresos del otro progenitor?",
        },
        {
            "need_key": "estrategia::modalidad_divorcio",
            "category": "estrategia",
            "priority": "critical",
            "suggested_question": "¿El divorcio sería unilateral o de común acuerdo?",
            "reason": "Define la vía estratégica inmediata.",
        },
    ]

    def _progression(*args, **kwargs):
        return {
            "output_mode": "estrategia",
            "progression_stage": "strategy",
            "missing_focus": ["modalidad del divorcio"],
            "progression_state": {
                "facts_collected": ["hay_hijos"],
                "questions_asked": [],
                "topics_covered": ["divorcio"],
                "last_output_mode": "estrategia",
                "progression_stage": "strategy",
                "recent_turns": [],
                "last_intent_type": "general_information",
                "current_turn": {"output_mode": "estrategia", "topics_covered": ["divorcio"]},
            },
            "rendered_response_text": "",
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)

    final_output = processor.postprocess(
        request_id="req-case-followup-dominant",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "¿El divorcio sería unilateral o de común acuerdo?" in final_output.response_text
    assert final_output.api_payload["case_followup"]["need_key"] == "estrategia::modalidad_divorcio"


def test_no_repregunta_en_ejecucion_si_ya_hay_acciones_suficientes(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-followup-execution",
        should_ask_first=False,
        query="Que hago manana?",
        practical=True,
    )
    pipeline_payload["missing_facts"] = [
        {
            "need_key": "estrategia::modalidad_divorcio",
            "category": "estrategia",
            "priority": "critical",
            "suggested_question": "¿El divorcio sería unilateral o de común acuerdo?",
        }
    ]

    def _progression(*args, **kwargs):
        return {
            "output_mode": "ejecucion",
            "progression_stage": "execution",
            "missing_focus": [],
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

    def _build_execution_output(**kwargs):
        return {
            "applies": True,
            "rendered_response_text": "Para avanzar de forma concreta, podes hacer esto:\n1. Presentar escrito.\n2. Reunir documentacion.\n\nDonde ir:\n- Juzgado competente.",
            "execution_output": {
                "what_to_do_now": ["Presentar escrito.", "Reunir documentacion."],
                "where_to_go": ["Juzgado competente."],
                "what_to_request": [],
                "documents_needed": [],
            },
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_progression_policy", _progression)
    monkeypatch.setattr(response_postprocessor_module, "build_execution_output", _build_execution_output)

    final_output = processor.postprocess(
        request_id="req-case-followup-execution",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert final_output.api_payload["case_followup"]["should_ask"] is False
    assert "Para ajustar el paso siguiente" not in final_output.response_text


def test_case_state_matches_progression(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-stage-align",
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
        request_id="req-case-stage-align",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    snapshot = final_output.api_payload["case_state_snapshot"]
    assert snapshot["case_state"]["case_stage"] == "analisis_estructurado"


def test_pipeline_adjunta_y_persiste_case_progress(db_session):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-progress",
        should_ask_first=False,
        query="Quiero reclamar alimentos por mi hija",
    )

    final_output = processor.postprocess(
        request_id="req-case-progress",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert "case_progress" in final_output.api_payload
    assert "case_progress_snapshot" in final_output.api_payload
    assert final_output.api_payload["case_progress"]["stage"] in {
        "exploracion",
        "estructuracion",
        "decision",
        "ejecucion",
        "bloqueado",
        "inconsistente",
    }
    assert final_output.api_payload["conversation_state"]["case_progress"]["stage"] == final_output.api_payload["case_progress"]["stage"]
    loaded_state = response_postprocessor_module.conversation_state_service.load_state(
        db_session,
        conversation_id="conv-case-progress",
    )
    assert loaded_state["case_progress"]["stage"] == final_output.api_payload["case_progress"]["stage"]
    assert loaded_state["case_progress_snapshot"]["stage"] == final_output.api_payload["case_progress_snapshot"]["stage"]


def test_no_rompe_respuesta_si_case_progress_falla(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-case-progress-fail",
        should_ask_first=False,
    )

    monkeypatch.setattr(response_postprocessor_module, "build_case_progress", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    final_output = processor.postprocess(
        request_id="req-case-progress-fail",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert final_output.response_text
    assert "case_progress" not in final_output.api_payload
    assert "case_followup" in final_output.api_payload


def test_pipeline_case_progress_afecta_followup_y_smart_strategy(db_session, monkeypatch):
    processor = ResponsePostprocessor()
    normalized_input, pipeline_payload = _payload(
        conversation_id="conv-progress-driven-behavior",
        should_ask_first=False,
        query="No me pasa alimentos y hay datos contradictorios sobre el domicilio",
    )
    pipeline_payload["case_state_snapshot"] = {
        "case_state": {"case_stage": "analisis_estructurado"},
        "confirmed_facts": {"hay_hijos": True},
        "probable_facts": {},
        "open_needs": [],
        "contradictions": [
            {"key": "domicilio_relevante", "prev_value": "Jujuy", "new_value": "Salta", "detected_at": 2},
        ],
    }

    def _attach_case_state(*, db, normalized_input, pipeline_payload, api_payload):
        api_payload["case_state_snapshot"] = dict(pipeline_payload.get("case_state_snapshot") or {})
        pipeline_payload["case_state_snapshot"] = dict(api_payload["case_state_snapshot"])

    monkeypatch.setattr(processor, "_attach_case_state", _attach_case_state)

    final_output = processor.postprocess(
        request_id="req-progress-driven-behavior",
        normalized_input=normalized_input,
        pipeline_payload=pipeline_payload,
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
        db=db_session,
    )

    assert final_output.api_payload["case_progress"]["next_step_type"] == "resolve_contradiction"
    assert final_output.api_payload["case_followup"]["should_ask"] is True
    assert "domicilio relevante" in final_output.api_payload["case_followup"]["question"].lower()
    assert final_output.api_payload["smart_strategy"]["strategy_mode"] in {"clarify_critical", "orient_with_prudence"}
