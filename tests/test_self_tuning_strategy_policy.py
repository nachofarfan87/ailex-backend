from __future__ import annotations

from datetime import timedelta

from app.services.self_tuning_strategy_policy import build_strategy_recommendation
from app.services.utc import utc_now


def _recommendation() -> dict:
    return {
        "candidate_adjustments": [
            {
                "parameter_name": "apply_confidence_delta",
                "current_value": 0.0,
                "proposed_value": -0.02,
                "delta": -0.02,
                "confidence": 0.82,
                "priority_score": 0.8,
                "blocked": False,
                "blocked_reasons": [],
                "explanation": {"why_not": []},
            }
        ],
        "risk_flags": [],
    }


def _meta_snapshot(**overrides) -> dict:
    payload = {
        "recommended_action": "apply",
        "meta_confidence": 0.78,
        "meta_risk_flags": [],
        "history_window_summary": {"weighted_unknown_outcome_rate": 0.1},
        "historical_support": {
            "risky_parameters": [],
            "supportive_parameters": ["apply_confidence_delta"],
            "mode_support": {"requested_mode_evidence_status": "sufficient_mode_evidence"},
        },
        "meta_signals": {"current_context": "stable"},
    }
    payload.update(overrides)
    return payload


def _signals(**overrides) -> dict:
    payload = {
        "trend_stability": 0.82,
        "consistency": 0.84,
        "rollback_ratio": 0.0,
        "sample_size": 64,
        "drift_level": "none",
    }
    payload.update(overrides)
    return payload


def test_fragile_context_produces_prudent_strategy_profile():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(meta_confidence=0.52, meta_signals={"current_context": "fragile"}),
        current_signals=_signals(trend_stability=0.42, consistency=0.45),
        tuning_history=[],
    )

    assert snapshot["strategy_profile"] in {"micro_adjustment", "restricted_adjustment"}


def test_low_meta_confidence_prefers_micro_or_restricted_strategy():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(meta_confidence=0.32),
        current_signals=_signals(),
        tuning_history=[],
    )

    assert snapshot["strategy_profile"] in {"micro_adjustment", "restricted_adjustment"}
    assert snapshot["strategy_support_level"] in {"low", "medium"}


def test_risky_parameter_gets_step_reduced():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(
            historical_support={"risky_parameters": ["apply_confidence_delta"], "supportive_parameters": []},
        ),
        current_signals=_signals(),
        tuning_history=[],
    )

    candidate = snapshot["adapted_candidates"][0]
    assert abs(float(candidate["strategy_effective_delta"])) < abs(float(candidate["delta"]))
    assert candidate["strategy_priority_score"] < candidate["priority_score"]


def test_supportive_parameter_can_use_standard_strategy():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(
            meta_confidence=0.86,
            historical_support={
                "risky_parameters": [],
                "supportive_parameters": ["apply_confidence_delta"],
                "mode_support": {"requested_mode_evidence_status": "sufficient_mode_evidence"},
            },
        ),
        current_signals=_signals(),
        tuning_history=[],
    )

    assert snapshot["strategy_profile"] == "standard_adjustment"


def test_rollback_pressure_hardens_strategy():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(meta_risk_flags=["meta_rollback_after_tuning_pressure"]),
        current_signals=_signals(rollback_ratio=0.12),
        tuning_history=[],
    )

    assert snapshot["strategy_profile"] == "restricted_adjustment"


def test_strategy_layer_does_not_relax_observe_only():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(recommended_action="observe_only"),
        current_signals=_signals(),
        tuning_history=[],
    )

    assert snapshot["recommended_action"] == "observe_only"


def test_strategy_extended_cooldown_can_block_candidate():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(meta_confidence=0.3),
        current_signals=_signals(rollback_ratio=0.1),
        tuning_history=[
            {
                "parameter_name": "apply_confidence_delta",
                "created_at": utc_now() - timedelta(hours=4),
            }
        ],
    )

    candidate = snapshot["adapted_candidates"][0]
    assert candidate["blocked"] is True
    assert "strategy_extended_cooldown_active" in candidate["blocked_reasons"]
    assert candidate["strategy_controls"]["effective_cooldown_hours"] >= 24


def test_delta_below_resolution_blocks_candidate():
    snapshot = build_strategy_recommendation(
        recommendation={
            "candidate_adjustments": [
                {
                    "parameter_name": "min_sample_size_delta",
                    "current_value": 0,
                    "proposed_value": 1,
                    "delta": 1,
                    "confidence": 0.88,
                    "priority_score": 0.8,
                    "blocked": False,
                    "blocked_reasons": [],
                    "explanation": {"why_not": []},
                }
            ],
            "risk_flags": [],
        },
        meta_snapshot=_meta_snapshot(
            historical_support={"risky_parameters": ["min_sample_size_delta"], "supportive_parameters": []},
        ),
        current_signals=_signals(rollback_ratio=0.1),
        tuning_history=[],
    )

    candidate = snapshot["adapted_candidates"][0]
    assert candidate["blocked"] is True
    assert "strategy_micro_step_below_resolution" in candidate["blocked_reasons"]


def test_delta_trace_is_clamped_and_visible():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(meta_signals={"current_context": "stable"}),
        current_signals=_signals(),
        tuning_history=[],
    )

    candidate = snapshot["adapted_candidates"][0]
    assert "strategy_delta_trace" in candidate
    assert "effective_step_resolution" in candidate["strategy_controls"]
    assert "priority_contribution_breakdown" in candidate
    assert "priority_contribution_breakdown" in candidate["explanation"]


def test_hysteresis_keeps_more_restrictive_previous_profile_without_strong_evidence():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(meta_confidence=0.7),
        current_signals=_signals(),
        tuning_history=[],
        strategy_history=[{"final_strategy_profile": "restricted_adjustment"}],
    )

    assert snapshot["final_strategy_profile"] == "restricted_adjustment"
    assert snapshot["strategy_hysteresis_applied"] is True
    assert "strategy_hysteresis_state" in snapshot
    assert snapshot["strategy_hysteresis_state"]["hysteresis_locked_profile"] == "restricted_adjustment"
    assert snapshot["strategy_hysteresis_state"]["requested_strategy_profile"] == "micro_adjustment"


def test_hysteresis_state_exposes_relaxation_retention():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(meta_confidence=0.78),
        current_signals=_signals(),
        tuning_history=[],
        strategy_history=[{"final_strategy_profile": "micro_adjustment"}],
    )

    state = snapshot["strategy_hysteresis_state"]
    assert state["hysteresis_recent_profiles"] == ["micro_adjustment"]
    assert state["hysteresis_relaxation_allowed"] is False


def test_hysteresis_allows_hardening_faster_than_relaxation():
    snapshot = build_strategy_recommendation(
        recommendation=_recommendation(),
        meta_snapshot=_meta_snapshot(meta_confidence=0.86, meta_risk_flags=["meta_rollback_after_tuning_pressure"]),
        current_signals=_signals(rollback_ratio=0.12),
        tuning_history=[],
        strategy_history=[{"final_strategy_profile": "standard_adjustment"}],
    )

    assert snapshot["final_strategy_profile"] == "restricted_adjustment"
    assert snapshot["strategy_hysteresis_applied"] is False
