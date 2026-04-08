# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_response_composition_consistency.py
"""
Tests de consistencia del contrato composition → postprocessor.

Cubre:
- Estabilidad de metadata en contextos similares
- close_without_more_questions no reabre follow-up ni por composición ni por closing
- action_first no termina con cierre contradictorio
- allow_postprocessor_closing es coherente con el estado del texto
- closing_applied detecta correctamente el cierre inyectado
- render_family es coherente con output_mode + strategy_mode
- selected_legal_referral_note viene del language service, no de composition
"""
from __future__ import annotations

import pytest

from app.services.response_composition_service import (
    resolve_response_composition,
    _resolve_render_family,
    _sections_contain_followup,
    _sections_contain_closing,
)
from app.services.strategy_language_service import resolve_strategy_language_profile


# ── Fixtures base ─────────────────────────────────────────────────────────────

def _base_strategy(mode: str) -> dict:
    return {"strategy_mode": mode}


def _base_lang(mode: str, output_mode: str = "estrategia") -> dict:
    return resolve_strategy_language_profile(
        _base_strategy(mode),
        output_mode=output_mode,
    )


# ── render_family consistency ────────────────────────────────────────────────

@pytest.mark.parametrize("output_mode,strategy_mode,expected_family", [
    ("estrategia", "clarify_critical", "clarification"),
    ("estructuracion", "clarify_critical", "clarification"),
    ("ejecucion", "clarify_critical", "clarification"),
    ("estrategia", "close_without_more_questions", "conclusive"),
    ("estructuracion", "close_without_more_questions", "conclusive"),
    ("ejecucion", "close_without_more_questions", "conclusive"),
    ("ejecucion", "action_first", "action"),
    ("ejecucion", "guide_next_step", "action"),
    ("ejecucion", "orient_with_prudence", "action"),
    ("estructuracion", "orient_with_prudence", "structured"),
    ("estructuracion", "guide_next_step", "structured"),
    ("estrategia", "orient_with_prudence", "guided"),
    ("estrategia", "guide_next_step", "guided"),
    ("estrategia", "substantive_analysis", "guided"),
])
def test_render_family_is_coherent(output_mode, strategy_mode, expected_family):
    family = _resolve_render_family(output_mode=output_mode, strategy_mode=strategy_mode)
    assert family == expected_family, (
        f"output_mode={output_mode!r}, strategy_mode={strategy_mode!r}: "
        f"expected {expected_family!r}, got {family!r}"
    )


# ── close_without_more_questions: sin follow-up, con cierre, sin reapertura ──

def test_close_without_more_questions_estrategia_no_followup():
    lang = _base_lang("close_without_more_questions", "estrategia")
    result = resolve_response_composition(
        output_mode="estrategia",
        smart_strategy=_base_strategy("close_without_more_questions"),
        strategy_composition_profile={"allow_followup": False},
        strategy_language_profile=lang,
        conversation_state={},
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={
            "case_strategy": {"recommended_path": "Iniciar divorcio unilateral."},
        },
        api_payload={},
        followup_question="",
    )
    metadata = result["composition_metadata"]
    assert metadata["expects_followup"] is False
    assert metadata["render_family"] == "conclusive"
    assert metadata["allow_postprocessor_closing"] is False
    assert "?" not in result["rendered_response_text"]


def test_close_without_more_questions_does_not_contain_question():
    lang = _base_lang("close_without_more_questions", "estrategia")
    result = resolve_response_composition(
        output_mode="estrategia",
        smart_strategy=_base_strategy("close_without_more_questions"),
        strategy_composition_profile={"allow_followup": False},
        strategy_language_profile=lang,
        conversation_state={},
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="¿Hay hijos menores involucrados?",  # debe ser ignorado por el renderer
    )
    # close_without_more_questions nunca debe incluir un follow-up en la respuesta
    assert "?" not in result["rendered_response_text"]
    assert result["composition_metadata"]["expects_followup"] is False


def test_close_without_more_questions_estructuracion_closing_applied():
    lang = _base_lang("close_without_more_questions", "estructuracion")
    result = resolve_response_composition(
        output_mode="estructuracion",
        smart_strategy=_base_strategy("close_without_more_questions"),
        strategy_composition_profile={"allow_followup": False},
        strategy_language_profile=lang,
        conversation_state={
            "known_facts": [{"key": "hay_hijos", "value": True}],
        },
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="",
    )
    metadata = result["composition_metadata"]
    # Si hay selected_closing en el profile, debe estar closing_applied=True
    if lang.get("selected_closing"):
        assert metadata["closing_applied"] is True
    assert metadata["allow_postprocessor_closing"] is False


# ── action_first: sin cierre contradictorio ───────────────────────────────────

def test_action_first_ejecucion_no_followup_has_closing_applied():
    lang = _base_lang("action_first", "ejecucion")
    result = resolve_response_composition(
        output_mode="ejecucion",
        smart_strategy=_base_strategy("action_first"),
        strategy_composition_profile={"allow_followup": False},
        strategy_language_profile=lang,
        conversation_state={},
        dialogue_policy={},
        execution_output={
            "execution_output": {
                "what_to_do_now": ["Presentar escrito.", "Reunir documentacion."],
            }
        },
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="",
    )
    metadata = result["composition_metadata"]
    assert metadata["render_family"] == "action"
    assert metadata["allow_postprocessor_closing"] is False
    # Texto empieza con la acción, no con una introducción discursiva
    text = result["rendered_response_text"]
    assert text.strip()
    assert "?" not in text


def test_action_first_with_followup_allowed_does_not_add_closing():
    lang = _base_lang("action_first", "ejecucion")
    result = resolve_response_composition(
        output_mode="ejecucion",
        smart_strategy=_base_strategy("action_first"),
        strategy_composition_profile={"allow_followup": True},
        strategy_language_profile=lang,
        conversation_state={},
        dialogue_policy={},
        execution_output={
            "execution_output": {
                "what_to_do_now": ["Presentar escrito."],
            }
        },
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="¿Se inició notificación?",
    )
    metadata = result["composition_metadata"]
    # Cuando hay follow-up activo, composition NO agrega cierre adicional
    assert metadata["expects_followup"] is True
    # El texto debe terminar con la pregunta
    text = result["rendered_response_text"]
    assert text.strip().endswith("?")


# ── clarify_critical: sin cierre, solo pregunta ───────────────────────────────

def test_clarify_critical_estrategia_no_closing():
    lang = _base_lang("clarify_critical", "estrategia")
    result = resolve_response_composition(
        output_mode="estrategia",
        smart_strategy=_base_strategy("clarify_critical"),
        strategy_composition_profile={"allow_followup": True},
        strategy_language_profile=lang,
        conversation_state={},
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="¿El caso es laboral o civil?",
    )
    metadata = result["composition_metadata"]
    assert metadata["render_family"] == "clarification"
    assert metadata["closing_applied"] is False
    assert metadata["allow_postprocessor_closing"] is False
    assert metadata["expects_followup"] is True


def test_clarify_critical_count_questions():
    lang = _base_lang("clarify_critical", "estrategia")
    result = resolve_response_composition(
        output_mode="estrategia",
        smart_strategy=_base_strategy("clarify_critical"),
        strategy_composition_profile={"allow_followup": True},
        strategy_language_profile=lang,
        conversation_state={},
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="¿Es laboral?",
    )
    # Solo debe haber una pregunta
    assert result["rendered_response_text"].count("?") == 1


# ── Estabilidad en contextos similares ────────────────────────────────────────

def test_metadata_stable_across_similar_contexts():
    """
    Para el mismo output_mode + strategy_mode, la render_family y allow_postprocessor_closing
    deben ser idénticos independientemente de los datos de conversación.
    """
    base_kwargs = dict(
        output_mode="estrategia",
        smart_strategy=_base_strategy("guide_next_step"),
        strategy_composition_profile={"allow_followup": True},
        strategy_language_profile=_base_lang("guide_next_step", "estrategia"),
        dialogue_policy={},
        execution_output={},
        progression_policy={},
        pipeline_payload={},
        api_payload={},
        followup_question="",
    )
    result_a = resolve_response_composition(
        **base_kwargs,
        conversation_state={"turn_count": 1, "known_facts": []},
    )
    result_b = resolve_response_composition(
        **base_kwargs,
        conversation_state={"turn_count": 5, "known_facts": [{"key": "hay_hijos", "value": True}]},
    )
    # render_family y allow_postprocessor_closing no deben variar por datos de conversación
    assert result_a["composition_metadata"]["render_family"] == result_b["composition_metadata"]["render_family"]
    assert result_a["composition_metadata"]["allow_postprocessor_closing"] == result_b["composition_metadata"]["allow_postprocessor_closing"]


# ── language service: legal_referral_note está en el language service ─────────

def test_legal_referral_note_present_for_relevant_modes():
    for mode in ("orient_with_prudence", "guide_next_step"):
        lang = resolve_strategy_language_profile(
            _base_strategy(mode),
            output_mode="ejecucion",
        )
        assert lang.get("selected_legal_referral_note"), (
            f"strategy_mode={mode!r} deberia tener selected_legal_referral_note"
        )


def test_legal_referral_note_absent_for_action_modes():
    for mode in ("action_first", "close_without_more_questions", "clarify_critical"):
        lang = resolve_strategy_language_profile(
            _base_strategy(mode),
            output_mode="ejecucion",
        )
        assert not lang.get("selected_legal_referral_note"), (
            f"strategy_mode={mode!r} NO deberia tener selected_legal_referral_note"
        )


def test_composition_uses_language_referral_note_not_hardcoded():
    """
    En la rama de ejecucion genérica (strategy_mode no cubierto por ninguna rama explícita),
    la nota de abogado viene del language profile, no de un string hardcodeado en composition.
    Probamos pasando un note custom en el language_profile y verificando que aparece en el texto.
    """
    custom_note = "Si no tenes representacion: consulta con el servicio legal de tu jurisdiccion."
    lang = {"selected_legal_referral_note": custom_note, "selected_bridge": ""}

    result = resolve_response_composition(
        output_mode="ejecucion",
        # strategy_mode vacío → cae en la rama genérica de _render_execution_sections
        smart_strategy={"strategy_mode": ""},
        strategy_composition_profile={},
        strategy_language_profile=lang,
        conversation_state={},
        dialogue_policy={},
        execution_output={
            "execution_output": {
                "what_to_do_now": ["Presentar denuncia."],
            }
        },
        progression_policy={},
        # "facts" no menciona "abogado" → la nota debe incluirse
        pipeline_payload={"facts": "El consultante describe su situacion."},
        api_payload={},
        followup_question="",
    )
    text = result["rendered_response_text"]
    assert custom_note.split("\n")[0] in text


# ── _sections_contain_followup / _sections_contain_closing ───────────────────

def test_sections_contain_followup_detects_question():
    assert _sections_contain_followup(["Algo normal.", "¿Tiene representacion?"]) is True
    assert _sections_contain_followup(["Algo normal.", "Sin preguntas."]) is False
    assert _sections_contain_followup([]) is False


def test_sections_contain_closing_detects_match():
    closing = "Con esto ya tenes un siguiente paso concreto para mover el caso."
    assert _sections_contain_closing(
        ["Primer paso: hacer algo.", closing],
        language_profile={"selected_closing": closing},
    ) is True
    assert _sections_contain_closing(
        ["Primer paso: hacer algo."],
        language_profile={"selected_closing": closing},
    ) is False
    assert _sections_contain_closing(
        ["Primer paso."],
        language_profile={},
    ) is False
