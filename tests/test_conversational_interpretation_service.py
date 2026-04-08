from __future__ import annotations

from app.services.conversational_interpretation_service import interpret_clarification_answer


def test_si_se_interpreta_como_short_valid_y_permite_avanzar():
    result = interpret_clarification_answer(
        answer="Si",
        last_question="¿El otro padre o madre le pasa algo de plata actualmente?",
        known_facts={},
        asked_questions=["¿El otro padre o madre le pasa algo de plata actualmente?"],
    )

    assert result["response_quality"] == "short_valid"
    assert result["response_strategy"] == "advance"
    assert result["answer_status"] == "precise"
    assert result["facts"]["aportes_actuales"] is True


def test_no_se_dispara_repregunta_util():
    result = interpret_clarification_answer(
        answer="No se",
        last_question="¿El otro padre o madre le pasa algo de plata actualmente?",
        known_facts={},
        asked_questions=["¿El otro padre o madre le pasa algo de plata actualmente?"],
    )

    assert result["response_quality"] == "ambiguous"
    assert result["response_strategy"] == "clarify"
    assert result["precision_required"] is True
    assert result["limit_explanation"]


def test_respuesta_ambigua_no_avanza_a_ciegas():
    result = interpret_clarification_answer(
        answer="Creo que si",
        last_question="¿El otro padre o madre le pasa algo de plata actualmente?",
        known_facts={},
        asked_questions=["¿El otro padre o madre le pasa algo de plata actualmente?"],
    )

    assert result["response_quality"] == "ambiguous"
    assert result["response_strategy"] in {"clarify", "advance_with_prudence"}
    assert result["answer_status"] != "precise"


def test_si_pero_no_siempre_prioriza_ambiguous_sobre_short_valid():
    result = interpret_clarification_answer(
        answer="Si, pero no siempre",
        last_question="Â¿El otro padre o madre le pasa algo de plata actualmente?",
        known_facts={},
        asked_questions=["Â¿El otro padre o madre le pasa algo de plata actualmente?"],
    )

    assert result["response_quality"] == "ambiguous"
    assert result["answer_status"] == "ambiguous"


def test_respuesta_insuficiente_reformula_mejor_la_pregunta():
    result = interpret_clarification_answer(
        answer="Puede ser",
        last_question="¿Tenés algún dato sobre los ingresos actuales del otro progenitor?",
        known_facts={},
        asked_questions=["¿Tenés algún dato sobre los ingresos actuales del otro progenitor?"],
    )

    assert result["response_quality"] in {"ambiguous", "insufficient"}
    assert result["response_strategy"] in {"clarify", "reformulate_question"}
    if result["response_strategy"] == "reformulate_question":
        assert result["reformulated_question"]


def test_detecta_contradiccion_contra_hecho_previsto():
    result = interpret_clarification_answer(
        answer="No",
        last_question="¿El otro padre o madre le pasa algo de plata actualmente?",
        known_facts={"aportes_actuales": True},
        asked_questions=["¿El otro padre o madre le pasa algo de plata actualmente?"],
    )

    assert result["response_quality"] == "contradictory"
    assert result["response_strategy"] == "clarify"
    assert result["answer_status"] == "contradictory"


def test_no_loop_si_el_slot_ya_fue_preguntado_varias_veces():
    result = interpret_clarification_answer(
        answer="No se",
        last_question="¿El otro padre o madre le pasa algo de plata actualmente?",
        known_facts={},
        asked_questions=[
            "¿El otro padre o madre le pasa algo de plata actualmente?",
            "¿El otro progenitor está aportando algo actualmente?",
        ],
    )

    assert result["detected_loop"] is True
