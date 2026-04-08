# backend/tests/test_progress_behavior_intent.py
"""
Tests — FASE 13C ajustes finos: resolve_progress_behavior_intent

Verifica que el helper centraliza correctamente las señales operativas
que tanto smart_strategy_service como case_followup_service consumen.
"""
from __future__ import annotations

import pytest

from app.services.case_progress_service import resolve_progress_behavior_intent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _progress(
    stage: str = "",
    next_step_type: str = "",
    progress_status: str = "",
    readiness_label: str = "",
    critical_gaps: list | None = None,
    important_gaps: list | None = None,
    blocking_issues: list | None = None,
    contradiction_count: int = 0,
) -> dict:
    return {
        "stage": stage,
        "next_step_type": next_step_type,
        "progress_status": progress_status,
        "readiness_label": readiness_label,
        "critical_gaps": critical_gaps or [],
        "important_gaps": important_gaps or [],
        "blocking_issues": blocking_issues or [],
        "contradiction_count": contradiction_count,
    }


def _gap(key: str, purpose: str = "", category: str = "") -> dict:
    return {"key": key, "purpose": purpose, "category": category, "priority": "medium"}


def _blocker(severity: str = "high") -> dict:
    return {"type": "test_blocker", "severity": severity, "key": "test_key", "reason": "test"}


# ── 1. Estructura completa ─────────────────────────────────────────────────────

def test_intent_estructura_completa():
    intent = resolve_progress_behavior_intent({})
    required_keys = {
        "stage", "next_step_type", "progress_status", "readiness_label",
        "has_critical_gaps", "has_blockers", "has_important_gaps",
        "has_contradictions", "has_strong_blocker", "has_non_blocking_critical_gaps",
        "has_high_impact_important_gaps", "should_prioritize_contradiction",
        "should_block_execution", "should_allow_execution",
        "should_reduce_followup", "should_allow_decision_followup",
    }
    for key in required_keys:
        assert key in intent, f"Falta clave requerida: {key!r}"


# ── 2. should_allow_decision_followup ────────────────────────────────────────

def test_intent_should_allow_decision_followup_con_important_procesal():
    intent = resolve_progress_behavior_intent(_progress(
        stage="decision",
        next_step_type="decide",
        important_gaps=[_gap("jurisdiccion", purpose="procesal")],
        critical_gaps=[],
        blocking_issues=[],
    ))
    assert intent["should_allow_decision_followup"] is True


def test_intent_should_allow_decision_followup_sin_important_alto_impacto():
    intent = resolve_progress_behavior_intent(_progress(
        stage="decision",
        next_step_type="decide",
        important_gaps=[_gap("monto_estimado", purpose="economico", category="economico")],
        critical_gaps=[],
        blocking_issues=[],
    ))
    assert intent["should_allow_decision_followup"] is False


def test_intent_should_allow_decision_followup_false_con_critical_gaps():
    """Con critical_gaps presentes, should_allow_decision_followup debe ser False."""
    intent = resolve_progress_behavior_intent(_progress(
        stage="decision",
        important_gaps=[_gap("jurisdiccion", purpose="procesal")],
        critical_gaps=[_gap("vinculo")],
        blocking_issues=[],
    ))
    assert intent["should_allow_decision_followup"] is False


def test_intent_should_allow_decision_followup_false_con_blocker():
    intent = resolve_progress_behavior_intent(_progress(
        stage="decision",
        important_gaps=[_gap("jurisdiccion", purpose="procesal")],
        critical_gaps=[],
        blocking_issues=[_blocker(severity="high")],
    ))
    assert intent["should_allow_decision_followup"] is False


# ── 3. has_non_blocking_critical_gaps ────────────────────────────────────────

def test_intent_has_non_blocking_critical_gaps_cuando_hay_critical_sin_blocker():
    intent = resolve_progress_behavior_intent(_progress(
        stage="estructuracion",
        critical_gaps=[_gap("hay_hijos")],
        blocking_issues=[],
    ))
    assert intent["has_non_blocking_critical_gaps"] is True


def test_intent_no_non_blocking_critical_gaps_cuando_bloqueado():
    intent = resolve_progress_behavior_intent(_progress(
        stage="bloqueado",
        critical_gaps=[_gap("hay_hijos")],
        blocking_issues=[_blocker(severity="high")],
    ))
    assert intent["has_non_blocking_critical_gaps"] is False


def test_intent_no_non_blocking_critical_gaps_sin_critical():
    intent = resolve_progress_behavior_intent(_progress(
        stage="ejecucion",
        critical_gaps=[],
        blocking_issues=[],
    ))
    assert intent["has_non_blocking_critical_gaps"] is False


# ── 4. should_block_execution en inconsistente ───────────────────────────────

def test_intent_should_block_execution_en_inconsistente():
    intent = resolve_progress_behavior_intent(_progress(
        stage="inconsistente",
        blocking_issues=[_blocker(severity="high")],
    ))
    assert intent["should_block_execution"] is True


def test_intent_should_block_execution_en_bloqueado_sin_blocker_explicito():
    """Stage bloqueado implica strong blocker incluso sin blocking_issues listados."""
    intent = resolve_progress_behavior_intent(_progress(
        stage="bloqueado",
        blocking_issues=[],
    ))
    assert intent["should_block_execution"] is True


def test_intent_no_should_block_en_ejecucion_limpia():
    intent = resolve_progress_behavior_intent(_progress(
        stage="ejecucion",
        readiness_label="high",
        blocking_issues=[],
    ))
    assert intent["should_block_execution"] is False


# ── 5. should_reduce_followup ────────────────────────────────────────────────

def test_intent_should_reduce_followup_en_decision_sin_critical():
    intent = resolve_progress_behavior_intent(_progress(
        stage="decision",
        critical_gaps=[],
        blocking_issues=[],
    ))
    assert intent["should_reduce_followup"] is True


def test_intent_should_reduce_followup_false_con_critical_gaps():
    intent = resolve_progress_behavior_intent(_progress(
        stage="decision",
        critical_gaps=[_gap("domicilio")],
    ))
    assert intent["should_reduce_followup"] is False


# ── 6. Backward compat: inputs vacíos ────────────────────────────────────────

def test_intent_backward_compat_inputs_vacios():
    intent = resolve_progress_behavior_intent(None)
    assert isinstance(intent, dict)
    assert intent["should_allow_decision_followup"] is False
    assert intent["has_non_blocking_critical_gaps"] is False
    assert intent["should_block_execution"] is False


# ── 7. Coherencia con smart_strategy_service ─────────────────────────────────

def test_intent_coherencia_con_smart_strategy_signals():
    """
    Verifica que los signals que smart_strategy_service extrae via
    _resolve_case_progress_signals son coherentes con resolve_progress_behavior_intent.
    Los valores de stage, has_critical_gaps, etc. deben coincidir.
    """
    from app.services.smart_strategy_service import resolve_smart_strategy

    progress_input = _progress(
        stage="ejecucion",
        readiness_label="high",
        critical_gaps=[_gap("jurisdiccion")],
        blocking_issues=[],
        next_step_type="execute",
    )

    intent = resolve_progress_behavior_intent(progress_input)

    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True, "domicilio": "Jujuy"},
        missing_facts=[],
        conversation_state={},
        case_followup={"should_ask": False},
        case_confidence={"confidence_level": "medium", "confidence_score": 0.65, "case_stage": "developing"},
        output_mode="ejecucion",
        case_progress=progress_input,
    )

    # El intent dice que hay non-blocking critical gaps
    assert intent["has_non_blocking_critical_gaps"] is True
    # El tono resultante debe ser prudente (no ejecutivo) por esos gaps
    assert result["recommended_tone"] == "prudente"
    # La razón debe mencionar los gaps no bloqueantes
    assert "prudencia" in result["reason"].lower() or "gap" in result["reason"].lower()
