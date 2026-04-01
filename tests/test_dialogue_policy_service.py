# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_dialogue_policy_service.py
from __future__ import annotations

from app.services.dialogue_policy_service import resolve_dialogue_policy


def _state(
    *,
    turn_count: int = 1,
    asked_questions: list[str] | None = None,
    missing_facts: list[dict] | None = None,
    case_completeness: str = "low",
    blocking_missing: bool = False,
    repeated_question_risk: str = "low",
) -> dict:
    return {
        "conversation_id": "conv-policy",
        "turn_count": turn_count,
        "known_facts": [],
        "missing_facts": missing_facts or [],
        "asked_questions": asked_questions or [],
        "working_case_type": "alimentos_hijos",
        "working_domain": "alimentos",
        "current_stage": "clarification",
        "progress_signals": {
            "known_fact_count": 0,
            "missing_fact_count": len(missing_facts or []),
            "question_count": len(asked_questions or []),
            "repeated_question_risk": repeated_question_risk,
            "turn_count": turn_count,
            "blocking_missing": blocking_missing,
            "case_completeness": case_completeness,
        },
    }


def test_dominant_override_prioriza_core_identify_en_top_n():
    policy = resolve_dialogue_policy(
        conversation_state=_state(
            case_completeness="low",
            blocking_missing=True,
            missing_facts=[
                {"key": "ingresos_otro_progenitor", "label": "ingresos del otro progenitor", "priority": "critical", "purpose": "quantify"},
                {"key": "rol_procesal", "label": "rol procesal", "priority": "ordinary", "purpose": "identify"},
            ],
        )
    )

    assert policy["dominant_missing_key"] == "rol_procesal"
    assert policy["dominant_missing_purpose"] == "identify"
    assert policy["action"] == "ask"


def test_blocking_missing_override_fuerza_ask():
    policy = resolve_dialogue_policy(
        conversation_state=_state(
            case_completeness="medium",
            blocking_missing=True,
            missing_facts=[
                {"key": "convivencia", "label": "convivencia", "priority": "ordinary", "purpose": "enable"},
            ],
        )
    )

    assert policy["dominant_missing_key"] == "convivencia"
    assert policy["action"] == "ask"
    assert policy["confidence"] == "high"


def test_guidance_strength_afecta_flags():
    low_policy = resolve_dialogue_policy(
        conversation_state=_state(
            case_completeness="medium",
            blocking_missing=True,
            missing_facts=[
                {"key": "convivencia", "label": "convivencia", "priority": "ordinary", "purpose": "enable"},
            ],
        )
    )
    high_policy = resolve_dialogue_policy(
        conversation_state=_state(
            case_completeness="high",
            missing_facts=[
                {"key": "comprobantes_pago", "label": "comprobantes de pago", "priority": "ordinary", "purpose": "prove"},
            ],
        )
    )

    assert low_policy["guidance_strength"] == "low"
    assert low_policy["should_ask_first"] is True
    assert high_policy["guidance_strength"] == "high"
    assert high_policy["should_offer_partial_guidance"] is True


def test_repeated_missing_key_mayor_o_igual_a_dos_genera_loop_high():
    policy = resolve_dialogue_policy(
        conversation_state=_state(
            turn_count=4,
            asked_questions=[
                "Cual es la convivencia actual?",
                "Podes indicar la convivencia del nino?",
                "Tenes datos de convivencia?",
            ],
            case_completeness="low",
            blocking_missing=True,
            missing_facts=[
                {"key": "convivencia", "label": "convivencia actual del nino", "priority": "critical", "purpose": "enable"},
                {"key": "ingresos_otro_progenitor", "label": "ingresos del otro progenitor", "priority": "ordinary", "purpose": "quantify"},
            ],
        )
    )

    assert policy["loop_risk"] == "high"
    assert policy["priority_missing_keys"] == ["ingresos_otro_progenitor"]


def test_hybrid_low_se_comporta_cerca_de_ask():
    policy = resolve_dialogue_policy(
        conversation_state=_state(
            case_completeness="low",
            turn_count=5,
            asked_questions=[
                "Cual es la convivencia actual?",
                "Podes indicar la convivencia?",
                "Tenes datos de convivencia?",
            ],
            blocking_missing=True,
            repeated_question_risk="high",
            missing_facts=[
                {"key": "convivencia", "label": "convivencia", "priority": "critical", "purpose": "enable"},
            ],
        )
    )

    assert policy["action"] == "hybrid"
    assert policy["guidance_strength"] == "medium"
    assert policy["should_ask_first"] is False
    assert policy["should_offer_partial_guidance"] is True


def test_hybrid_medium_mantiene_balance_y_quantify():
    policy = resolve_dialogue_policy(
        conversation_state=_state(
            case_completeness="medium",
            missing_facts=[
                {"key": "ingresos_otro_progenitor", "label": "ingresos del otro progenitor", "priority": "ordinary", "purpose": "quantify"},
            ],
        )
    )

    assert policy["action"] == "hybrid"
    assert policy["guidance_strength"] == "medium"
    assert policy["should_ask_first"] is False
    assert policy["should_offer_partial_guidance"] is True


def test_hybrid_high_se_comporta_cerca_de_advise():
    policy = resolve_dialogue_policy(
        conversation_state=_state(
            case_completeness="high",
            missing_facts=[
                {"key": "comprobantes_pago", "label": "comprobantes de pago", "priority": "ordinary", "purpose": "prove"},
            ],
        )
    )

    assert policy["action"] in {"hybrid", "advise"}
    if policy["action"] == "hybrid":
        assert policy["guidance_strength"] == "high"
        assert policy["should_offer_partial_guidance"] is True


def test_confidence_baja_en_conflicto_con_blocking_missing():
    policy = resolve_dialogue_policy(
        conversation_state=_state(
            case_completeness="low",
            turn_count=5,
            asked_questions=[
                "Cual es la convivencia actual?",
                "Podes indicar la convivencia del nino?",
                "Tenes datos de convivencia?",
            ],
            blocking_missing=True,
            repeated_question_risk="high",
            missing_facts=[
                {"key": "convivencia", "label": "convivencia", "priority": "critical", "purpose": "enable"},
            ],
        )
    )

    assert policy["action"] == "hybrid"
    assert policy["confidence"] == "low"
