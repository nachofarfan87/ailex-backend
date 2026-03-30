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
