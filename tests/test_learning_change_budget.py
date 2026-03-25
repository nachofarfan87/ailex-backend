from __future__ import annotations

from app.services.learning_change_budget import resolve_change_budget
from app.services.observability_signal_extractor import (
    SIGNAL_DRIFT_DETECTED,
    SIGNAL_HIGH_FAILURE_RATE,
    SIGNAL_RECENT_REGRESSION,
)


def test_budget_normal_mode():
    result = resolve_change_budget(
        observability_snapshot={"signals": [], "has_data": True},
        recommendation_count=5,
    )

    assert result["mode"] == "normal"
    assert result["max_changes"] == 3
    assert result["max_high_risk_changes"] == 1


def test_budget_restricted_mode_with_drift():
    result = resolve_change_budget(
        observability_snapshot={"signals": [SIGNAL_DRIFT_DETECTED], "has_data": True},
        recommendation_count=5,
    )

    assert result["mode"] == "restricted"
    assert result["max_changes"] == 2
    assert result["max_high_risk_changes"] == 0


def test_budget_protective_mode_with_regression():
    result = resolve_change_budget(
        observability_snapshot={"signals": [SIGNAL_RECENT_REGRESSION, SIGNAL_HIGH_FAILURE_RATE], "has_data": True},
        recommendation_count=5,
    )

    assert result["mode"] == "protective"
    assert result["max_changes"] == 1
    assert result["max_high_risk_changes"] == 0


def test_budget_fallback_without_data():
    result = resolve_change_budget(
        observability_snapshot={"signals": [], "has_data": False},
        recommendation_count=2,
    )

    assert result["mode"] == "normal"
    assert result["max_changes"] == 2
    assert result["max_high_risk_changes"] == 1


def test_budget_uses_candidate_apply_count_over_raw_recommendation_count():
    result = resolve_change_budget(
        observability_snapshot={"signals": [], "has_data": True},
        recommendation_count=10,
        candidate_apply_count=2,
    )

    assert result["max_changes"] == 2
    assert "candidate_apply_count=2" in result["reasoning"]
