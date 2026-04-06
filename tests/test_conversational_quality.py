"""Tests for the Conversational Quality Layer (Fase 5.5)."""

from __future__ import annotations

from app.services.conversational.conversational_quality import (
    apply_conversational_style,
    build_fact_aware_opening,
    build_contextual_opening,
    simplify_question_text,
)


def test_first_turn_opening_is_introductory():
    memory = {"conversation_turns": 0}
    opening = build_contextual_opening(memory, question_key="aportes_actuales")
    assert "ya tenemos" not in opening.lower()
    assert "ya se" not in opening.lower()
    assert opening.endswith(".")


def test_continuation_turn_opening_differs_from_first():
    first = build_contextual_opening({"conversation_turns": 0}, question_key="convivencia")
    cont = build_contextual_opening({"conversation_turns": 2}, question_key="convivencia")
    assert first != cont


def test_late_turn_opening_has_closing_tone():
    opening = build_contextual_opening({"conversation_turns": 5}, question_key="urgencia")
    late_markers = ("bastante claro", "cerca", "casi", "solo me falta", "un dato mas", "ultimo")
    assert any(marker in opening.lower() for marker in late_markers)


def test_no_consecutive_repeat_for_different_keys():
    memory = {"conversation_turns": 1}
    o1 = build_contextual_opening(memory, question_key="aportes_actuales")
    o2 = build_contextual_opening(memory, question_key="convivencia")
    o3 = build_contextual_opening(memory, question_key="notificacion")
    assert len({o1, o2, o3}) >= 2


def test_anti_repeat_uses_last_opening_idx():
    memory = {"conversation_turns": 0}
    opening_a = build_contextual_opening(memory, question_key="aportes_actuales")

    from app.services.conversational.conversational_quality import _FIRST_TURN_OPENINGS, _pick_index

    idx = _pick_index(_FIRST_TURN_OPENINGS, "aportes_actuales", 0)
    memory["_last_opening_idx"] = idx

    opening_b = build_contextual_opening(memory, question_key="aportes_actuales")
    assert opening_a != opening_b


def test_opening_is_deterministic():
    memory_a = {"conversation_turns": 2}
    memory_b = {"conversation_turns": 2}
    a = build_contextual_opening(memory_a, question_key="ingresos")
    b = build_contextual_opening(memory_b, question_key="ingresos")
    assert a == b


def test_simplify_known_slots():
    assert "plata" in simplify_question_text("ignored", "aportes_actuales").lower()
    assert "vive con vos" in simplify_question_text("ignored", "convivencia").lower()
    assert "ubicar" in simplify_question_text("ignored", "notificacion").lower()
    assert "trabaja" in simplify_question_text("ignored", "ingresos").lower() or "ingreso" in simplify_question_text("ignored", "ingresos").lower()
    assert "urgente" in simplify_question_text("ignored", "urgencia").lower()
    assert "reclamo" in simplify_question_text("ignored", "antecedentes").lower() or "acuerdo" in simplify_question_text("ignored", "antecedentes").lower()
    assert "unilateral" in simplify_question_text("ignored", "divorcio_modalidad").lower()
    assert "hijos" in simplify_question_text("ignored", "hay_hijos").lower()


def test_simplify_unknown_slot_returns_original():
    original = "¿Cual es el estado civil del demandante?"
    assert simplify_question_text(original, "unknown_slot") == original


def test_simplify_no_slot_returns_original():
    original = "¿Tiene bienes gananciales?"
    assert simplify_question_text(original, "") == original
    assert simplify_question_text(original) == original


def test_simplified_questions_are_shorter():
    formal = "¿Sabes si el otro progenitor tiene ingresos o una actividad laboral identificable?"
    simple = simplify_question_text(formal, "ingresos")
    assert len(simple) < len(formal)


def test_apply_style_includes_opening_and_question():
    result = apply_conversational_style(
        "¿El otro progenitor esta aportando algo actualmente?",
        {"conversation_turns": 0},
        slot_key="aportes_actuales",
    )
    assert "plata" in result.lower()
    assert "¿" in result
    assert result.count("¿") == 1


def test_apply_style_without_opening():
    result = apply_conversational_style(
        "¿El otro progenitor esta aportando algo actualmente?",
        {"conversation_turns": 0},
        slot_key="aportes_actuales",
        include_opening=False,
    )
    assert result == simplify_question_text("ignored", "aportes_actuales")


def test_apply_style_no_memory_still_works():
    result = apply_conversational_style(
        "¿Ya hubo algun reclamo?",
        None,
        slot_key="antecedentes",
    )
    assert "¿" in result
    assert len(result) > 10


def test_build_contextual_opening_persists_idx_in_memory():
    memory = {"conversation_turns": 0}
    assert "_last_opening_idx" not in memory
    build_contextual_opening(memory, question_key="convivencia")
    assert "_last_opening_idx" in memory
    assert isinstance(memory["_last_opening_idx"], int)


def test_persisted_idx_prevents_repeat_on_same_key_next_turn():
    memory = {"conversation_turns": 2}
    opening_turn1 = build_contextual_opening(memory, question_key="ingresos")
    assert "_last_opening_idx" in memory

    memory["conversation_turns"] = 3
    opening_turn2 = build_contextual_opening(memory, question_key="ingresos")
    assert opening_turn1 != opening_turn2


def test_persisted_idx_survives_merge_conversation_memory():
    from app.services.conversational.memory_service import merge_conversation_memory

    previous = {"conversation_turns": 1, "_last_opening_idx": 3}
    incoming = {"conversation_turns": 2}
    merged = merge_conversation_memory(previous, incoming)
    assert merged["_last_opening_idx"] == 3


def test_merge_conversation_memory_incoming_overrides_previous_idx():
    from app.services.conversational.memory_service import merge_conversation_memory

    previous = {"_last_opening_idx": 1}
    incoming = {"_last_opening_idx": 4}
    merged = merge_conversation_memory(previous, incoming)
    assert merged["_last_opening_idx"] == 4


def test_full_multi_turn_anti_repetition():
    memory = {"conversation_turns": 0}
    openings: list[str] = []

    keys = ["aportes_actuales", "convivencia", "ingresos", "notificacion"]
    for turn, key in enumerate(keys):
        memory["conversation_turns"] = turn
        openings.append(build_contextual_opening(memory, question_key=key))

    for index in range(1, len(openings)):
        assert openings[index] != openings[index - 1]


def test_none_memory_does_not_crash_and_does_not_persist():
    opening = build_contextual_opening(None, question_key="urgencia")
    assert isinstance(opening, str)
    assert len(opening) > 0


def test_existing_response_structure_preserved():
    opening = build_contextual_opening({"conversation_turns": 1}, "convivencia")
    assert isinstance(opening, str)

    simplified = simplify_question_text("anything", "convivencia")
    assert isinstance(simplified, str)

    styled = apply_conversational_style("anything", {}, slot_key="convivencia")
    assert isinstance(styled, str)


def test_fact_aware_opening_divorcio_alimentos_hijos():
    opening = build_fact_aware_opening(
        {
            "tema_divorcio": "inferred",
            "tema_alimentos": "inferred",
            "hay_hijos": True,
        }
    )

    lowered = opening.lower()
    assert "divorcio" in lowered
    assert "alimentos" in lowered
    assert "hijos" in lowered


def test_fact_aware_opening_divorcio_hijos_sin_alimentos():
    opening = build_fact_aware_opening(
        {
            "tema_divorcio": True,
            "hay_hijos": "si",
            "tema_alimentos": False,
        }
    )

    lowered = opening.lower()
    assert "divorcio" in lowered
    assert "hijos" in lowered
    assert "alimentos" not in lowered


def test_fact_aware_opening_alimentos_hijos():
    opening = build_fact_aware_opening(
        {
            "tema_alimentos": "inferred",
            "hay_hijos": "true",
        }
    )

    lowered = opening.lower()
    assert "alimentos" in lowered
    assert "hijos" in lowered


def test_fact_aware_opening_sin_facts_devuelve_vacio():
    assert build_fact_aware_opening({}) == ""
    assert build_fact_aware_opening(None) == ""
