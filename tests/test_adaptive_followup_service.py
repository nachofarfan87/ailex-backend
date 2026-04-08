# backend/tests/test_adaptive_followup_service.py
from __future__ import annotations

from app.services.adaptive_followup_service import resolve_followup_decision


def test_no_pregunta_si_missing_facts_vacio():
    decision = resolve_followup_decision(
        known_facts={"hay_hijos": True},
        missing_facts=[],
        conversation_state={},
        previous_questions=[],
        last_user_messages=[],
    )

    assert decision["should_ask"] is False
    assert decision["priority_question"] is None
    assert decision["progress_state"] == "complete"
    assert decision["user_cannot_answer"] is False
    assert decision["recent_progress"] is False


def test_no_pregunta_si_known_facts_ya_cubren_missing():
    decision = resolve_followup_decision(
        known_facts={"ingresos_otro_progenitor": 200000},
        missing_facts=[
            {
                "key": "ingresos_otro_progenitor",
                "label": "ingresos del otro progenitor",
                "importance": "critical",
                "impact_on_strategy": True,
                "suggested_question": "¿Podes precisar los ingresos del otro progenitor?",
            }
        ],
        conversation_state={},
        previous_questions=[],
        last_user_messages=[],
    )

    assert decision["should_ask"] is False
    assert decision["priority_question"] is None
    assert decision["progress_state"] == "complete"


def test_user_cannot_answer_y_missing_critico_bloquea():
    decision = resolve_followup_decision(
        known_facts={},
        missing_facts=[
            {
                "key": "jurisdiccion",
                "label": "la jurisdiccion",
                "importance": "critical",
                "impact_on_strategy": True,
                "suggested_question": "¿En que provincia o jurisdiccion tramitarias esto?",
            }
        ],
        conversation_state={},
        previous_questions=[],
        last_user_messages=["No se", "No tengo ese dato"],
    )

    assert decision["user_cannot_answer"] is True
    assert decision["progress_state"] == "blocked"
    assert decision["should_ask"] is False
    assert decision["priority_question"] is None


def test_user_cannot_answer_y_missing_bajo_estanca():
    decision = resolve_followup_decision(
        known_facts={},
        missing_facts=[
            {
                "key": "gastos_extraordinarios",
                "label": "gastos extraordinarios",
                "importance": "low",
                "impact_on_strategy": False,
                "suggested_question": "¿Hay gastos extraordinarios relevantes?",
            }
        ],
        conversation_state={},
        previous_questions=[],
        last_user_messages=["No se", "Ni idea"],
    )

    assert decision["user_cannot_answer"] is True
    assert decision["progress_state"] == "stalled"
    assert decision["should_ask"] is False


def test_ultimos_mensajes_no_informativos_dan_stalled():
    decision = resolve_followup_decision(
        known_facts={},
        missing_facts=[
            {
                "key": "gastos_extraordinarios",
                "label": "gastos extraordinarios",
                "importance": "medium",
                "impact_on_strategy": False,
                "suggested_question": "¿Hay gastos extraordinarios relevantes?",
            }
        ],
        conversation_state={},
        previous_questions=[],
        last_user_messages=["ya te dije", "lo mismo"],
    )

    assert decision["recent_progress"] is False
    assert decision["progress_state"] == "stalled"
    assert decision["should_ask"] is False


def test_mensaje_reciente_con_dato_util_da_advancing():
    decision = resolve_followup_decision(
        known_facts={},
        missing_facts=[
            {
                "key": "fecha_separacion",
                "label": "la fecha de separacion",
                "importance": "medium",
                "impact_on_strategy": True,
                "suggested_question": "¿Desde cuando estan separados?",
            }
        ],
        conversation_state={},
        previous_questions=[],
        last_user_messages=["Estamos separados desde marzo de 2024."],
    )

    assert decision["recent_progress"] is True
    assert decision["progress_state"] == "advancing"
    assert decision["should_ask"] is True
    assert decision["priority_question"] is not None


def test_loop_sigue_priorizando_blocked():
    decision = resolve_followup_decision(
        known_facts={},
        missing_facts=[
            {
                "key": "ingresos_otro_progenitor",
                "label": "ingresos del otro progenitor",
                "importance": "critical",
                "impact_on_strategy": True,
                "suggested_question": "¿Podes precisar los ingresos del otro progenitor?",
            }
        ],
        conversation_state={},
        previous_questions=[
            "¿Podes precisar los ingresos del otro progenitor?",
            "¿Podes precisar los ingresos del otro progenitor?",
        ],
        last_user_messages=["No se", "No tengo ese dato"],
    )

    assert decision["detected_loop"] is True
    assert decision["progress_state"] == "blocked"
    assert decision["should_ask"] is False


def test_critical_missing_sin_imposibilidad_puede_seguir_preguntando():
    decision = resolve_followup_decision(
        known_facts={},
        missing_facts=[
            {
                "key": "modalidad_divorcio",
                "label": "si el divorcio seria unilateral o de comun acuerdo",
                "importance": "critical",
                "impact_on_strategy": True,
                "suggested_question": "¿El divorcio seria unilateral o de comun acuerdo?",
            }
        ],
        conversation_state={},
        previous_questions=[],
        last_user_messages=["Todavia no lo definimos con claridad."],
    )

    assert decision["user_cannot_answer"] is False
    assert decision["should_ask"] is True
    assert "divorcio" in str(decision["priority_question"]).lower()


def test_prioriza_pregunta_critica_sobre_opcional():
    decision = resolve_followup_decision(
        known_facts={},
        missing_facts=[
            {
                "key": "gastos_extraordinarios",
                "label": "gastos extraordinarios",
                "importance": "medium",
                "impact_on_strategy": False,
                "suggested_question": "¿Hay gastos extraordinarios relevantes?",
            },
            {
                "key": "modalidad_divorcio",
                "label": "si el divorcio seria unilateral o de comun acuerdo",
                "importance": "critical",
                "impact_on_strategy": True,
                "suggested_question": "¿El divorcio seria unilateral o de comun acuerdo?",
            },
        ],
        conversation_state={},
        previous_questions=[],
        last_user_messages=["Estamos viendo como organizarlo."],
    )

    assert decision["should_ask"] is True
    assert "divorcio" in str(decision["priority_question"]).lower()
    assert decision["question_type"] == "critical"


def test_dict_de_retorno_sigue_siendo_compatible_y_expandido():
    decision = resolve_followup_decision(
        known_facts={},
        missing_facts=[
            {
                "key": "jurisdiccion",
                "label": "la jurisdiccion",
                "importance": "critical",
                "impact_on_strategy": True,
            }
        ],
        conversation_state={},
        previous_questions=[],
        last_user_messages=["Vivo en Jujuy."],
    )

    assert "should_ask" in decision
    assert "reason" in decision
    assert "priority_question" in decision
    assert "question_type" in decision
    assert "detected_loop" in decision
    assert "progress_state" in decision
    assert "user_cannot_answer" in decision
    assert "recent_progress" in decision
    assert "stagnation_reason" in decision
