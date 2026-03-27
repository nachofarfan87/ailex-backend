from __future__ import annotations

from app.services.conversational import (
    build_conversation_memory,
    build_primary_question_for_alimentos,
    select_primary_question_for_alimentos,
)


def _payload(
    query: str,
    *,
    facts: dict | None = None,
    clarification_context: dict | None = None,
) -> dict:
    return {
        "query": query,
        "case_domain": "alimentos",
        "facts": facts or {},
        "metadata": {
            "clarification_context": clarification_context or {},
            "session_id": "sess-memory",
        },
    }


def test_memory_marks_support_as_resolved_and_selector_skips_it():
    payload = _payload(
        "No, no me pasa nada hace meses",
        clarification_context={
            "base_query": "Quiero reclamar alimentos por mi hija",
            "last_question": "¿El otro progenitor está aportando algo actualmente?",
            "asked_questions": ["¿El otro progenitor está aportando algo actualmente?"],
            "last_user_answer": "No, no me pasa nada hace meses",
            "known_facts": {},
        },
    )

    memory = build_conversation_memory(payload)
    question = select_primary_question_for_alimentos(
        known_facts=payload["facts"],
        missing_facts=[],
        query_text=payload["query"],
        clarification_context=payload["metadata"]["clarification_context"],
        conversation_memory=memory,
    )

    assert "aportes_actuales" in memory["resolved_slots"]
    assert memory["known_facts"]["aportes_actuales"] is False
    assert memory["canonical_signals"]["incumplimiento_aportes"] is True
    assert question != "¿El otro progenitor está aportando algo actualmente?"


def test_memory_prevents_reasking_convivencia_when_already_resolved():
    payload = _payload(
        "Vive conmigo desde siempre",
        clarification_context={
            "base_query": "Quiero reclamar alimentos",
            "last_question": "¿Tu hija o hijo vive con vos actualmente?",
            "asked_questions": ["¿Tu hija o hijo vive con vos actualmente?"],
            "last_user_answer": "Vive conmigo desde siempre",
            "known_facts": {},
        },
    )

    memory = build_conversation_memory(payload)
    selection = build_primary_question_for_alimentos(
        {
            "known_facts": payload["facts"],
            "missing_facts": [],
            "query_text": payload["query"],
            "clarification_context": payload["metadata"]["clarification_context"],
            "conversation_memory": memory,
        }
    )

    assert "convivencia" in memory["resolved_slots"]
    assert memory["known_facts"]["convivencia"] is True
    assert selection is not None
    assert selection["selected"]["key"] != "convivencia"


def test_memory_activates_location_problem_and_avoids_redundant_location_question():
    payload = _payload(
        "No sé dónde vive y desapareció",
        clarification_context={
            "base_query": "Quiero reclamar alimentos",
            "last_question": "¿Tenés algún domicilio o dato útil para poder ubicar al otro progenitor?",
            "asked_questions": ["¿Tenés algún domicilio o dato útil para poder ubicar al otro progenitor?"],
            "last_user_answer": "No sé dónde vive y desapareció",
            "known_facts": {},
        },
    )

    memory = build_conversation_memory(payload)
    selection = build_primary_question_for_alimentos(
        {
            "known_facts": payload["facts"],
            "missing_facts": [],
            "query_text": payload["query"],
            "clarification_context": payload["metadata"]["clarification_context"],
            "conversation_memory": memory,
        }
    )

    assert memory["canonical_signals"]["problema_ubicacion"] is True
    assert "notificacion" in memory["resolved_slots"]
    assert selection is not None
    assert selection["selected"]["key"] != "notificacion"


def test_without_previous_memory_system_still_builds_valid_state():
    memory = build_conversation_memory(_payload("Quiero reclamar alimentos por mi hija"))

    assert memory["conversation_turns"] >= 1
    assert memory["last_user_message"] == "Quiero reclamar alimentos por mi hija"
    assert memory["canonical_signals"]["intencion_inicio_reclamo"] is True


def test_conversation_memory_is_serializable():
    memory = build_conversation_memory(_payload("Quiero reclamar alimentos"))

    assert isinstance(memory, dict)
    assert isinstance(memory["known_facts"], dict)
    assert isinstance(memory["canonical_signals"], dict)
    assert isinstance(memory["asked_questions"], list)
    assert isinstance(memory["user_answers"], list)


def test_canonical_signals_are_merged_across_turns():
    payload = _payload(
        "No, no me pasa nada hace meses",
        clarification_context={
            "base_query": "Quiero reclamar alimentos",
            "last_question": "¿El otro progenitor está aportando algo actualmente?",
            "last_user_answer": "No, no me pasa nada hace meses",
            "conversation_memory": {
                "canonical_signals": {
                    "intencion_inicio_reclamo": True,
                },
                "asked_questions": ["¿El otro progenitor está aportando algo actualmente?"],
            },
        },
    )

    memory = build_conversation_memory(payload)

    assert memory["canonical_signals"]["intencion_inicio_reclamo"] is True
    assert memory["canonical_signals"]["incumplimiento_aportes"] is True


def test_asked_questions_accumulate_and_keep_penalty_on_next_turn():
    payload = _payload(
        "Quiero seguir con el reclamo",
        clarification_context={
            "base_query": "Quiero reclamar alimentos",
            "asked_questions": ["¿El otro progenitor está aportando algo actualmente?"],
            "conversation_memory": {
                "asked_questions": ["¿Tu hija o hijo vive con vos actualmente?"],
                "canonical_signals": {"intencion_inicio_reclamo": True},
            },
        },
    )

    memory = build_conversation_memory(payload)
    selection = build_primary_question_for_alimentos(
        {
            "known_facts": payload["facts"],
            "missing_facts": [],
            "query_text": payload["query"],
            "clarification_context": payload["metadata"]["clarification_context"],
            "conversation_memory": memory,
        }
    )

    assert "¿El otro progenitor está aportando algo actualmente?" in memory["asked_questions"]
    assert "¿Tu hija o hijo vive con vos actualmente?" in memory["asked_questions"]
    assert selection is not None
    assert selection["selected"]["key"] not in {"aportes_actuales", "convivencia"}
