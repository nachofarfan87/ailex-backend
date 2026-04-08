# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_response_composition_service.py
from __future__ import annotations

from app.services.response_composition_service import resolve_response_composition


def test_render_structuring_response_from_service():
    result = resolve_response_composition(
        output_mode="estructuracion",
        smart_strategy={"strategy_mode": "orient_with_prudence"},
        strategy_composition_profile={"allow_followup": False},
        strategy_language_profile={"selected_opening": "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor."},
        conversation_state={
            "known_facts": [{"key": "hay_hijos", "value": True}],
            "missing_facts": [{"label": "ingresos del otro progenitor", "priority": "high", "purpose": "enable"}],
        },
        dialogue_policy={},
        execution_output={},
        progression_policy={"missing_focus": ["ingresos del otro progenitor"]},
        pipeline_payload={},
        api_payload={},
        followup_question="",
    )

    assert "el caso ya se puede ordenar mejor" in result["rendered_response_text"].lower()
    assert "ingresos del otro progenitor" in result["rendered_response_text"].lower()


def test_render_strategy_response_keeps_clarify_critical_brief():
    result = resolve_response_composition(
        output_mode="estrategia",
        smart_strategy={"strategy_mode": "clarify_critical"},
        strategy_composition_profile={"allow_followup": True},
        strategy_language_profile={
            "selected_opening": "Hay un punto que define esto ahora.",
            "selected_followup_intro": "Necesito confirmar solo esto:",
        },
        conversation_state={},
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={
            "case_strategy": {
                "recommended_actions": ["Iniciar divorcio unilateral."],
                "risk_analysis": ["La via alternativa deja mas frentes abiertos."],
            }
        },
        api_payload={},
        followup_question="¿El divorcio seria unilateral o de comun acuerdo?",
    )

    assert result["rendered_response_text"].count("?") == 1
    assert len(result["rendered_response_text"]) < 400


def test_render_execution_response_keeps_action_first_steps_first():
    result = resolve_response_composition(
        output_mode="ejecucion",
        smart_strategy={"strategy_mode": "action_first"},
        strategy_composition_profile={"allow_followup": False},
        strategy_language_profile={"selected_bridge": "Para avanzar de forma concreta, podes hacer esto:"},
        conversation_state={},
        dialogue_policy={},
        execution_output={
            "execution_output": {
                "what_to_do_now": ["Presentar escrito.", "Reunir documentacion."],
                "where_to_go": ["Juzgado competente."],
                "documents_needed": ["Partida de nacimiento."],
            }
        },
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="",
    )

    assert result["rendered_response_text"].startswith("Para avanzar de forma concreta, podes hacer esto:")
    assert "1. Presentar escrito." in result["rendered_response_text"]
    assert "Donde ir:" in result["rendered_response_text"]


def test_composition_metadata_has_expected_keys():
    result = resolve_response_composition(
        output_mode="estructuracion",
        smart_strategy={"strategy_mode": "orient_with_prudence"},
        strategy_composition_profile={},
        strategy_language_profile={},
        conversation_state={},
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="",
    )
    metadata = result["composition_metadata"]
    for key in ("output_mode", "strategy_mode", "section_count", "render_family",
                "expects_followup", "closing_applied", "allow_postprocessor_closing"):
        assert key in metadata, f"Falta clave '{key}' en composition_metadata"


def test_fallback_output_mode_returns_valid_metadata():
    result = resolve_response_composition(
        output_mode="orientacion_inicial",
        smart_strategy={"strategy_mode": "orient_with_prudence"},
        strategy_composition_profile={},
        strategy_language_profile={},
        conversation_state={},
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={},
        api_payload={"response_text": "Una respuesta de fallback."},
        followup_question="",
    )
    metadata = result["composition_metadata"]
    assert metadata["render_family"] == "fallback"
    assert metadata["allow_postprocessor_closing"] is True
    assert result["rendered_response_text"] == "Una respuesta de fallback."
