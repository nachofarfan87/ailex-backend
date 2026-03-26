from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.chat_logger import sanitize_for_logging


@dataclass
class BetaObservabilitySnapshot:
    event_type: str = "beta_observability_snapshot"
    timestamp: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    query: str | None = None
    normalized_query: str | None = None
    jurisdiction: str | None = None
    forum: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    original_action_slug: str | None = None
    final_action_slug: str | None = None
    original_case_domain: str | None = None
    final_case_domain: str | None = None
    slug_aligned_to_domain: bool | None = None
    domain_override_applied: bool | None = None
    selected_model: str | None = None
    selected_template: str | None = None
    strategy_mode: str | None = None
    dominant_factor: str | None = None
    final_confidence: float | None = None
    protective_mode_active: bool | None = None
    safety_status: str | None = None
    review_queue_flag: bool | None = None
    internal_warnings: list[str] = field(default_factory=list)
    hallucination_flags: list[str] = field(default_factory=list)
    hallucination_guard_status: str | None = None
    citation_validation_status: str | None = None
    fallback_detected: bool | None = None
    sanitized_output: bool | None = None
    secondary_domains: list[str] = field(default_factory=list)
    had_secondary_domains: bool | None = None
    had_interdomain_conflict: bool | None = None
    response_status: str | None = None
    top_level_domains_detected: list[str] = field(default_factory=list)
    learning_action: str | None = None
    hard_safety_intervention: bool | None = None
    human_intervention: bool | None = None
    total_duration_ms: int | None = None
    stage_durations_ms: dict[str, int] = field(default_factory=dict)
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_for_logging(asdict(self))
