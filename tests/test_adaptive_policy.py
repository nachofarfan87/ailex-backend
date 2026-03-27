from __future__ import annotations

from app.services.conversational import (
    build_adaptive_context,
    build_primary_question_for_alimentos,
    evaluate_conversation_progress,
)


def _memory(
    *,
    resolved_slots: list[str] | None = None,
    pending_slots: list[str] | None = None,
    user_answers: list[dict] | None = None,
    conversation_turns: int = 1,
    canonical_signals: dict | None = None,
) -> dict:
    return {
        "known_facts": {},
        "inferred_facts": {},
        "canonical_signals": canonical_signals or {},
        "asked_questions": [],
        "user_answers": user_answers or [],
        "resolved_slots": resolved_slots or [],
        "pending_slots": pending_slots or ["aportes_actuales", "convivencia", "notificacion"],
        "conversation_turns": conversation_turns,
        "last_user_message": "",
    }


def test_short_ambiguous_answer_increases_friction_and_is_not_productive():
    memory = _memory(
        user_answers=[
            {
                "question": "¿El otro progenitor está aportando algo actualmente?",
                "answer": "Y... no sé",
                "slot": "aportes_actuales",
            }
        ],
        conversation_turns=2,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["friction_level"] in {"medium", "high"}
    assert adaptive["last_question_productive"] is False


def test_short_valid_answer_for_ingresos_is_not_ambiguous_and_is_productive():
    memory = _memory(
        user_answers=[
            {
                "question": "¿Sabés si el otro progenitor tiene ingresos o una actividad laboral identificable?",
                "answer": "Sí, trabaja",
                "slot": "ingresos",
            }
        ],
        conversation_turns=2,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["last_question_productive"] is True
    assert adaptive["friction_level"] == "low"


def test_short_valid_answer_for_aportes_is_not_ambiguous_and_is_productive():
    memory = _memory(
        user_answers=[
            {
                "question": "¿El otro progenitor está aportando algo actualmente?",
                "answer": "No, no me deposita",
                "slot": "aportes_actuales",
            }
        ],
        conversation_turns=2,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["last_question_productive"] is True
    assert adaptive["friction_level"] == "low"


def test_long_but_evasive_answer_is_not_easily_marked_as_productive():
    memory = _memory(
        user_answers=[
            {
                "question": "¿El otro progenitor está aportando algo actualmente?",
                "answer": "Sí, pero la verdad no sé bien cómo es eso",
                "slot": "aportes_actuales",
            }
        ],
        conversation_turns=2,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["last_question_productive"] is False
    assert adaptive["friction_level"] in {"medium", "high"}


def test_clear_answer_is_productive_and_improves_progress():
    memory = _memory(
        resolved_slots=["aportes_actuales"],
        user_answers=[
            {
                "question": "¿El otro progenitor está aportando algo actualmente?",
                "answer": "No, no me pasa nada hace meses",
                "slot": "aportes_actuales",
            }
        ],
        conversation_turns=2,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["last_question_productive"] is True
    assert adaptive["weighted_productive_score"] > 0.9
    assert adaptive["conversation_quality"] in {"medium", "high"}


def test_good_progress_is_detected_with_two_resolved_slots():
    memory = _memory(
        resolved_slots=["aportes_actuales", "convivencia"],
        pending_slots=["notificacion", "ingresos"],
        user_answers=[
            {"question": "¿El otro progenitor está aportando algo actualmente?", "answer": "No, no me pasa nada", "slot": "aportes_actuales"},
            {"question": "¿Tu hija o hijo vive con vos actualmente?", "answer": "Sí, vive conmigo", "slot": "convivencia"},
        ],
        conversation_turns=3,
    )

    assert evaluate_conversation_progress(memory) == "good"
    adaptive = build_adaptive_context(memory)
    assert adaptive["recent_progress"] == "good"
    assert adaptive["conversation_quality"] == "high"


def test_stalled_progress_is_detected_after_three_unproductive_turns():
    memory = _memory(
        user_answers=[
            {"question": "¿El otro progenitor está aportando algo actualmente?", "answer": "No sé", "slot": "aportes_actuales"},
            {"question": "¿Tu hija o hijo vive con vos actualmente?", "answer": "Y... no sé", "slot": "convivencia"},
            {"question": "¿Tenés algún domicilio o dato útil para poder ubicar al otro progenitor?", "answer": "No recuerdo", "slot": "notificacion"},
        ],
        conversation_turns=4,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["recent_progress"] == "stalled"
    assert adaptive["adaptive_signals"]["stalled_conversation"] is True
    assert adaptive["conversation_quality"] == "low"


def test_last_turn_weighs_more_than_older_productive_history():
    memory = _memory(
        resolved_slots=["ingresos", "convivencia"],
        pending_slots=["notificacion", "urgencia"],
        user_answers=[
            {
                "question": "¿Sabés si el otro progenitor tiene ingresos o una actividad laboral identificable?",
                "answer": "Sí, trabaja en blanco",
                "slot": "ingresos",
            },
            {
                "question": "¿Hay alguna necesidad urgente del hijo o hija que convenga plantear desde el inicio?",
                "answer": "Y... no sé",
                "slot": "urgencia",
            },
            {
                "question": "¿Tu hija o hijo vive con vos actualmente?",
                "answer": "Sí, vive conmigo",
                "slot": "convivencia",
            },
        ],
        conversation_turns=4,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["last_question_category"] == "encuadre_familiar"
    assert adaptive["recent_productive_categories"][0] == "encuadre_familiar"
    assert adaptive["weighted_productive_score"] > 1.0


def test_notificacion_signal_is_recognized_from_real_language():
    memory = _memory(
        user_answers=[
            {
                "question": "¿Tenés algún domicilio o dato útil para poder ubicar al otro progenitor?",
                "answer": "No tengo dirección y no sé dónde está",
                "slot": "notificacion",
            }
        ],
        conversation_turns=2,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["last_question_productive"] is True
    assert adaptive["friction_level"] == "low"


def test_conversation_quality_uses_weighted_scores_consistently():
    memory = _memory(
        user_answers=[
            {
                "question": "¿Sabés si el otro progenitor tiene ingresos o una actividad laboral identificable?",
                "answer": "Sí, trabaja",
                "slot": "ingresos",
            },
            {
                "question": "¿El otro progenitor está aportando algo actualmente?",
                "answer": "No, no me deposita",
                "slot": "aportes_actuales",
            },
        ],
        resolved_slots=["ingresos", "aportes_actuales"],
        pending_slots=["convivencia", "notificacion"],
        conversation_turns=3,
    )

    adaptive = build_adaptive_context(memory)

    assert adaptive["weighted_productive_score"] >= 1.5
    assert adaptive["weighted_ambiguous_score"] == 0
    assert adaptive["conversation_quality"] == "high"


def test_adaptive_adjustments_are_serialized_in_question_selection():
    memory = _memory(
        resolved_slots=["aportes_actuales"],
        pending_slots=["notificacion", "ingresos", "urgencia"],
        user_answers=[
            {
                "question": "¿El otro progenitor está aportando algo actualmente?",
                "answer": "No, no me pasa nada hace meses",
                "slot": "aportes_actuales",
            }
        ],
        conversation_turns=2,
        canonical_signals={"incumplimiento_aportes": True, "intencion_inicio_reclamo": True},
    )

    selection = build_primary_question_for_alimentos(
        {
            "query_text": "Quiero reclamar alimentos",
            "known_facts": {},
            "missing_facts": [],
            "clarification_context": {},
            "conversation_memory": memory,
        }
    )

    assert selection is not None
    assert isinstance(selection["adaptive_context"], dict)
    assert selection["adaptive_context"]["last_question_productive"] is True
    assert selection["adaptive_context"]["conversation_quality"] in {"medium", "high"}
    assert "adaptive" in selection["selected"]["score_breakdown"]


def test_selector_still_works_without_adaptive_context():
    selection = build_primary_question_for_alimentos(
        {
            "query_text": "Quiero iniciar una demanda de alimentos por mi hija",
            "known_facts": {},
            "missing_facts": [],
            "clarification_context": {},
        }
    )

    assert selection is not None
    assert selection["selected"]["text"]
