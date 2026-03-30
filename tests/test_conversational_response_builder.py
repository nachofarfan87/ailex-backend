from __future__ import annotations

from app.services import output_mode_service
from app.services.conversational import (
    build_conversational_response,
    build_primary_question_for_alimentos,
    select_primary_question_for_alimentos,
)


def _alimentos_payload(
    query: str,
    *,
    facts: dict | None = None,
    missing_information: list[str] | None = None,
) -> dict:
    return {
        "query": query,
        "case_domain": "alimentos",
        "case_domains": ["alimentos"],
        "facts": facts or {},
        "reasoning": {
            "short_answer": "Hay una base inicial para orientar un reclamo de alimentos.",
        },
        "case_profile": {"case_domain": "alimentos"},
        "case_strategy": {
            "strategy_mode": "conservadora",
            "recommended_actions": [
                "Reunir documentación básica.",
                "Preparar el reclamo inicial.",
            ],
            "critical_missing_information": [],
            "ordinary_missing_information": missing_information
            or [
                "Precisar aportes actuales del otro progenitor.",
                "Precisar datos para notificación del otro progenitor.",
            ],
        },
        "procedural_strategy": {
            "missing_information": [
                "Confirmar si el hijo o hija convive con la persona consultante.",
            ]
        },
        "legal_decision": {
            "confidence_score": 0.63,
            "strategic_posture": "conservadora",
            "execution_readiness": "requiere_impulso_procesal",
        },
        "procedural_case_state": {"blocking_factor": "none"},
        "response_text": "Respuesta jurídica base.",
    }


def test_alimentos_guided_response_is_present_and_adds_value_before_question():
    result = output_mode_service.build_dual_output(
        _alimentos_payload("Quiero iniciar una demanda de alimentos por mi hija de 13 años")
    )

    conversational_response = result["conversational_response"]

    assert conversational_response["domain"] == "alimentos"
    assert conversational_response["mode"] == "guided_answer"
    assert len(conversational_response["messages"]) >= 5
    assert conversational_response["messages"][0]["type"] != "question"
    assert "¿" not in conversational_response["messages"][0]["text"]
    assert conversational_response["primary_question"]
    assert conversational_response["messages"][-1] == {
        "type": "question",
        "text": conversational_response["primary_question"],
    }
    question_messages = [item for item in conversational_response["messages"] if item["type"] == "question"]
    assert len(question_messages) == 1
    assert "edad" not in conversational_response["primary_question"].lower()
    assert "hijos" not in conversational_response["primary_question"].lower()
    assert conversational_response["question_selection"]["selected"]["key"] in {
        "aportes_actuales",
        "convivencia",
    }
    assert result["response_text"] == "Respuesta jurídica base."
    assert "output_modes" in result
    assert "conversational" in result


def test_real_language_non_payment_does_not_repeat_current_support_question():
    result = build_conversational_response(
        _alimentos_payload("No me pasa plata hace meses")
    )

    assert result is not None
    assert result["domain"] == "alimentos"
    assert result["question_selection"]["selected"]["key"] != "aportes_actuales"
    assert result["question_selection"]["selected"]["key"] in {
        "convivencia",
        "urgencia",
        "notificacion",
        "ingresos",
    }


def test_non_compliance_and_claim_intent_do_not_generate_redundant_question():
    result = build_conversational_response(
        _alimentos_payload("No cumple y quiero reclamar alimentos")
    )

    assert result is not None
    assert result["question_selection"]["selected"]["key"] != "aportes_actuales"


def test_unknown_address_query_does_not_repeat_notification_problem():
    result = build_conversational_response(
        _alimentos_payload("No sé nada de él y quiero reclamar")
    )

    assert result is not None
    assert result["question_selection"]["selected"]["key"] != "notificacion"
    assert "ubicar" not in result["primary_question"].lower()
    assert "domicilio" not in result["primary_question"].lower()


def test_start_intent_is_detected_without_demand_or_trial_words():
    result = build_conversational_response(
        _alimentos_payload("Quiero pedir alimentos, ¿qué tengo que hacer?")
    )

    assert result is not None
    assert result["question_selection"]["selected"]["key"] in {
        "aportes_actuales",
        "convivencia",
        "notificacion",
        "ingresos",
    }


def test_my_child_reference_does_not_force_assumed_convivencia():
    result = build_conversational_response(
        _alimentos_payload("Es mi hija pero vive con su padre")
    )

    assert result is not None
    assert result["question_selection"]["selected"]["key"] != "convivencia"


def test_resolved_slots_force_other_useful_question():
    context = {
        "known_facts": {
            "aportes_actuales": False,
            "convivencia_hijo": True,
        },
        "missing_facts": [
            "Determinar ingresos del otro progenitor.",
            "Precisar datos para notificación del otro progenitor.",
        ],
        "query_text": "Quiero iniciar una demanda de alimentos",
        "clarification_context": {},
    }
    question = select_primary_question_for_alimentos(
        known_facts=context["known_facts"],
        missing_facts=context["missing_facts"],
        query_text=context["query_text"],
        clarification_context=context["clarification_context"],
    )
    selection = build_primary_question_for_alimentos(context)

    assert question
    assert selection is not None
    assert selection["selected"]["text"] == question
    assert selection["selected"]["key"] in {
        "notificacion",
        "ingresos",
        "urgencia",
    }


def test_copy_is_professional_in_messages_and_question():
    result = output_mode_service.build_dual_output(
        _alimentos_payload("Quiero iniciar una demanda de alimentos por mi hija")
    )

    conversational_response = result["conversational_response"]
    all_text = " ".join(item["text"] for item in conversational_response["messages"])
    assert "podés" in all_text
    assert "defensoría" in all_text
    assert "está" in all_text
    # Fase 5.5: primary_question is now simplified — check it reads naturally
    pq = conversational_response["primary_question"]
    assert "¿" in pq and pq.endswith("?")
    # At least one natural-language marker present (vos-form or plain Spanish)
    assert any(w in pq.lower() for w in ("algún", "está", "sabés", "plata", "vive con vos", "ubicar", "trabaja"))


def test_question_selection_metadata_is_serialized_without_breaking_contract():
    result = output_mode_service.build_dual_output(
        _alimentos_payload("Quiero iniciar una demanda de alimentos por mi hija de 13 años")
    )

    conversational_response = result["conversational_response"]
    assert conversational_response["primary_question"]
    # Fase 5.5: primary_question is simplified; selected.text preserves the original formal version.
    # Both must be non-empty and the simplified version should be a proper question.
    assert conversational_response["primary_question"]
    assert conversational_response["question_selection"]["selected"]["text"]
    assert conversational_response["primary_question"].startswith("¿")
    assert conversational_response["question_selection"]["selected"]["score"] > 0
    assert conversational_response["question_selection"]["selected"]["score_breakdown"]["total"] == conversational_response["question_selection"]["selected"]["score"]
    assert isinstance(conversational_response["question_selection"]["adaptive_context"], dict)
    assert conversational_response["question_selection"]["adaptive_context"]["conversation_quality"] in {
        "high",
        "medium",
        "low",
    }
    assert isinstance(conversational_response["conversation_memory"], dict)
    assert isinstance(conversational_response["conversation_memory"]["canonical_signals"], dict)
    assert isinstance(conversational_response["conversation_memory"]["adaptive_context"], dict)
    assert conversational_response["conversation_memory"]["adaptive_context"]["conversation_quality"] in {
        "high",
        "medium",
        "low",
    }


def test_unsupported_domain_does_not_break_legacy_output():
    payload = _alimentos_payload("Quiero saber sobre divorcio")
    payload["case_domain"] = "divorcio"
    payload["case_domains"] = ["divorcio"]
    payload["case_profile"] = {"case_domain": "divorcio"}

    result = output_mode_service.build_dual_output(payload)

    assert "conversational_response" not in result
    assert result["output_modes"]["user"]["summary"]
    assert result["conversational"]["message"]
