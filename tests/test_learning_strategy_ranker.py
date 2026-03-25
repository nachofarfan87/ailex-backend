from __future__ import annotations

from app.services.learning_strategy_ranker import rank_recommendations


def _item(
    *,
    expected_impact_score: float,
    simulation_confidence: float,
    risk_score: float,
    expected_outcome: str = "neutral",
    decision_class: str = "apply",
    confidence_score: float = 0.8,
    priority: float = 0.8,
) -> dict:
    return {
        "recommendation": {
            "event_type": "domain_override",
            "confidence_score": confidence_score,
            "priority": priority,
        },
        "simulation_result": {
            "expected_outcome": expected_outcome,
            "expected_impact_score": expected_impact_score,
            "confidence_score": simulation_confidence,
        },
        "operational_risk": {
            "risk_score": risk_score,
            "risk_level": "high" if risk_score >= 0.7 else "low",
        },
        "final_learning_decision": {
            "decision_class": decision_class,
            "should_apply": decision_class == "apply",
        },
    }


def test_orders_by_ranking_score():
    ranked = rank_recommendations(
        [
            _item(expected_impact_score=0.2, simulation_confidence=0.6, risk_score=0.2),
            _item(expected_impact_score=0.7, simulation_confidence=0.8, risk_score=0.1),
        ]
    )

    assert ranked[0]["ranking_score"] > ranked[1]["ranking_score"]
    assert ranked[0]["rank_position"] == 1


def test_high_risk_is_penalized():
    ranked = rank_recommendations(
        [
            _item(expected_impact_score=0.4, simulation_confidence=0.8, risk_score=0.8),
            _item(expected_impact_score=0.4, simulation_confidence=0.8, risk_score=0.1),
        ]
    )

    assert ranked[0]["operational_risk"]["risk_score"] == 0.1


def test_high_risk_level_penalizes_more_than_medium_with_same_score():
    ranked = rank_recommendations(
        [
            _item(expected_impact_score=0.4, simulation_confidence=0.8, risk_score=0.3),
            {
                **_item(expected_impact_score=0.4, simulation_confidence=0.8, risk_score=0.3),
                "operational_risk": {"risk_score": 0.3, "risk_level": "medium"},
            },
            {
                **_item(expected_impact_score=0.4, simulation_confidence=0.8, risk_score=0.3),
                "operational_risk": {"risk_score": 0.3, "risk_level": "high"},
            },
        ]
    )

    assert ranked[0]["operational_risk"]["risk_level"] == "low"
    assert ranked[-1]["operational_risk"]["risk_level"] == "high"


def test_positive_outcome_gets_boost():
    ranked = rank_recommendations(
        [
            _item(expected_impact_score=0.3, simulation_confidence=0.7, risk_score=0.1, expected_outcome="neutral"),
            _item(expected_impact_score=0.3, simulation_confidence=0.7, risk_score=0.1, expected_outcome="positive"),
        ]
    )

    assert ranked[0]["simulation_result"]["expected_outcome"] == "positive"


def test_negative_outcome_moves_to_bottom():
    ranked = rank_recommendations(
        [
            _item(expected_impact_score=-0.2, simulation_confidence=0.8, risk_score=0.1, expected_outcome="negative"),
            _item(expected_impact_score=0.1, simulation_confidence=0.4, risk_score=0.2, expected_outcome="neutral"),
        ]
    )

    assert ranked[-1]["simulation_result"]["expected_outcome"] == "negative"


def test_defer_is_penalized_vs_apply():
    ranked = rank_recommendations(
        [
            _item(expected_impact_score=0.25, simulation_confidence=0.7, risk_score=0.1, decision_class="defer"),
            _item(expected_impact_score=0.25, simulation_confidence=0.7, risk_score=0.1, decision_class="apply"),
        ]
    )

    assert ranked[0]["final_learning_decision"]["decision_class"] == "apply"


def test_skip_stays_at_bottom_without_destructive_penalty():
    ranked = rank_recommendations(
        [
            _item(expected_impact_score=0.15, simulation_confidence=0.5, risk_score=0.1, decision_class="skip"),
            _item(expected_impact_score=0.10, simulation_confidence=0.45, risk_score=0.1, decision_class="apply"),
        ]
    )

    assert ranked[-1]["final_learning_decision"]["decision_class"] == "skip"
    assert ranked[-1]["ranking_score"] > -1.0
