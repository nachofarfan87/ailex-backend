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
