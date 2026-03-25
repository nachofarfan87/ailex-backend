from __future__ import annotations

from app.services.self_tuning_meta_policy import build_meta_signals, evaluate_meta_policy


def _strategy_memory(
    *,
    parameter_performance: dict | None = None,
    mode_performance: dict | None = None,
    history_window_summary: dict | None = None,
    meta_confidence: float = 0.78,
) -> dict:
    return {
        "parameter_performance": parameter_performance or {},
        "mode_performance": mode_performance or {},
        "context_performance": {},
        "history_window_summary": history_window_summary
        or {
            "total_cycles": 8,
            "weighted_total_cycles": 8.0,
            "known_outcomes": 6,
            "weighted_known_outcomes": 6.0,
            "unknown_outcome_rate": 0.2,
            "weighted_unknown_outcome_rate": 0.2,
            "rollback_after_tuning_rate": 0.05,
            "weighted_rollback_rate": 0.05,
            "weighted_failure_rate": 0.2,
            "high_confidence_bad_outcome_rate": 0.0,
            "context_weight_distribution": {
                "stable": 6.0,
                "fragile": 1.0,
                "rollback_pressure": 1.0,
                "drift_context": 0.0,
                "low_evidence_context": 0.0,
            },
        },
        "meta_confidence": meta_confidence,
        "meta_confidence_reasoning": ["meta_confidence_level=high" if meta_confidence >= 0.65 else "meta_confidence_level=low"],
        "meta_confidence_components": {
            "evidence_component": 0.3 if meta_confidence >= 0.65 else 0.05,
            "stability_component": 0.12 if meta_confidence >= 0.65 else 0.02,
            "uncertainty_penalty": 0.05 if meta_confidence >= 0.65 else 0.2,
            "rollback_penalty": 0.02 if meta_confidence >= 0.65 else 0.1,
        },
    }


def _recommendation() -> dict:
    return {
        "candidate_adjustments": [
            {
                "parameter_name": "apply_confidence_delta",
                "direction": "decrease",
                "blocked": False,
                "priority_score": 0.8,
                "confidence": 0.82,
            }
        ]
    }


def _signals(**overrides) -> dict:
    payload = {
        "trend_stability": 0.82,
        "consistency": 0.84,
        "sample_size": 64,
        "rollback_ratio": 0.0,
        "drift_level": "none",
    }
    payload.update(overrides)
    return payload


def test_parameter_with_effective_history_improves_meta_score():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            parameter_performance={
                "apply_confidence_delta": {
                    "total_records": 4,
                    "known_outcomes": 3,
                    "success_rate": 0.8,
                    "weighted_success_rate": 0.85,
                    "failure_rate": 0.2,
                    "weighted_failure_rate": 0.15,
                    "rollback_after_tuning_rate": 0.0,
                    "weighted_rollback_rate": 0.0,
                    "unknown_outcome_rate": 0.25,
                    "weighted_unknown_outcome_rate": 0.1,
                }
            }
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(),
        requested_mode="balanced",
    )

    assessment = meta_signals["parameter_assessments"]["apply_confidence_delta"]
    assert assessment["meta_score"] > 0
    assert assessment["label"] == "supportive"


def test_parameter_with_ineffective_history_is_penalized():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            parameter_performance={
                "apply_confidence_delta": {
                    "total_records": 4,
                    "known_outcomes": 3,
                    "success_rate": 0.2,
                    "weighted_success_rate": 0.15,
                    "failure_rate": 0.8,
                    "weighted_failure_rate": 0.85,
                    "rollback_after_tuning_rate": 0.35,
                    "weighted_rollback_rate": 0.4,
                    "unknown_outcome_rate": 0.25,
                    "weighted_unknown_outcome_rate": 0.2,
                }
            }
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(),
        requested_mode="balanced",
    )

    assessment = meta_signals["parameter_assessments"]["apply_confidence_delta"]
    assert assessment["meta_score"] < 0
    assert assessment["block_parameter"] is True


def test_aggressive_mode_with_bad_history_recommends_conservative_or_balanced():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            mode_performance={
                "aggressive": {
                    "mode": "aggressive",
                    "total_cycles": 7,
                    "known_outcomes": 5,
                    "success_rate": 0.2,
                    "weighted_success_rate": 0.18,
                    "failure_rate": 0.8,
                    "weighted_failure_rate": 0.82,
                    "rollback_after_tuning_rate": 0.3,
                    "weighted_rollback_rate": 0.32,
                    "unknown_outcome_rate": 0.1,
                    "weighted_unknown_outcome_rate": 0.1,
                    "evidence_status": "sufficient_mode_evidence",
                }
            }
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(),
        requested_mode="aggressive",
    )

    decision = evaluate_meta_policy(meta_signals=meta_signals, dry_run=False)

    assert decision["recommended_mode"] in {"balanced", "conservative"}
    assert decision["recommended_action"] in {"simulate", "observe_only", "block"}


def test_unknown_outcomes_are_not_treated_as_success():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            parameter_performance={
                "apply_confidence_delta": {
                    "total_records": 5,
                    "known_outcomes": 0,
                    "success_rate": 0.0,
                    "failure_rate": 0.0,
                    "rollback_after_tuning_rate": 0.0,
                    "unknown_outcome_rate": 1.0,
                    "weighted_unknown_outcome_rate": 1.0,
                }
            }
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(),
        requested_mode="balanced",
    )

    assessment = meta_signals["parameter_assessments"]["apply_confidence_delta"]
    assert assessment["label"] != "supportive"
    assert assessment["success_rate"] == 0.0


def test_meta_policy_can_return_observe_only():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            parameter_performance={
                "apply_confidence_delta": {
                    "total_records": 4,
                    "known_outcomes": 3,
                    "success_rate": 0.1,
                    "weighted_success_rate": 0.1,
                    "failure_rate": 0.9,
                    "weighted_failure_rate": 0.9,
                    "rollback_after_tuning_rate": 0.1,
                    "weighted_rollback_rate": 0.1,
                    "unknown_outcome_rate": 0.25,
                    "weighted_unknown_outcome_rate": 0.25,
                }
            },
            history_window_summary={
                "total_cycles": 8,
                "weighted_total_cycles": 8.0,
                "known_outcomes": 5,
                "weighted_known_outcomes": 5.0,
                "unknown_outcome_rate": 0.2,
                "weighted_unknown_outcome_rate": 0.2,
                "rollback_after_tuning_rate": 0.1,
                "weighted_rollback_rate": 0.1,
                "weighted_failure_rate": 0.2,
                "high_confidence_bad_outcome_rate": 0.0,
                "context_weight_distribution": {"stable": 8.0},
            },
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(),
        requested_mode="balanced",
    )

    decision = evaluate_meta_policy(meta_signals=meta_signals, dry_run=False)

    assert decision["recommended_action"] == "observe_only"


def test_meta_policy_can_degrade_apply_to_simulate():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            history_window_summary={
                "total_cycles": 8,
                "weighted_total_cycles": 8.0,
                "known_outcomes": 5,
                "weighted_known_outcomes": 5.0,
                "unknown_outcome_rate": 0.7,
                "weighted_unknown_outcome_rate": 0.7,
                "rollback_after_tuning_rate": 0.05,
                "weighted_rollback_rate": 0.05,
                "weighted_failure_rate": 0.2,
                "high_confidence_bad_outcome_rate": 0.3,
                "context_weight_distribution": {"stable": 8.0},
            }
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(),
        requested_mode="balanced",
    )

    decision = evaluate_meta_policy(meta_signals=meta_signals, dry_run=False)

    assert decision["recommended_action"] == "simulate"


def test_insufficient_meta_evidence_stays_prudent():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            history_window_summary={
                "total_cycles": 1,
                "weighted_total_cycles": 1.0,
                "known_outcomes": 0,
                "weighted_known_outcomes": 0.0,
                "unknown_outcome_rate": 1.0,
                "weighted_unknown_outcome_rate": 1.0,
                "rollback_after_tuning_rate": 0.0,
                "weighted_rollback_rate": 0.0,
                "weighted_failure_rate": 0.0,
                "high_confidence_bad_outcome_rate": 0.0,
                "context_weight_distribution": {"stable": 1.0},
            }
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(),
        requested_mode="aggressive",
    )

    decision = evaluate_meta_policy(meta_signals=meta_signals, dry_run=False)

    assert decision["recommended_action"] == "simulate"
    assert decision["recommended_mode"] != "aggressive"


def test_low_meta_confidence_degrades_to_simulate_or_observe():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            meta_confidence=0.22,
            history_window_summary={
                "total_cycles": 3,
                "weighted_total_cycles": 2.0,
                "known_outcomes": 1,
                "weighted_known_outcomes": 0.8,
                "unknown_outcome_rate": 0.8,
                "weighted_unknown_outcome_rate": 0.8,
                "rollback_after_tuning_rate": 0.0,
                "weighted_rollback_rate": 0.0,
                "weighted_failure_rate": 0.2,
                "high_confidence_bad_outcome_rate": 0.0,
                "context_weight_distribution": {"fragile": 2.0},
            },
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(trend_stability=0.4, consistency=0.45),
        requested_mode="balanced",
    )

    decision = evaluate_meta_policy(meta_signals=meta_signals, dry_run=False)

    assert decision["meta_status"] == "low_meta_confidence"
    assert decision["recommended_action"] in {"simulate", "observe_only"}


def test_high_meta_confidence_allows_prudent_support():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(meta_confidence=0.84),
        current_recommendation=_recommendation(),
        current_signals=_signals(),
        requested_mode="balanced",
    )

    decision = evaluate_meta_policy(meta_signals=meta_signals, dry_run=False)

    assert decision["meta_status"] in {"supported", "cautious_support"}
    assert decision["recommended_mode"] in {"balanced", "conservative"}


def test_context_with_insufficient_evidence_does_not_block_by_itself():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            parameter_performance={
                "apply_confidence_delta": {
                    "total_records": 4,
                    "known_outcomes": 3,
                    "weighted_success_rate": 0.72,
                    "weighted_failure_rate": 0.12,
                    "weighted_rollback_rate": 0.0,
                    "weighted_unknown_outcome_rate": 0.2,
                    "context_performance": {
                        "fragile": {
                            "weighted_success_rate": 0.0,
                            "weighted_failure_rate": 1.0,
                            "context_meta_score": -0.8,
                            "evidence_status": "insufficient_context_evidence",
                        }
                    },
                }
            }
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(trend_stability=0.45, consistency=0.45),
        requested_mode="balanced",
    )

    assessment = meta_signals["parameter_assessments"]["apply_confidence_delta"]
    assert assessment["contextual_evidence_status"] == "insufficient_context_evidence"
    assert assessment["block_parameter"] is False


def test_context_with_strong_bad_evidence_penalizes_parameter():
    meta_signals = build_meta_signals(
        strategy_memory=_strategy_memory(
            parameter_performance={
                "apply_confidence_delta": {
                    "total_records": 5,
                    "known_outcomes": 4,
                    "weighted_success_rate": 0.55,
                    "weighted_failure_rate": 0.35,
                    "weighted_rollback_rate": 0.0,
                    "weighted_unknown_outcome_rate": 0.1,
                    "context_performance": {
                        "fragile": {
                            "weighted_success_rate": 0.1,
                            "weighted_failure_rate": 0.75,
                            "context_meta_score": -0.5,
                            "evidence_status": "sufficient_context_evidence",
                        }
                    },
                }
            }
        ),
        current_recommendation=_recommendation(),
        current_signals=_signals(trend_stability=0.42, consistency=0.44),
        requested_mode="balanced",
    )

    assessment = meta_signals["parameter_assessments"]["apply_confidence_delta"]
    assert assessment["contextual_evidence_status"] == "sufficient_context_evidence"
    assert assessment["block_parameter"] is True
