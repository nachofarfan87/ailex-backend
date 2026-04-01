# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_intent_resolution_service.py
from __future__ import annotations

from app.services.intent_resolution_service import resolve_intent_resolution


def _normalized_input(query: str) -> dict:
    return {
        "query": query,
        "metadata": {"conversation_id": "conv-intent"},
    }


def test_detecta_action_now_con_que_tengo_que_hacer_manana():
    result = resolve_intent_resolution(
        normalized_input=_normalized_input("Que tengo que hacer mañana para empezar mi divorcio?"),
        dialogue_policy={"action": "ask"},
        conversational_intelligence={"signals": {}},
        pipeline_payload={"query": "Que tengo que hacer mañana para empezar mi divorcio?"},
    )

    assert result["intent_type"] == "action_now"


def test_detecta_urgencia_alta_con_manana_y_hoy():
    result = resolve_intent_resolution(
        normalized_input=_normalized_input("Hoy o mañana como arranco?"),
        dialogue_policy={"action": "hybrid"},
        conversational_intelligence={"signals": {}},
        pipeline_payload={"query": "Hoy o mañana como arranco?"},
    )

    assert result["urgency"] == "high"


def test_no_rompe_intent_no_practico_y_cae_en_general_information():
    result = resolve_intent_resolution(
        normalized_input=_normalized_input("Explicame la diferencia entre divorcio y separacion."),
        dialogue_policy={"action": "advise"},
        conversational_intelligence={"signals": {}},
        pipeline_payload={"query": "Explicame la diferencia entre divorcio y separacion."},
    )

    assert result["intent_type"] in {"clarification_needed", "general_information"}
