# backend/tests/test_conversation_consistency_service.py
"""
Tests — FASE 12.7: Conversation Consistency Hardening

Cubre:
1. Reglas de supresión por strategy_mode
2. lead_type_whitelist garantiza leads compatibles con el strategy_mode
3. stable_variation_bucket no cambia con turn_count
4. stable_variation_bucket cambia cuando cambia el contexto estratégico
5. Consistencia multi-turno: mismo contexto → mismos valores de output
6. action_first → sin lead, sin body_bridge
7. close_without_more_questions → sin lead, sin bridge, sin question_intro
8. clarify_critical → sin body_bridge, max 1 párrafo de body
9. orient_with_prudence → sin restricciones agresivas
10. guide_next_step → lead permitido, max 2 párrafos
"""
from __future__ import annotations

import pytest

from app.services.conversation_consistency_service import (
    resolve_consistency_policy,
    _compute_stable_variation_bucket,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _state(
    case_completeness: str = "low",
    turn_count: int = 1,
) -> dict:
    return {
        "turn_count": turn_count,
        "progress_signals": {"case_completeness": case_completeness},
    }


def _policy(
    strategy_mode: str,
    output_mode: str = "orientacion_inicial",
    conversation_state: dict | None = None,
    composition_profile: dict | None = None,
) -> dict:
    return resolve_consistency_policy(
        strategy_mode=strategy_mode,
        output_mode=output_mode,
        composition_profile=composition_profile or {},
        conversation_state=conversation_state or _state(),
    )


# ── Campos obligatorios ───────────────────────────────────────────────────────

def test_policy_has_all_required_keys():
    policy = _policy("orient_with_prudence")
    for key in (
        "strategy_mode", "suppress_lead", "suppress_body_bridge",
        "suppress_question_intro", "max_body_paragraphs",
        "lead_type_whitelist", "stable_variation_bucket", "reason",
    ):
        assert key in policy, f"Falta clave requerida: {key!r}"


# ── action_first ──────────────────────────────────────────────────────────────

def test_action_first_suppresses_lead():
    policy = _policy("action_first")
    assert policy["suppress_lead"] is True


def test_action_first_suppresses_body_bridge():
    policy = _policy("action_first")
    assert policy["suppress_body_bridge"] is True


def test_action_first_lead_whitelist_is_empty():
    policy = _policy("action_first")
    assert policy["lead_type_whitelist"] == []


def test_action_first_does_not_suppress_question_intro():
    # action_first puede tener follow-up crítico
    policy = resolve_consistency_policy(
        strategy_mode="action_first",
        output_mode="orientacion_inicial",
        composition_profile={"allow_followup": True},
        conversation_state=_state(),
    )
    assert policy["suppress_question_intro"] is False


def test_action_first_suppresses_question_intro_when_followup_disabled():
    policy = resolve_consistency_policy(
        strategy_mode="action_first",
        output_mode="orientacion_inicial",
        composition_profile={"allow_followup": False},
        conversation_state=_state(),
    )
    assert policy["suppress_question_intro"] is True


# ── close_without_more_questions ─────────────────────────────────────────────

def test_close_without_more_questions_suppresses_lead():
    policy = _policy("close_without_more_questions")
    assert policy["suppress_lead"] is True


def test_close_without_more_questions_suppresses_body_bridge():
    policy = _policy("close_without_more_questions")
    assert policy["suppress_body_bridge"] is True


def test_close_without_more_questions_suppresses_question_intro():
    policy = _policy("close_without_more_questions")
    assert policy["suppress_question_intro"] is True


def test_close_without_more_questions_lead_whitelist_contains_only_closure():
    policy = _policy("close_without_more_questions")
    whitelist = policy["lead_type_whitelist"]
    assert whitelist is not None
    assert whitelist == ["partial_closure"]


def test_close_without_more_questions_max_body_is_two():
    policy = _policy("close_without_more_questions")
    assert policy["max_body_paragraphs"] == 2


# ── clarify_critical ──────────────────────────────────────────────────────────

def test_clarify_critical_suppresses_body_bridge():
    policy = _policy("clarify_critical")
    assert policy["suppress_body_bridge"] is True


def test_clarify_critical_does_not_suppress_lead():
    # El framing de clarificación es útil ("Hay un punto que define esto ahora.")
    policy = _policy("clarify_critical")
    assert policy["suppress_lead"] is False


def test_clarify_critical_max_body_is_one():
    policy = _policy("clarify_critical")
    assert policy["max_body_paragraphs"] == 1


def test_clarify_critical_lead_whitelist_only_clarification():
    policy = _policy("clarify_critical")
    assert policy["lead_type_whitelist"] == ["clarification"]


# ── orient_with_prudence ──────────────────────────────────────────────────────

def test_orient_with_prudence_no_suppression():
    policy = _policy("orient_with_prudence")
    assert policy["suppress_lead"] is False
    assert policy["suppress_body_bridge"] is False
    assert policy["suppress_question_intro"] is False


def test_orient_with_prudence_no_body_limit():
    policy = _policy("orient_with_prudence")
    assert policy["max_body_paragraphs"] is None


def test_orient_with_prudence_lead_whitelist_excludes_clarification():
    policy = _policy("orient_with_prudence")
    whitelist = policy["lead_type_whitelist"]
    assert whitelist is not None
    assert "clarification" not in whitelist


# ── guide_next_step ───────────────────────────────────────────────────────────

def test_guide_next_step_allows_lead():
    policy = _policy("guide_next_step")
    assert policy["suppress_lead"] is False


def test_guide_next_step_max_body_is_two():
    policy = _policy("guide_next_step")
    assert policy["max_body_paragraphs"] == 2


def test_guide_next_step_whitelist_excludes_clarification():
    policy = _policy("guide_next_step")
    whitelist = policy["lead_type_whitelist"]
    assert whitelist is not None
    assert "clarification" not in whitelist


# ── output_mode != orientacion_inicial siempre suprime lead ──────────────────

@pytest.mark.parametrize("output_mode", ["estrategia", "estructuracion", "ejecucion"])
def test_non_initial_output_mode_always_suppresses_lead(output_mode):
    # Para cualquier strategy_mode, si output_mode no es orientacion_inicial
    # el lead siempre se suprime (composition_service maneja la apertura en esos modos)
    for mode in ("orient_with_prudence", "guide_next_step", "clarify_critical"):
        policy = _policy(mode, output_mode=output_mode)
        assert policy["suppress_lead"] is True, (
            f"output_mode={output_mode!r}, strategy_mode={mode!r}: suppress_lead debería ser True"
        )


# ── Stable variation bucket ───────────────────────────────────────────────────

def test_stable_bucket_does_not_change_with_turn_count():
    """El bucket no debe cambiar entre turnos con el mismo contexto estratégico."""
    base = dict(
        strategy_mode="orient_with_prudence",
        output_mode="orientacion_inicial",
    )
    b1 = _compute_stable_variation_bucket(**base, conversation_state=_state(turn_count=1))
    b2 = _compute_stable_variation_bucket(**base, conversation_state=_state(turn_count=2))
    b3 = _compute_stable_variation_bucket(**base, conversation_state=_state(turn_count=7))
    assert b1 == b2 == b3, "El bucket cambió con el turn_count sin cambio de contexto"


def test_stable_bucket_changes_with_strategy_mode():
    """Distintos strategy_mode deben producir buckets potencialmente distintos."""
    buckets = {
        mode: _compute_stable_variation_bucket(
            strategy_mode=mode,
            output_mode="orientacion_inicial",
            conversation_state=_state(),
        )
        for mode in ("clarify_critical", "action_first", "close_without_more_questions",
                     "orient_with_prudence", "guide_next_step")
    }
    # No todos los buckets pueden ser iguales — debe haber variación entre modos
    assert len(set(buckets.values())) > 1, (
        "Todos los strategy_mode producen el mismo bucket, no hay variación entre modos"
    )


def test_stable_bucket_same_for_same_context():
    """Mismo contexto → mismo bucket (determinismo)."""
    state = _state(case_completeness="medium", turn_count=5)
    b1 = _compute_stable_variation_bucket(
        strategy_mode="guide_next_step",
        output_mode="estrategia",
        conversation_state=state,
    )
    b2 = _compute_stable_variation_bucket(
        strategy_mode="guide_next_step",
        output_mode="estrategia",
        conversation_state=state,
    )
    assert b1 == b2


def test_stable_bucket_from_policy_is_integer_in_range():
    for mode in ("clarify_critical", "action_first", "orient_with_prudence",
                 "close_without_more_questions", "guide_next_step"):
        policy = _policy(mode)
        bucket = policy["stable_variation_bucket"]
        assert isinstance(bucket, int), f"bucket no es int para {mode!r}"
        assert 0 <= bucket <= 2, f"bucket {bucket} fuera del rango [0, 2] para {mode!r}"


# ── Consistencia multi-turno ──────────────────────────────────────────────────

def test_same_context_produces_same_suppress_flags():
    """Mismo strategy_mode + output_mode + completeness → mismos suppress flags."""
    policy_a = resolve_consistency_policy(
        strategy_mode="guide_next_step",
        output_mode="orientacion_inicial",
        conversation_state=_state(case_completeness="medium", turn_count=3),
    )
    policy_b = resolve_consistency_policy(
        strategy_mode="guide_next_step",
        output_mode="orientacion_inicial",
        conversation_state=_state(case_completeness="medium", turn_count=8),
    )
    assert policy_a["suppress_lead"] == policy_b["suppress_lead"]
    assert policy_a["suppress_body_bridge"] == policy_b["suppress_body_bridge"]
    assert policy_a["suppress_question_intro"] == policy_b["suppress_question_intro"]
    assert policy_a["stable_variation_bucket"] == policy_b["stable_variation_bucket"]


def test_strategy_mode_change_may_change_bucket():
    """Un cambio real de strategy_mode puede producir un bucket diferente."""
    b_orient = _compute_stable_variation_bucket(
        strategy_mode="orient_with_prudence",
        output_mode="orientacion_inicial",
        conversation_state=_state(case_completeness="low"),
    )
    b_clarify = _compute_stable_variation_bucket(
        strategy_mode="clarify_critical",
        output_mode="orientacion_inicial",
        conversation_state=_state(case_completeness="low"),
    )
    # No es un error que sean iguales por colisión, pero documentamos que pueden variar
    # El test real es que el bucket del turno siguiente no cambia si el modo no cambia
    assert isinstance(b_orient, int)
    assert isinstance(b_clarify, int)


# ── allow_followup=False siempre suprime question_intro ──────────────────────

@pytest.mark.parametrize("strategy_mode", [
    "orient_with_prudence", "guide_next_step", "substantive_analysis",
])
def test_allow_followup_false_suppresses_question_intro(strategy_mode):
    policy = resolve_consistency_policy(
        strategy_mode=strategy_mode,
        output_mode="orientacion_inicial",
        composition_profile={"allow_followup": False},
        conversation_state=_state(),
    )
    assert policy["suppress_question_intro"] is True, (
        f"strategy_mode={strategy_mode!r} con allow_followup=False debería suprimir question_intro"
    )
