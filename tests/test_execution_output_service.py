# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_execution_output_service.py
from __future__ import annotations

from app.services.execution_output_service import build_execution_output


def _conversation_state(*, blocking_missing: bool = False, hay_hijos: bool | None = None, known_facts: list[dict] | None = None) -> dict:
    facts = list(known_facts or [])
    if hay_hijos is not None:
        facts.append({"key": "hay_hijos", "value": hay_hijos})
    return {
        "conversation_id": "conv-exec",
        "turn_count": 2,
        "known_facts": facts,
        "missing_facts": [
            {"key": "domicilio_relevante", "label": "domicilio relevante", "purpose": "identify", "importance": "core"},
        ],
        "progress_signals": {
            "blocking_missing": blocking_missing,
            "case_completeness": "medium",
        },
    }


def _dialogue_policy(*, action: str = "ask", purpose: str = "quantify", importance: str = "relevant") -> dict:
    return {
        "action": action,
        "guidance_strength": "medium",
        "should_ask_first": action == "ask",
        "should_offer_partial_guidance": action in {"hybrid", "advise"},
        "dominant_missing_key": "ingresos_otro_progenitor",
        "dominant_missing_purpose": purpose,
        "dominant_missing_importance": importance,
    }


def _intention(intent_type: str = "action_now", urgency: str = "high") -> dict:
    return {
        "intent_type": intent_type,
        "urgency": urgency,
        "should_prioritize_execution_output": True,
    }


def _payload() -> dict:
    return {
        "query": "Que tengo que hacer mañana para empezar mi divorcio?",
        "quick_start": "Primer paso recomendado: Preparar presentacion inicial de divorcio con encuadre y competencia correctos.",
        "case_profile": {"case_domain": "divorcio"},
        "case_strategy": {
            "recommended_actions": [
                "Preparar presentacion inicial de divorcio con encuadre y competencia correctos.",
                "Redactar propuesta reguladora con los efectos necesarios del divorcio.",
                "Pedir cuota provisoria en el mismo inicio si corresponde.",
            ],
            "procedural_focus": [
                "Verificar competencia y ultimo domicilio conyugal.",
            ],
            "ordinary_missing_information": [
                "Completar propuesta reguladora y documentacion basica.",
            ],
        },
        "procedural_strategy": {
            "next_steps": [
                "Reunir prueba documental basica.",
                "Definir juzgado competente segun domicilios relevantes.",
            ],
            "missing_information": [
                "Documentacion basica y comprobantes relevantes.",
            ],
        },
        "output_modes": {
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
        },
        "conversational": {
            "question": "¿El divorcio seria de comun acuerdo o unilateral?",
        },
    }


def test_execution_output_genera_acciones_concretas_cuando_hay_base_suficiente():
    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=_payload(),
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    assert result["applies"] is True
    assert len(result["execution_output"]["what_to_do_now"]) >= 3


def test_no_presume_hijos_si_no_estan_confirmados():
    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=_payload(),
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    first_action = result["execution_output"]["what_to_do_now"][0]
    assert "si hay hijos" in first_action.lower()


def test_si_hay_hijos_confirmados_usa_redaccion_especifica():
    result = build_execution_output(
        conversation_state=_conversation_state(hay_hijos=True),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=_payload(),
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    first_action = result["execution_output"]["what_to_do_now"][0]
    assert "si hay hijos" not in first_action.lower()
    assert "vinculados a hijos" in first_action.lower()


def test_respuesta_ejecutiva_no_empieza_preguntando_si_el_intent_es_action_now():
    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=_payload(),
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    assert result["rendered_response_text"].startswith("Que podes hacer hoy o manana para empezar tu divorcio:")


def test_action_now_con_urgencia_alta_usa_encabezado_ejecutivo_temporal():
    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=_payload(),
        response_text="Respuesta base.",
        intent_resolution=_intention(intent_type="action_now", urgency="high"),
    )

    assert "hoy o manana" in result["rendered_response_text"].splitlines()[0].lower()


def test_seccion_de_competencia_usa_formulacion_prudente():
    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=_payload(),
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    where_to_go = result["execution_output"]["where_to_go"][0].lower()
    assert "jurisdiccion" in where_to_go
    assert "domicilio relevante" in where_to_go


def test_pregunta_residual_queda_al_final():
    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=_payload(),
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    lines = [line for line in result["rendered_response_text"].splitlines() if line.strip()]
    assert "Para afinar el paso siguiente" in lines[-1]


def test_divorcio_prioriza_modalidad_sobre_otras_preguntas():
    payload = _payload()
    payload["conversational"]["question"] = "¿Ya hubo cese de convivencia?"

    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=payload,
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    assert result["execution_output"]["followup_question"] == "¿El divorcio sería unilateral o de común acuerdo?"


def test_divorcio_si_modalidad_ya_definida_prioriza_cese_de_convivencia():
    payload = _payload()
    payload["facts"] = {"divorcio_modalidad": "unilateral"}

    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=payload,
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    assert result["execution_output"]["followup_question"] == "¿Ya hubo cese de convivencia?"


def test_alimentos_prioriza_convivencia_y_aporte_actual():
    payload = _payload()
    payload["case_profile"] = {"case_domain": "alimentos"}
    payload["classification"] = {"action_slug": "alimentos_hijos", "case_domain": "alimentos"}
    payload["conversational"]["question"] = "¿Tenés algún dato sobre ingresos o gastos relevantes?"

    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=payload,
        response_text="Respuesta base.",
        intent_resolution=_intention(intent_type="process_guidance", urgency="medium"),
    )

    assert result["execution_output"]["followup_question"] == "¿El niño o niña vive con quien consulta?"


def test_no_rompe_casos_donde_el_intent_no_es_practico():
    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(action="advise"),
        conversational_intelligence={"signals": {}},
        pipeline_payload=_payload(),
        response_text="Respuesta base.",
        intent_resolution=_intention(intent_type="general_information", urgency="low"),
    )

    assert result["applies"] is False
    assert result["rendered_response_text"] == "Respuesta base."


def test_mantiene_fallback_si_no_hay_base_suficiente():
    payload = {
        "query": "Que hago mañana?",
        "case_profile": {"case_domain": "divorcio"},
        "conversational": {"question": "¿El divorcio sería unilateral o de común acuerdo?"},
    }
    result = build_execution_output(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        pipeline_payload=payload,
        response_text="Respuesta base.",
        intent_resolution=_intention(),
    )

    assert result["applies"] is False
    assert result["rendered_response_text"] == "Respuesta base."
