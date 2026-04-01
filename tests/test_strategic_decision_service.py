# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_strategic_decision_service.py
from __future__ import annotations

from app.services.strategic_decision_service import resolve_strategic_decision


def _conversation_state(*, known_facts: list[dict] | None = None) -> dict:
    return {
        "conversation_id": "conv-strategic",
        "known_facts": known_facts or [],
    }


def test_divorcio_con_hija_menor_y_sin_acuerdo_prioriza_unilateral_y_alimentos():
    result = resolve_strategic_decision(
        conversation_state=_conversation_state(
            known_facts=[
                {"key": "hay_hijos", "value": True},
                {"key": "edad_hija", "value": 0},
                {"key": "hay_acuerdo", "value": False},
            ]
        ),
        pipeline_payload={
            "query": "Quiero divorciarme y pedir alimentos para mi hija de 3 meses",
            "facts": {"hay_hijos": True, "hay_acuerdo": False},
            "classification": {"action_slug": "divorcio_unilateral", "case_domain": "divorcio"},
            "case_profile": {"case_domain": "divorcio"},
        },
        progression_policy={"topics_covered": ["divorcio", "alimentos"]},
    )

    assert "divorcio unilateral" in result["recommended_path"].lower()
    assert "alimentos provisorios" in result["recommended_path"].lower()
    assert result["priority_action"]
    assert result["justification"]


def test_alimentos_sin_aporte_actual_prioriza_cuota_provisoria():
    result = resolve_strategic_decision(
        conversation_state=_conversation_state(
            known_facts=[
                {"key": "hay_hijos", "value": True},
                {"key": "aporte_actual", "value": False},
            ]
        ),
        pipeline_payload={
            "query": "No me pasa alimentos para mi hija",
            "facts": {"hay_hijos": True, "aporte_actual": False},
            "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
            "case_profile": {"case_domain": "alimentos"},
        },
        progression_policy={"topics_covered": ["alimentos"]},
    )

    assert "cuota provisoria" in result["recommended_path"].lower()
    assert "menos conveniente" not in result["justification"].lower()


def test_si_hay_acuerdo_claro_en_divorcio_prioriza_comun_acuerdo():
    result = resolve_strategic_decision(
        conversation_state=_conversation_state(
            known_facts=[
                {"key": "divorcio_modalidad", "value": "comun_acuerdo"},
                {"key": "hay_hijos", "value": True},
            ]
        ),
        pipeline_payload={
            "query": "Queremos divorciarnos de comun acuerdo",
            "facts": {"divorcio_modalidad": "comun_acuerdo"},
            "classification": {"action_slug": "divorcio", "case_domain": "divorcio"},
            "case_profile": {"case_domain": "divorcio"},
        },
        progression_policy={"topics_covered": ["divorcio"]},
    )

    assert "comun acuerdo" in result["recommended_path"].lower()
    assert result["alternative_path"]
