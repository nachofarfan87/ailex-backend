from __future__ import annotations

from typing import Any

from app.services import learning_runtime_config
from app.services.learning_runtime_config_store import save_runtime_config


class LearningActionResult:
    def __init__(self, applied: bool, reason: str, details: dict | None = None):
        self.applied = applied
        self.reason = reason
        self.details = details or {}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def apply_recommendation(db, recommendation: dict) -> LearningActionResult:
    # Transaction contract:
    # - this service never commits
    # - it must run inside an outer transactional learning cycle
    # - callers are responsible for commit / rollback boundaries
    if db is None:
        raise ValueError("db_session_required")

    event_type = str(recommendation.get("event_type") or "").strip()
    proposed_changes = _as_dict(recommendation.get("proposed_changes"))

    if event_type == "domain_override":
        added_domains: list[str] = []
        for domain in proposed_changes.get("prefer_hybrid_domains_add", []) or []:
            normalized = str(domain or "").strip().lower()
            if normalized:
                learning_runtime_config.add_prefer_hybrid_domain(normalized)
                added_domains.append(normalized)
        for domain in proposed_changes.get("force_full_pipeline_domains_add", []) or []:
            normalized = str(domain or "").strip().lower()
            if normalized:
                learning_runtime_config.add_force_full_pipeline_domain(normalized)
                added_domains.append(normalized)
        if not added_domains:
            return LearningActionResult(False, "no_runtime_change")
        runtime_config = learning_runtime_config.get_effective_runtime_config()
        save_runtime_config(db, runtime_config)
        return LearningActionResult(
            True,
            "applied_domain_override",
            {
                "added_domains": added_domains,
                "runtime_config": runtime_config,
            },
        )

    if event_type == "threshold_adjustment":
        threshold_review = _as_dict(proposed_changes.get("threshold_review"))
        applied_thresholds: dict[str, float] = {}
        for source_key, target_key in (
            ("low_confidence_threshold", "low_confidence"),
            ("low_decision_confidence_threshold", "low_decision_confidence"),
        ):
            if source_key in threshold_review:
                value = float(threshold_review[source_key])
                learning_runtime_config.update_threshold(target_key, value)
                applied_thresholds[target_key] = value
        if not applied_thresholds:
            return LearningActionResult(False, "no_runtime_change")
        runtime_config = learning_runtime_config.get_effective_runtime_config()
        save_runtime_config(db, runtime_config)
        return LearningActionResult(
            True,
            "applied_threshold_adjustment",
            {
                "updated_thresholds": applied_thresholds,
                "runtime_config": runtime_config,
            },
        )

    if event_type == "classification_review":
        return LearningActionResult(False, "requires_manual_review")
    if event_type == "strategy_recalibration":
        return LearningActionResult(False, "requires_manual_review")
    if event_type == "version_alert":
        return LearningActionResult(False, "requires_manual_review")
    return LearningActionResult(False, "unsupported_event_type")
