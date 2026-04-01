# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_progression_policy.py
from __future__ import annotations

from app.services.output_mode_service import apply_output_mode_progression
from app.services.progression_policy import finalize_progression_state, resolve_progression_policy


def _conversation_state(
    *,
    turn_count: int = 2,
    known_facts: list[dict] | None = None,
    missing_facts: list[dict] | None = None,
    asked_questions: list[str] | None = None,
    blocking_missing: bool = False,
    case_completeness: str = "medium",
    progression_state: dict | None = None,
) -> dict:
    return {
        "conversation_id": "conv-progress",
        "turn_count": turn_count,
        "known_facts": known_facts
        or [
            {"key": "hay_hijos", "value": True},
            {"key": "rol_procesal", "value": "madre"},
        ],
        "missing_facts": missing_facts
        or [
            {
                "key": "ingresos_otro_progenitor",
                "label": "ingresos del otro progenitor",
                "priority": "critical",
                "purpose": "quantify",
            }
        ],
        "asked_questions": asked_questions or ["El otro progenitor esta aportando algo actualmente?"],
        "working_domain": "alimentos",
        "progression_state": progression_state
        or {
            "facts_collected": ["hay_hijos", "rol_procesal"],
            "questions_asked": ["El otro progenitor esta aportando algo actualmente?"],
            "topics_covered": ["alimentos"],
            "last_output_mode": "orientacion_inicial",
            "progression_stage": "initial",
            "recent_turns": [
                {
                    "output_mode": "orientacion_inicial",
                    "intent_type": "general_information",
                    "topics_covered": ["alimentos"],
                    "response_fingerprint": "hay base para orientar el reclamo con pasos generales y documentacion basica",
                }
            ],
            "last_intent_type": "general_information",
        },
        "progress_signals": {
            "known_fact_count": 2,
            "missing_fact_count": 1,
            "question_count": 1,
            "blocking_missing": blocking_missing,
            "case_completeness": case_completeness,
        },
    }


def _dialogue_policy(action: str = "ask") -> dict:
    return {
        "action": action,
        "dominant_missing_key": "ingresos_otro_progenitor",
        "dominant_missing_purpose": "quantify",
        "dominant_missing_importance": "core",
    }


def _pipeline_payload() -> dict:
    return {
        "case_profile": {"case_domain": "alimentos"},
        "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
        "case_strategy": {
            "recommended_actions": [
                "Preparar inicio del reclamo.",
                "Ordenar gastos habituales del nino o nina.",
                "Definir si corresponde pedir cuota provisoria.",
            ],
            "procedural_focus": [
                "Precisar ingresos del otro progenitor.",
            ],
        },
        "conversational": {
            "question": "El otro progenitor esta aportando algo actualmente?",
        },
        "output_modes": {
            "user": {
                "title": "Orientacion inicial para alimentos",
                "summary": "Hay base para orientar el reclamo.",
                "what_this_means": "Hay base para orientar el reclamo.",
                "next_steps": ["Preparar inicio del reclamo."],
                "missing_information": ["ingresos del otro progenitor"],
            },
            "professional": {
                "title": "Encuadre estrategico de alimentos",
                "summary": "Encuadre inicial.",
            },
        },
    }


def test_no_repeticion_fuerza_cambio_de_output_mode():
    progression = resolve_progression_policy(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        intent_resolution={"intent_type": "general_information", "urgency": "low"},
        execution_output={"applies": False},
        pipeline_payload=_pipeline_payload(),
        response_text="Hay base para orientar el reclamo con pasos generales y documentacion basica.",
    )

    assert progression["anti_repetition_guard"]["semantic_repetition_detected"] is True
    assert progression["output_mode"] == "estructuracion"
    assert progression["progression_stage"] == "structuring_case"


def test_progression_pasa_a_ejecucion_si_execution_output_aplica():
    progression = resolve_progression_policy(
        conversation_state=_conversation_state(case_completeness="high"),
        dialogue_policy=_dialogue_policy(action="hybrid"),
        conversational_intelligence={"signals": {"ready_to_advance": True}},
        intent_resolution={"intent_type": "action_now", "urgency": "high"},
        execution_output={
            "applies": True,
            "rendered_response_text": "Que podes hacer ahora:\n- Presentar el reclamo.",
            "execution_output": {"followup_question": "El otro progenitor esta aportando algo actualmente?"},
        },
        pipeline_payload=_pipeline_payload(),
        response_text="Texto base.",
    )

    assert progression["output_mode"] == "ejecucion"
    assert progression["progression_stage"] == "execution"


def test_apply_output_mode_progression_actualiza_titulos_y_summary():
    payload = _pipeline_payload()
    progression = resolve_progression_policy(
        conversation_state=_conversation_state(),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        intent_resolution={"intent_type": "general_information", "urgency": "low"},
        execution_output={"applies": False},
        pipeline_payload=payload,
        response_text="Hay base para orientar el reclamo con pasos generales y documentacion basica.",
    )

    evolved = apply_output_mode_progression(payload, progression)

    assert evolved["output_mode"] == "estructuracion"
    assert evolved["output_modes"]["user"]["title"] == "Estructuracion del caso de alimentos"
    assert "ordena el caso" in evolved["output_modes"]["user"]["summary"].lower()


def test_finalize_progression_state_guarda_solo_los_ultimos_dos_turnos():
    progression = resolve_progression_policy(
        conversation_state=_conversation_state(
            progression_state={
                "facts_collected": ["hay_hijos"],
                "questions_asked": [],
                "topics_covered": ["alimentos"],
                "last_output_mode": "orientacion_inicial",
                "progression_stage": "initial",
                "recent_turns": [
                    {"output_mode": "orientacion_inicial", "intent_type": "general_information", "topics_covered": ["alimentos"], "response_fingerprint": "uno"},
                    {"output_mode": "estructuracion", "intent_type": "general_information", "topics_covered": ["alimentos"], "response_fingerprint": "dos"},
                ],
            },
        ),
        dialogue_policy=_dialogue_policy(),
        conversational_intelligence={"signals": {}},
        intent_resolution={"intent_type": "general_information", "urgency": "low"},
        execution_output={"applies": False},
        pipeline_payload=_pipeline_payload(),
        response_text="Hay base para orientar el reclamo con pasos generales y documentacion basica.",
    )

    finalized = finalize_progression_state(
        progression_policy=progression,
        response_text="Respuesta final evolucionada.",
    )

    assert len(finalized["recent_turns"]) == 2
    assert finalized["recent_turns"][-1]["output_mode"] == progression["output_mode"]
