# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_strategy_language_service.py
from __future__ import annotations

from app.services.strategy_language_service import resolve_strategy_language_profile


def test_action_first_profile_is_direct_and_practical():
    profile = resolve_strategy_language_profile(
        {"strategy_mode": "action_first"},
        composition_profile={"allow_followup": False},
        conversation_state={"turn_count": 2},
        output_mode="ejecucion",
        turn_type="followup",
    )

    assert profile["tone_style"] == "executive"
    assert profile["directiveness_level"] == "high"
    assert profile["selected_opening"] == ""
    assert profile["selected_bridge"]


def test_orient_with_prudence_profile_keeps_visible_prudence():
    profile = resolve_strategy_language_profile(
        {"strategy_mode": "orient_with_prudence"},
        composition_profile={"allow_followup": False},
        conversation_state={"turn_count": 3},
        output_mode="estrategia",
        turn_type="followup",
    )

    assert profile["tone_style"] == "prudent"
    assert profile["prudence_visibility"] == "high"
    assert "prud" in profile["reason"].lower()


def test_substantive_analysis_profile_is_more_analytic():
    profile = resolve_strategy_language_profile(
        {"strategy_mode": "substantive_analysis"},
        composition_profile={"allow_followup": False},
        conversation_state={"turn_count": 4},
        output_mode="estrategia",
        turn_type="partial_closure",
    )

    assert profile["tone_style"] == "analytical"
    assert profile["selected_closing"]
    assert profile["followup_style"] == "disabled"


def test_close_without_more_questions_does_not_return_followup_intro():
    profile = resolve_strategy_language_profile(
        {"strategy_mode": "close_without_more_questions"},
        composition_profile={"allow_followup": False},
        conversation_state={"turn_count": 5},
        output_mode="estructuracion",
        turn_type="partial_closure",
    )

    assert profile["selected_followup_intro"] == ""
    assert profile["selected_closing"]


def test_profiles_differ_across_strategy_modes():
    action_profile = resolve_strategy_language_profile(
        {"strategy_mode": "action_first"},
        conversation_state={"turn_count": 2},
        output_mode="ejecucion",
        turn_type="followup",
    )
    prudent_profile = resolve_strategy_language_profile(
        {"strategy_mode": "orient_with_prudence"},
        conversation_state={"turn_count": 2},
        output_mode="estrategia",
        turn_type="followup",
    )

    assert action_profile["tone_style"] != prudent_profile["tone_style"]
    assert action_profile["selected_bridge"] != prudent_profile["selected_bridge"]
