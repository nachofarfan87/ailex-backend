from __future__ import annotations

from app.services.conversational_interpretation_service import interpret_clarification_answer


def test_current_turn_can_correct_previous_structural_fact_without_leaving_old_value():
    result = interpret_clarification_answer(
        answer="Tengo una hija de 3 meses y quiero que se quede conmigo.",
        last_question="Existen hijos menores o con capacidad restringida que haya que contemplar?",
        known_facts={"hay_hijos": False},
        extracted_facts={"hay_hijos": True, "hay_hijos_edad": "informada"},
        asked_questions=["Existen hijos menores o con capacidad restringida que haya que contemplar?"],
    )

    assert result["facts"]["hay_hijos"] is True
    assert result["facts"]["hay_hijos_edad"] == "informada"
    assert result["response_quality"] != "contradictory"


def test_reformulated_question_is_human_short_and_question_shaped():
    result = interpret_clarification_answer(
        answer="No se",
        last_question="Existen hijos menores o con capacidad restringida que haya que contemplar...",
        known_facts={},
        asked_questions=["Existen hijos menores o con capacidad restringida que haya que contemplar..."],
    )

    assert result["precision_required"] is True
    assert result["reformulated_question"].endswith("?")
    assert "por ejemplo" not in result["reformulated_question"].lower()
    assert "eso me ayuda" not in result["reformulated_question"].lower()
    assert "hijos" in result["reformulated_question"].lower()
