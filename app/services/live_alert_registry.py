from __future__ import annotations

ALERT_METRIC_REGISTRY: dict[str, dict[str, object]] = {
    "resolution_drop": {
        "scope": "global",
        "baseline_metrics": ["resolution_rate"],
        "drift_metrics": ["resolution_rate"],
    },
    "excessive_clarification": {
        "scope": "global",
        "baseline_metrics": ["clarification_ratio"],
        "drift_metrics": ["clarification_ratio"],
    },
    "loop_risk": {
        "scope": "global",
        "baseline_metrics": ["loop_rate"],
        "drift_metrics": ["loop_rate"],
    },
    "spike_in_protective_mode": {
        "scope": "global",
        "baseline_metrics": ["protective_mode_ratio"],
        "drift_metrics": ["protective_mode_ratio"],
    },
    "low_confidence_cluster": {
        "scope": "global",
        "baseline_metrics": ["low_confidence_ratio"],
        "drift_metrics": ["low_confidence_ratio"],
    },
    "auto_healing_hardening_event": {
        "scope": "global",
        "baseline_metrics": ["hardening_rate"],
        "drift_metrics": ["hardening_rate"],
    },
    "repeated_hardening": {
        "scope": "global",
        "baseline_metrics": ["hardening_rate"],
        "drift_metrics": ["hardening_rate"],
    },
    "family_specific_degradation": {
        "scope": "family",
        "baseline_metrics": ["family_avg_score", "family_regressed_ratio"],
        "drift_metrics": ["family_avg_score", "family_regressed_ratio"],
    },
    "signature_specific_regression": {
        "scope": "signature",
        "baseline_metrics": ["signature_avg_score", "signature_regressed_ratio"],
        "drift_metrics": ["signature_avg_score", "signature_regressed_ratio"],
    },
}
