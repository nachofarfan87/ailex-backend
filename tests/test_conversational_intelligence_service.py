# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_conversational_intelligence_service.py
from __future__ import annotations

from app.services.conversational_intelligence_service import (
    apply_conversational_intelligence_to_policy,
    resolve_conversational_intelligence,
)


def _state(
    *,
    turn_count: int = 1,
    case_completeness: str = "low",
    blocking_missing: bool = False,
    question_count: int = 0,
    conversation_memory: dict | None = None,
) -> dict:
    return {
        "conversation_id": "conv-intel",
        "turn_count": turn_count,
        "asked_questions": [],
        "conversation_memory": conversation_memory or {},
        "progress_signals": {
            "case_completeness": case_completeness,
            "blocking_missing": blocking_missing,
            "question_count": question_count,
        },
    }


def _policy(
    *,
    action: str = "ask",
    policy_stage: str = "clarify",
    guidance_strength: str = "low",
    loop_risk: str = "low",
    max_questions: int = 1,
    dominant_missing_key: str = "convivencia",
    dominant_missing_purpose: str = "enable",
    dominant_missing_importance: str = "core",
    blocking_missing: bool = False,
) -> dict:
    return {
        "action": action,
        "policy_stage": policy_stage,
        "guidance_strength": guidance_strength,
        "loop_risk": loop_risk,
        "max_questions": max_questions,
        "dominant_missing_key": dominant_missing_key,
        "dominant_missing_purpose": dominant_missing_purpose,
        "dominant_missing_importance": dominant_missing_importance,
        "blocking_missing": blocking_missing,
        "should_ask_first": action == "ask",
        "should_offer_partial_guidance": action in {"hybrid", "advise"},
    }


def _normalized_input(query: str) -> dict:
    return {
        "query": query,
        "metadata": {"conversation_id": "conv-intel"},
    }


def test_conversacion_estancada_resuelve_status_stalled():
    state = _state(
        turn_count=5,
        case_completeness="low",
        question_count=4,
        conversation_memory={
            "asked_missing_keys_history": ["convivencia", "convivencia"],
            "last_dominant_missing_key": "convivencia",
            "last_dialogue_action": "ask",
        },
    )
    policy = _policy(loop_risk="high")

    intelligence = resolve_conversational_intelligence(
        conversation_state=state,
        dialogue_policy=policy,
        conversation_memory=state["conversation_memory"],
        normalized_input=_normalized_input("No se"),
    )

    assert intelligence["conversation_status"] == "stalled"
    assert intelligence["signals"]["stalled_conversation"] is True


def test_demasiada_clarificacion_detecta_high_clarification_load():
    state = _state(
        turn_count=4,
        case_completeness="low",
        question_count=3,
        conversation_memory={"last_dialogue_action": "ask", "last_turn_type": "clarification"},
    )
    policy = _policy(action="ask", guidance_strength="low", policy_stage="clarify")

    intelligence = resolve_conversational_intelligence(
        conversation_state=state,
        dialogue_policy=policy,
        conversation_memory=state["conversation_memory"],
        normalized_input=_normalized_input("Si"),
    )

    assert intelligence["signals"]["high_clarification_load"] is True


def test_low_user_cooperation_no_se_activa_por_mensaje_corto_aislado_temprano():
    state = _state(
        turn_count=2,
        case_completeness="low",
        conversation_memory={"last_dialogue_action": "ask", "last_user_message": "Quiero saber"},
    )
    policy = _policy(action="ask")

    intelligence = resolve_conversational_intelligence(
        conversation_state=state,
        dialogue_policy=policy,
        conversation_memory=state["conversation_memory"],
        normalized_input=_normalized_input("Si"),
    )

    assert intelligence["signals"]["low_user_cooperation"] is False


def test_low_user_cooperation_si_se_activa_con_respuestas_vagas_repetidas():
    state = _state(
        turn_count=4,
        case_completeness="low",
        conversation_memory={
            "last_dialogue_action": "ask",
            "last_user_message": "No se",
        },
    )
    policy = _policy(action="ask")

    intelligence = resolve_conversational_intelligence(
        conversation_state=state,
        dialogue_policy=policy,
        conversation_memory=state["conversation_memory"],
        normalized_input=_normalized_input("No se"),
    )

    assert intelligence["signals"]["low_user_cooperation"] is True


def test_ready_to_advance_no_se_activa_si_hay_missing_core_bloqueante():
    state = _state(
        turn_count=4,
        case_completeness="high",
        blocking_missing=True,
        question_count=1,
        conversation_memory={"last_dialogue_action": "ask"},
    )
    policy = _policy(
        action="ask",
        policy_stage="clarify",
        guidance_strength="medium",
        dominant_missing_key="convivencia",
        dominant_missing_purpose="enable",
        dominant_missing_importance="core",
        blocking_missing=True,
    )

    intelligence = resolve_conversational_intelligence(
        conversation_state=state,
        dialogue_policy=policy,
        conversation_memory=state["conversation_memory"],
        normalized_input=_normalized_input("Perfecto"),
    )

    assert intelligence["signals"]["ready_to_advance"] is False


def test_conversation_pressure_score_se_calcula_correctamente():
    state = _state(
        turn_count=5,
        case_completeness="low",
        question_count=4,
        conversation_memory={
            "asked_missing_keys_history": ["convivencia", "convivencia"],
            "last_dominant_missing_key": "convivencia",
            "last_dialogue_action": "ask",
            "last_user_message": "No se",
        },
    )
    policy = _policy(loop_risk="high")

    intelligence = resolve_conversational_intelligence(
        conversation_state=state,
        dialogue_policy=policy,
        conversation_memory=state["conversation_memory"],
        normalized_input=_normalized_input("No se"),
    )

    assert intelligence["signals"]["stalled_conversation"] is True
    assert intelligence["signals"]["high_clarification_load"] is True
    assert intelligence["signals"]["low_user_cooperation"] is True
    assert intelligence["conversational_pressure_score"] == 5


def test_recommended_adjustment_advance_with_guidance_cuando_corresponde():
    state = _state(
        turn_count=4,
        case_completeness="high",
        blocking_missing=False,
        question_count=1,
        conversation_memory={"last_dialogue_action": "hybrid", "last_user_message": "Aporte todos los datos"},
    )
    policy = _policy(
        action="hybrid",
        policy_stage="guide",
        guidance_strength="high",
        dominant_missing_key="",
        dominant_missing_purpose="",
        dominant_missing_importance="relevant",
    )

    intelligence = resolve_conversational_intelligence(
        conversation_state=state,
        dialogue_policy=policy,
        conversation_memory=state["conversation_memory"],
        normalized_input=_normalized_input("Sí, ya te di lo principal."),
    )

    assert intelligence["recommended_adjustment"] == "advance_with_guidance"


def test_reduce_questions_reduce_friccion_pero_mantiene_prudencia_juridica():
    policy = _policy(
        action="ask",
        guidance_strength="low",
        max_questions=2,
        dominant_missing_purpose="enable",
        dominant_missing_importance="core",
        blocking_missing=True,
    )
    intelligence = {
        "recommended_adjustment": "reduce_questions",
        "signals": {"stalled_conversation": True},
    }

    adjusted = apply_conversational_intelligence_to_policy(
        dialogue_policy=policy,
        conversational_intelligence=intelligence,
    )

    assert adjusted["action"] == "ask"
    assert adjusted["max_questions"] == 1
    assert adjusted["should_ask_first"] is True


def test_blocking_missing_no_convierte_ask_en_advise():
    policy = _policy(
        action="ask",
        guidance_strength="medium",
        dominant_missing_purpose="quantify",
        dominant_missing_importance="core",
        blocking_missing=True,
    )
    intelligence = {
        "recommended_adjustment": "advance_with_guidance",
        "signals": {"ready_to_advance": True},
    }

    adjusted = apply_conversational_intelligence_to_policy(
        dialogue_policy=policy,
        conversational_intelligence=intelligence,
    )

    assert adjusted["action"] == "ask"


def test_missing_core_identify_enable_no_elimina_pregunta():
    policy = _policy(
        action="ask",
        guidance_strength="medium",
        dominant_missing_key="rol_procesal",
        dominant_missing_purpose="identify",
        dominant_missing_importance="core",
    )
    intelligence = {
        "recommended_adjustment": "reduce_questions",
        "signals": {"high_clarification_load": True},
    }

    adjusted = apply_conversational_intelligence_to_policy(
        dialogue_policy=policy,
        conversational_intelligence=intelligence,
    )

    assert adjusted["action"] == "ask"
    assert adjusted["should_ask_first"] is True
    assert adjusted["max_questions"] == 1


def test_snapshot_viejo_sin_conversation_memory_sigue_compatible():
    state = {
        "conversation_id": "conv-legacy",
        "turn_count": 1,
        "progress_signals": {"case_completeness": "low", "blocking_missing": False, "question_count": 0},
    }
    policy = _policy()

    intelligence = resolve_conversational_intelligence(
        conversation_state=state,
        dialogue_policy=policy,
        conversation_memory=None,
        normalized_input=_normalized_input("Quiero saber como seguir."),
    )

    assert intelligence["conversation_status"] in {"stable", "fragile"}
    assert isinstance(intelligence["signals"], dict)
