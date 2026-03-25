from __future__ import annotations

from app.services.learning_simulation_service import (
    LOW_SAMPLE_CONFIDENCE_CAP,
    LOW_SAMPLE_SIGNAL_DAMPEN,
    simulate_recommendation_outcome,
)
from app.services.observability_signal_extractor import (
    SIGNAL_DRIFT_DETECTED,
    SIGNAL_HIGH_FAILURE_RATE,
    SIGNAL_LOW_SAMPLE_SIZE,
    SIGNAL_RECENT_REGRESSION,
)


def _recommendation(**overrides) -> dict:
    payload = {
        "event_type": "domain_override",
        "confidence_score": 0.9,
        "priority": 0.8,
        "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
    }
    payload.update(overrides)
    return payload


def _impact_decision(score: float, *, strong_enough: bool = True, raw_total: int = 5, memory_confidence: float = 1.0) -> dict:
    evidence = {
        "available": True,
        "strong_enough": strong_enough,
        "score": score,
        "raw_total": raw_total,
        "memory_confidence": memory_confidence,
    }
    return {
        "signature_evidence": evidence,
        "signature_family_evidence": {},
        "event_type_evidence": {},
        "conflict_summary": {"has_conflict": False, "conflicts": []},
    }


def _adaptive_decision(**overrides) -> dict:
    payload = {
        "should_apply": True,
        "confidence_adjustment": 0.0,
        "risk_level": "low",
        "reasoning": "ok",
        "applied_rules": [],
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Basic simulation outcomes
# ===========================================================================


def test_positive_simulation_with_favorable_history():
    result = simulate_recommendation_outcome(
        recommendation=_recommendation(),
        impact_decision=_impact_decision(0.75),
        adaptive_decision=_adaptive_decision(confidence_adjustment=0.05),
        observability_snapshot={"signals": [], "has_data": True},
    )

    assert result["expected_outcome"] == "positive"
    assert result["expected_impact_score"] > 0.2
    assert result["confidence_score"] >= 0.6
    assert result["simulation_mode"] == "historical_heuristic"


def test_negative_simulation_with_unfavorable_history():
    result = simulate_recommendation_outcome(
        recommendation=_recommendation(confidence_score=0.7, priority=0.7),
        impact_decision=_impact_decision(-0.8),
        adaptive_decision=_adaptive_decision(risk_level="medium"),
        observability_snapshot={"signals": [SIGNAL_RECENT_REGRESSION], "has_data": True},
    )

    assert result["expected_outcome"] == "negative"
    assert result["expected_impact_score"] < -0.2
    assert "recent_regression" in result["warnings"]


def test_uncertain_simulation_when_evidence_is_missing():
    result = simulate_recommendation_outcome(
        recommendation=_recommendation(),
        impact_decision={},
        adaptive_decision=_adaptive_decision(),
        observability_snapshot={"signals": [], "has_data": False},
    )

    assert result["expected_outcome"] == "uncertain"
    assert "limited_historical_evidence" in result["warnings"]


def test_expected_impact_score_is_clamped():
    result = simulate_recommendation_outcome(
        recommendation=_recommendation(confidence_score=1.0, priority=1.0),
        impact_decision=_impact_decision(2.5),
        adaptive_decision=_adaptive_decision(confidence_adjustment=0.3),
        observability_snapshot={"signals": [], "has_data": True},
    )

    assert result["expected_impact_score"] == 1.0


def test_simulation_handles_missing_fields_defensively():
    result = simulate_recommendation_outcome(
        recommendation={},
        impact_decision={"conflict_summary": {"has_conflict": True}},
        adaptive_decision={"risk_level": "high"},
        observability_snapshot=None,
    )

    assert result["expected_outcome"] in {"uncertain", "negative", "neutral", "positive"}
    assert isinstance(result["drivers"], list)
    assert isinstance(result["warnings"], list)


# ===========================================================================
# Low sample prudence
# ===========================================================================


class TestLowSamplePrudence:
    def test_low_sample_reduces_confidence(self):
        """Low sample should push confidence below LOW_SAMPLE_CONFIDENCE_CAP."""
        result = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.5),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_LOW_SAMPLE_SIZE],
                "has_data": True,
            },
        )
        assert result["confidence_score"] <= LOW_SAMPLE_CONFIDENCE_CAP
        assert "low_sample_evidence" in result["warnings"]

    def test_low_sample_dampens_signal_adjustment(self):
        """Low sample should dampen the penalty from observability signals."""
        # Compare: low_sample with regression vs low_sample without regression
        # The regression penalty should be small (dampened) with low_sample
        result_low_with_reg = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.3),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_LOW_SAMPLE_SIZE, SIGNAL_RECENT_REGRESSION],
                "has_data": True,
            },
        )
        result_low_no_reg = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.3),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_LOW_SAMPLE_SIZE],
                "has_data": True,
            },
        )
        # The dampened regression penalty should be much smaller than the full -0.15
        dampened_penalty = result_low_no_reg["expected_impact_score"] - result_low_with_reg["expected_impact_score"]
        assert dampened_penalty < 0.15 * 0.5  # well below full penalty
        assert "low_sample_signal_dampened" in result_low_with_reg["drivers"]

    def test_low_sample_dampens_history_score(self):
        """Low sample should dampen historical evidence weight."""
        result_with_low = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.8),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_LOW_SAMPLE_SIZE],
                "has_data": True,
            },
        )
        result_without_low = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.8),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={"signals": [], "has_data": True},
        )
        # With low sample, the high history score should be dampened
        assert result_with_low["expected_impact_score"] < result_without_low["expected_impact_score"]
        assert "low_sample_history_dampened" in result_with_low["drivers"]

    def test_low_sample_does_not_overreact_to_negative(self):
        """Low sample + weak negative signals should NOT produce negative outcome."""
        result = simulate_recommendation_outcome(
            recommendation=_recommendation(confidence_score=0.85, priority=0.75),
            impact_decision=_impact_decision(
                -0.15, strong_enough=False, raw_total=1, memory_confidence=0.2,
            ),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_LOW_SAMPLE_SIZE, SIGNAL_DRIFT_DETECTED],
                "has_data": True,
            },
        )
        # Should NOT be negative — weak evidence + low sample => uncertain or neutral
        assert result["expected_outcome"] != "negative"

    def test_low_sample_constants_are_reasonable(self):
        assert 0 < LOW_SAMPLE_SIGNAL_DAMPEN < 1.0
        assert 0 < LOW_SAMPLE_CONFIDENCE_CAP < 1.0


# ===========================================================================
# Double penalization calibration
# ===========================================================================


class TestDoublePenalizationCalibration:
    def test_drift_does_not_over_penalize(self):
        """Drift should penalize but not catastrophically."""
        result_clean = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.3),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={"signals": [], "has_data": True},
        )
        result_drift = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.3),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_DRIFT_DETECTED],
                "has_data": True,
            },
        )
        score_drop = result_clean["expected_impact_score"] - result_drift["expected_impact_score"]
        risk_increase = result_drift["risk_score"] - result_clean["risk_score"]
        # Combined penalty should be meaningful but not extreme
        assert 0.05 < score_drop < 0.25
        assert 0.05 < risk_increase < 0.25

    def test_regression_penalizes_score_and_risk_moderately(self):
        """Regression impacts both paths but total penalty stays reasonable."""
        result = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.4),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_RECENT_REGRESSION],
                "has_data": True,
            },
        )
        # Should still be a valid score, not collapsed to extreme
        assert result["expected_impact_score"] > -0.5
        assert result["risk_score"] < 0.8

    def test_failure_rate_combined_penalty_is_bounded(self):
        """High failure rate penalty through both paths stays bounded."""
        result = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.2),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_HIGH_FAILURE_RATE],
                "has_data": True,
            },
        )
        assert result["risk_score"] < 0.7
        assert result["expected_impact_score"] > -0.5


# ===========================================================================
# has_data explicit handling
# ===========================================================================


class TestHasDataHandling:
    def test_no_observability_no_evidence_produces_uncertain(self):
        """has_data=False + no evidence => uncertain with appropriate warnings."""
        result = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision={},
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={"signals": [], "has_data": False},
        )
        assert result["expected_outcome"] == "uncertain"
        assert "limited_historical_evidence" in result["warnings"]
        assert "no_observability_data" in result["warnings"]
        assert result["confidence_score"] < 0.35

    def test_no_observability_with_evidence_does_not_over_penalize(self):
        """has_data=False but good evidence => signals don't add phantom penalties."""
        result = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.6),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={"signals": [], "has_data": False},
        )
        # Should still produce a reasonable positive result from evidence alone
        assert result["expected_impact_score"] > 0
        assert "no_observability_data" not in result["warnings"]

    def test_has_data_false_skips_signal_adjustment(self):
        """Even if signals are somehow present, has_data=False skips signal adj."""
        result_no_data = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.4),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_RECENT_REGRESSION],
                "has_data": False,
            },
        )
        result_with_data = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision=_impact_decision(0.4),
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={
                "signals": [SIGNAL_RECENT_REGRESSION],
                "has_data": True,
            },
        )
        # Without has_data, the regression signal should NOT penalize the score
        assert result_no_data["expected_impact_score"] > result_with_data["expected_impact_score"]

    def test_has_data_false_no_evidence_lowers_confidence(self):
        """No observability + no evidence produces low confidence."""
        result = simulate_recommendation_outcome(
            recommendation=_recommendation(),
            impact_decision={},
            adaptive_decision=_adaptive_decision(),
            observability_snapshot={"signals": [], "has_data": False},
        )
        # Low confidence from missing evidence + limited history penalties
        assert result["confidence_score"] < 0.25


# ===========================================================================
# Warnings and drivers
# ===========================================================================


def test_simulation_emits_warnings_for_drift_and_low_sample():
    result = simulate_recommendation_outcome(
        recommendation=_recommendation(),
        impact_decision=_impact_decision(0.15, strong_enough=False, raw_total=1, memory_confidence=0.2),
        adaptive_decision=_adaptive_decision(),
        observability_snapshot={
            "signals": [SIGNAL_DRIFT_DETECTED, SIGNAL_LOW_SAMPLE_SIZE],
            "has_data": True,
        },
    )

    assert "drift_detected" in result["warnings"]
    assert "low_sample_evidence" in result["warnings"]
