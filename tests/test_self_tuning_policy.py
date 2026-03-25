from __future__ import annotations

from datetime import timedelta

from app.services.self_tuning_policy import evaluate_self_tuning_candidates
from app.services.utc import utc_now


def _signals(**overrides) -> dict:
    sample_size = overrides.get("sample_size", 64)
    base = {
        "sample_size": sample_size,
        "impact_total": overrides.get("impact_total", sample_size),
        "total_observations": overrides.get("total_observations", sample_size),
        "audited_count": overrides.get("audited_count", sample_size),
        "improvement_rate": 0.76,
        "regression_rate": 0.04,
        "neutral_rate": 0.20,
        "failed_ratio": 0.05,
        "questionable_ratio": 0.1,
        "rollback_ratio": 0.0,
        "rollback_candidates": 0,
        "recent_avg_score": 0.38,
        "previous_avg_score": 0.32,
        "historical_avg_score": 0.24,
        "recent_vs_historical_delta": 0.14,
        "trend_stability": 0.82,
        "consistency": 0.86,
        "drift_level": "none",
        "governance_status": "healthy",
        "top_flag_counts": {},
    }
    base.update(overrides)
    return base


def test_no_data_returns_blocked_no_data():
    candidates, blocked_reasons, risk_flags = evaluate_self_tuning_candidates(
        signals=_signals(sample_size=0, impact_total=0, total_observations=0, audited_count=0),
        current_controls={},
        tuning_history=[],
    )

    assert candidates == []
    assert "no_data" in blocked_reasons
    assert "insufficient_data_for_tuning" in risk_flags


def test_cold_start_blocks_even_if_base_sample_exists():
    candidates, blocked_reasons, risk_flags = evaluate_self_tuning_candidates(
        signals=_signals(sample_size=28),
        current_controls={},
        tuning_history=[],
    )

    assert candidates == []
    assert "cold_start_tuning_block" in blocked_reasons
    assert "cold_start_tuning_block" in risk_flags


def test_new_consistency_penalizes_mixed_improvement_and_regression():
    candidates, blocked_reasons, risk_flags = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.42,
            regression_rate=0.28,
            neutral_rate=0.30,
            consistency=0.32,
            questionable_ratio=0.22,
        ),
        current_controls={},
        tuning_history=[],
    )

    assert candidates == []
    assert "mixed_evidence" in blocked_reasons
    assert "mixed_evidence" in risk_flags


def test_trend_instability_blocks_tuning():
    candidates, blocked_reasons, risk_flags = evaluate_self_tuning_candidates(
        signals=_signals(trend_stability=0.32),
        current_controls={},
        tuning_history=[],
    )

    assert candidates == []
    assert "unstable_trend" in blocked_reasons
    assert "unstable_trend" in risk_flags


def test_contradictory_recent_evidence_blocks_tuning():
    candidates, blocked_reasons, risk_flags = evaluate_self_tuning_candidates(
        signals=_signals(
            recent_avg_score=-0.08,
            previous_avg_score=0.24,
            historical_avg_score=0.18,
            recent_vs_historical_delta=-0.31,
            regression_rate=0.16,
        ),
        current_controls={},
        tuning_history=[],
    )

    assert candidates == []
    assert "contradictory_recent_evidence" in blocked_reasons
    assert "contradictory_recent_evidence" in risk_flags


def test_strong_positive_stable_evidence_generates_candidate():
    candidates, blocked_reasons, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={},
        tuning_history=[],
    )

    actionable = [candidate for candidate in candidates if not candidate["blocked"]]
    assert blocked_reasons == []
    assert actionable
    assert actionable[0]["direction"] in {"increase", "decrease"}


def test_historical_ineffective_tuning_blocks_parameter():
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={},
        tuning_history=[
            {
                "parameter_name": "apply_confidence_delta",
                "direction": "decrease",
                "effectiveness": "ineffective",
                "created_at": utc_now() - timedelta(hours=96),
            }
        ],
    )

    target = next(candidate for candidate in candidates if candidate["parameter_name"] == "apply_confidence_delta")
    assert "historical_ineffective_tuning" in target["blocked_reasons"]


def test_unknown_tuning_history_does_not_block_by_itself():
    candidates, blocked_reasons, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={},
        tuning_history=[
            {
                "parameter_name": "apply_confidence_delta",
                "direction": "decrease",
                "effectiveness": "unknown",
                "created_at": utc_now() - timedelta(hours=96),
            }
        ],
    )

    actionable = [candidate for candidate in candidates if not candidate["blocked"]]
    assert blocked_reasons == []
    assert actionable


def test_rollback_pressure_blocks_tuning():
    candidates, blocked_reasons, risk_flags = evaluate_self_tuning_candidates(
        signals=_signals(rollback_ratio=0.09, rollback_candidates=3),
        current_controls={},
        tuning_history=[],
    )

    assert candidates == []
    assert "rollback_pressure_block" in blocked_reasons
    assert "rollback_pressure" in risk_flags


def test_candidate_outside_bounds_is_clamped():
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.7,
            trend_stability=0.78,
        ),
        current_controls={"apply_confidence_delta": 0.2},
        tuning_history=[],
    )

    target = next(candidate for candidate in candidates if candidate["parameter_name"] == "apply_confidence_delta")
    assert target["proposed_value"] == 0.2
    assert "parameter_at_bound" in target["blocked_reasons"]


def test_cooldown_active_blocks_candidate():
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={},
        tuning_history=[
            {
                "parameter_name": "apply_confidence_delta",
                "direction": "decrease",
                "effectiveness": "effective",
                "created_at": utc_now(),
            }
        ],
    )

    target = next(candidate for candidate in candidates if candidate["parameter_name"] == "apply_confidence_delta")
    assert "cooldown_active" in target["blocked_reasons"]


def test_only_allowlisted_params_are_returned():
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={"unauthorized_param": 999},
        tuning_history=[],
    )

    assert all(candidate["parameter_name"] != "unauthorized_param" for candidate in candidates)


def test_candidate_prioritization_prefers_critical_parameters():
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={},
        tuning_history=[],
    )

    actionable = [candidate for candidate in candidates if not candidate["blocked"]]
    assert actionable
    assert actionable[0]["parameter_name"] == "apply_confidence_delta"
    assert actionable[0]["priority_score"] >= actionable[-1]["priority_score"]


def test_max_adjustments_per_cycle_is_respected():
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={},
        tuning_history=[],
    )

    actionable = [candidate for candidate in candidates if not candidate["blocked"]]
    assert len(actionable) <= 2


def test_anti_oscillation_blocks_direction_flip():
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={},
        tuning_history=[
            {
                "parameter_name": "apply_confidence_delta",
                "direction": "decrease",
                "effectiveness": "effective",
                "created_at": utc_now(),
            }
        ],
    )

    target = next(candidate for candidate in candidates if candidate["parameter_name"] == "apply_confidence_delta")
    assert "anti_oscillation_block" in target["blocked_reasons"] or "cooldown_active" in target["blocked_reasons"]


# ---------------------------------------------------------------------------
# FASE 8.1B — Safety Envelope, Guardrails, Aggressiveness, Budget, Explanation
# ---------------------------------------------------------------------------


def test_safety_envelope_blocks_excess_total_delta():
    """Safety envelope caps total |delta| across all candidates per cycle."""
    candidates, blocked_reasons, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={},
        tuning_history=[],
    )

    actionable = [c for c in candidates if not c["blocked"]]
    total_actionable_delta = sum(abs(float(c["delta"])) for c in actionable)
    assert total_actionable_delta <= 0.08


def test_guardrails_block_safe_zone_violation():
    """If current is inside safe zone, candidate cannot exit it."""
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={"apply_confidence_delta": 0.12},
        tuning_history=[],
    )

    target = next(c for c in candidates if c["parameter_name"] == "apply_confidence_delta")
    assert target["blocked"] is True
    assert "guardrail_safe_zone_exit_blocked" in target["blocked_reasons"]


def test_guardrails_allow_recovery_back_to_safe_zone():
    """If current is outside safe zone, moving back toward it is allowed."""
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={"apply_confidence_delta": -0.08},
        tuning_history=[],
    )

    target = next(c for c in candidates if c["parameter_name"] == "apply_confidence_delta")
    assert target["current_value"] == -0.08
    assert target["proposed_value"] == -0.06
    assert "guardrail_safe_zone_no_recovery" not in target["blocked_reasons"]


def test_guardrails_block_when_outside_safe_zone_and_not_recovering():
    """If current is outside safe zone, it cannot move farther away."""
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.76,
            regression_rate=0.04,
            consistency=0.86,
            trend_stability=0.82,
        ),
        current_controls={"apply_confidence_delta": -0.08},
        tuning_history=[],
    )

    target = next(c for c in candidates if c["parameter_name"] == "apply_confidence_delta")
    assert target["blocked"] is True
    assert "guardrail_safe_zone_no_recovery" in target["blocked_reasons"]


def test_guardrails_block_daily_shift_exceeded():
    """Guardrail blocks when accumulated daily shift exceeds max_daily_shift."""
    now = utc_now()
    heavy_history = [
        {
            "parameter_name": "apply_confidence_delta",
            "direction": "increase",
            "effectiveness": "effective",
            "created_at": now - timedelta(hours=6),
            "delta": 0.02,
        },
        {
            "parameter_name": "apply_confidence_delta",
            "direction": "increase",
            "effectiveness": "effective",
            "created_at": now - timedelta(hours=12),
            "delta": 0.02,
        },
        {
            "parameter_name": "apply_confidence_delta",
            "direction": "increase",
            "effectiveness": "effective",
            "created_at": now - timedelta(hours=18),
            "delta": 0.02,
        },
    ]

    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={},
        tuning_history=heavy_history,
    )

    target = next(c for c in candidates if c["parameter_name"] == "apply_confidence_delta")
    assert target["blocked"] is True
    guardrail_or_budget = any(
        r.startswith("guardrail_") or r.startswith("tuning_budget_") or r == "cooldown_active"
        for r in target["blocked_reasons"]
    )
    assert guardrail_or_budget


def test_aggressiveness_conservative_limits_candidates():
    """Conservative mode limits max adjustments to 1."""
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={},
        tuning_history=[],
        aggressiveness_mode="conservative",
    )

    actionable = [c for c in candidates if not c["blocked"]]
    assert len(actionable) <= 1


def test_aggressiveness_conservative_reduces_confidence():
    """Conservative mode applies 0.9 multiplier to confidence."""
    candidates_balanced, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={},
        tuning_history=[],
        aggressiveness_mode="balanced",
    )
    candidates_conservative, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={},
        tuning_history=[],
        aggressiveness_mode="conservative",
    )

    for cb in candidates_balanced:
        if cb["blocked"]:
            continue
        cc = next((c for c in candidates_conservative if c["parameter_name"] == cb["parameter_name"]), None)
        if cc and not cc["blocked"]:
            assert cc["confidence"] <= cb["confidence"]


def test_tuning_budget_blocks_recent_change_count():
    """Budget blocks by recent count-in-window, not by fake consecutiveness semantics."""
    now = utc_now()
    history = [
        {
            "parameter_name": "apply_confidence_delta",
            "direction": "decrease",
            "effectiveness": "effective",
            "created_at": now - timedelta(hours=h),
            "delta": 0.02,
        }
        for h in [30, 60, 96]
    ]

    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={},
        tuning_history=history,
    )

    target = next(c for c in candidates if c["parameter_name"] == "apply_confidence_delta")
    assert target["blocked"] is True
    budget_or_other = any(
        r == "tuning_budget_recent_change_count_exceeded" or r == "historical_ineffective_tuning" or r == "cooldown_active"
        for r in target["blocked_reasons"]
    )
    assert budget_or_other


def test_explanation_fields_present_on_candidate():
    """Every candidate must have a complete explanation dict."""
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(),
        current_controls={},
        tuning_history=[],
    )

    assert candidates
    for candidate in candidates:
        explanation = candidate.get("explanation")
        assert explanation is not None, f"Missing explanation on {candidate['parameter_name']}"
        assert "why" in explanation
        assert "why_not" in explanation
        assert isinstance(explanation["why_not"], list)
        assert "risk_context" in explanation
        assert isinstance(explanation["risk_context"], list)
        assert "historical_context" in explanation
        assert isinstance(explanation["historical_context"], dict)
        assert "dominant_signal" in explanation
        assert "stability" in explanation


def test_explanation_why_not_populated_when_blocked():
    """Blocked candidates should have non-empty why_not in explanation."""
    candidates, _, _ = evaluate_self_tuning_candidates(
        signals=_signals(
            improvement_rate=0.18,
            regression_rate=0.18,
            failed_ratio=0.12,
            top_flag_counts={"simulation_overconfidence": 2},
            consistency=0.72,
            trend_stability=0.8,
        ),
        current_controls={"apply_confidence_delta": 0.12},
        tuning_history=[],
    )

    target = next(c for c in candidates if c["parameter_name"] == "apply_confidence_delta")
    assert target["blocked"] is True
    assert len(target["explanation"]["why_not"]) > 0
