from __future__ import annotations

from app.services.clarification_flow_service import prepare_legal_query_turn


def test_divorcio_child_answer_with_singular_child_marks_slot_as_resolved():
    prepared = prepare_legal_query_turn(
        query="Esta mi hija de 3 meses",
        facts={},
        metadata={
            "clarification_context": {
                "base_query": "Quiero divorciarme",
                "case_domain": "divorcio",
                "last_question": "¿Hay hijos menores o con capacidad restringida?",
                "asked_questions": ["¿Hay hijos menores o con capacidad restringida?"],
                "known_facts": {},
            }
        },
    )

    known_facts = prepared.metadata["clarification_context"]["known_facts"]
    clarified_fields = prepared.metadata["clarification_context"]["clarified_fields"]

    assert known_facts["hay_hijos"] is True
    assert known_facts["hay_hijos_edad"] == "informada"
    assert "hay_hijos" in clarified_fields
    assert "hay_hijos_edad" in clarified_fields
    assert prepared.metadata["clarification_context"]["answer_status"] == "precise"


def test_divorcio_follow_up_keeps_base_query_after_switch_to_advice():
    prepared = prepare_legal_query_turn(
        query="Sera un divorcio unilateral",
        facts={"hay_hijos": True, "hay_hijos_edad": "informada"},
        metadata={
            "clarification_context": {
                "base_query": "Quiero divorciarme",
                "case_domain": "divorcio",
                "known_facts": {"hay_hijos": True, "hay_hijos_edad": "informada"},
                "clarified_fields": ["hay_hijos", "hay_hijos_edad"],
            }
        },
    )

    known_facts = prepared.metadata["clarification_context"]["known_facts"]

    assert prepared.effective_query.startswith("Quiero divorciarme.")
    assert "divorcio unilateral" in prepared.effective_query.lower()
    assert known_facts["divorcio_modalidad"] == "unilateral"
    assert known_facts["hay_acuerdo"] is False
    assert known_facts["hay_hijos"] is True


def test_divorcio_convenio_answer_extracts_arrangement_facts_and_keeps_textual_detail():
    prepared = prepare_legal_query_turn(
        query="El convenio incluye 20% de mi sueldo para alimentos y regimen comunicacional para 3 dias de la semana con mi hija.",
        facts={
            "hay_hijos": True,
            "hay_hijos_edad": "informada",
            "divorcio_modalidad": "unilateral",
            "hay_acuerdo": False,
        },
        metadata={
            "clarification_context": {
                "base_query": "Quiero divorciarme",
                "case_domain": "divorcio",
                "known_facts": {
                    "hay_hijos": True,
                    "hay_hijos_edad": "informada",
                    "divorcio_modalidad": "unilateral",
                    "hay_acuerdo": False,
                },
                "clarified_fields": [
                    "hay_hijos",
                    "hay_hijos_edad",
                    "divorcio_modalidad",
                    "hay_acuerdo",
                ],
            }
        },
    )

    known_facts = prepared.metadata["clarification_context"]["known_facts"]

    assert known_facts["convenio_regulador"] is True
    assert known_facts["alimentos_definidos"] is True
    assert known_facts["cuota_alimentaria_porcentaje"] == "20%"
    assert known_facts["regimen_comunicacional"] is True
    assert known_facts["regimen_comunicacional_frecuencia"] == "3 dias por semana"
    assert "hay convenio regulador" in prepared.effective_query.lower()
    assert "detalle textual del usuario" in prepared.effective_query.lower()
    assert "20% de mi sueldo" in prepared.effective_query.lower()


def test_alimentos_si_corto_se_interpreta_y_permita_avanzar():
    prepared = prepare_legal_query_turn(
        query="Si",
        facts={},
        metadata={
            "clarification_context": {
                "base_query": "Quiero iniciar alimentos para mi hijo",
                "case_domain": "alimentos",
                "last_question": "¿El otro padre o madre le pasa algo de plata actualmente?",
                "asked_questions": ["¿El otro padre o madre le pasa algo de plata actualmente?"],
                "known_facts": {},
            }
        },
    )

    context = prepared.metadata["clarification_context"]

    assert context["answer_status"] == "precise"
    assert context["response_quality"] == "short_valid"
    assert context["response_strategy"] == "advance"
    assert context["known_facts"]["aportes_actuales"] is True
    assert prepared.effective_query == "Quiero iniciar alimentos para mi hijo"


def test_followup_ambiguo_mantiene_limite_y_repregunta():
    prepared = prepare_legal_query_turn(
        query="No se",
        facts={},
        metadata={
            "clarification_context": {
                "base_query": "Quiero iniciar alimentos para mi hijo",
                "case_domain": "alimentos",
                "last_question": "¿El otro padre o madre le pasa algo de plata actualmente?",
                "asked_questions": ["¿El otro padre o madre le pasa algo de plata actualmente?"],
                "known_facts": {},
            }
        },
    )

    context = prepared.metadata["clarification_context"]

    assert context["response_quality"] == "ambiguous"
    assert context["response_strategy"] == "clarify"
    assert context["precision_required"] is True
    assert context["limit_explanation"]


def test_respuesta_sin_hijos_consolida_slot_y_no_lo_deja_ambiguo():
    prepared = prepare_legal_query_turn(
        query="Sin hijos",
        facts={},
        metadata={
            "clarification_context": {
                "base_query": "Quiero divorciarme",
                "case_domain": "divorcio",
                "last_question": "Â¿Hay hijos menores o con capacidad restringida?",
                "asked_questions": ["Â¿Hay hijos menores o con capacidad restringida?"],
                "known_facts": {},
            }
        },
    )

    context = prepared.metadata["clarification_context"]

    assert context["known_facts"]["hay_hijos"] is False
    assert context["answer_status"] == "precise"
    assert context["response_strategy"] == "advance"
