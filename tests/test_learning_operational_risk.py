from __future__ import annotations

from app.services.learning_operational_risk import evaluate_operational_risk


def test_low_risk_for_reversible_localized_change():
    result = evaluate_operational_risk(
        {
            "event_type": "domain_override",
            "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
        }
    )

    assert result["risk_level"] == "low"
    assert result["blast_radius"] == "small"
    assert result["reversible"] is True


def test_medium_risk_for_moderately_broad_change():
    result = evaluate_operational_risk(
        {
            "event_type": "domain_override",
            "proposed_changes": {
                "prefer_hybrid_domains_add": ["alimentos", "familia"],
                "force_full_pipeline_domains_add": ["civil"],
            },
        }
    )

    assert result["risk_level"] == "medium"
    assert result["blast_radius"] == "medium"


def test_high_risk_for_sensitive_global_threshold_change():
    result = evaluate_operational_risk(
        {
            "event_type": "threshold_adjustment",
            "proposed_changes": {
                "threshold_review": {
                    "low_confidence_threshold": 0.55,
                    "low_decision_confidence_threshold": 0.65,
                    "global_default": True,
                }
            },
        }
    )

    assert result["risk_level"] == "high"
    assert result["blast_radius"] == "large"
    assert result["reversible"] is False


def test_operational_risk_fallback_with_incomplete_recommendation():
    result = evaluate_operational_risk({"event_type": "domain_override"})

    assert result["risk_level"] == "medium"
    assert result["blast_radius"] == "medium"
    assert "missing_proposed_changes" in result["drivers"]
