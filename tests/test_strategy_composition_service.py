# backend/tests/test_strategy_composition_service.py
from __future__ import annotations

from app.services.strategy_composition_service import resolve_strategy_composition_profile


def test_clarify_critical_profile_is_brief_and_allows_followup():
    profile = resolve_strategy_composition_profile(
        {"strategy_mode": "clarify_critical"},
        output_mode="estrategia",
        case_followup={"should_ask": True},
        case_confidence={},
    )

    assert profile["content_density"] == "brief"
    assert profile["allow_followup"] is True
    assert profile["closing_style"] == "question_only"


def test_action_first_profile_prioritizes_action():
    profile = resolve_strategy_composition_profile(
        {"strategy_mode": "action_first"},
        output_mode="ejecucion",
        case_followup={"should_ask": False},
        case_confidence={},
    )

    assert profile["prioritize_action"] is True
    assert profile["opening_style"] == "none"
    assert profile["content_density"] == "guided"


def test_substantive_analysis_profile_expands_depth():
    profile = resolve_strategy_composition_profile(
        {"strategy_mode": "substantive_analysis"},
        output_mode="estrategia",
        case_followup={"should_ask": True},
        case_confidence={"recommended_depth": "extended"},
    )

    assert profile["allow_followup"] is False
    assert profile["content_density"] == "extended"
    assert profile["closing_style"] == "analysis_close"


def test_close_without_more_questions_disallows_followup():
    profile = resolve_strategy_composition_profile(
        {"strategy_mode": "close_without_more_questions"},
        output_mode="estructuracion",
        case_followup={"should_ask": True},
        case_confidence={},
    )

    assert profile["allow_followup"] is False
    assert profile["content_density"] == "brief"
    assert profile["closing_style"] == "clean_close"


def test_default_profile_falls_back_to_prudent_guided():
    profile = resolve_strategy_composition_profile(
        {"strategy_mode": "orient_with_prudence"},
        output_mode="orientacion_inicial",
        case_followup={},
        case_confidence={},
    )

    assert profile["content_density"] == "guided"
    assert profile["limit_analysis"] is True
    assert profile["prioritize_action"] is False
