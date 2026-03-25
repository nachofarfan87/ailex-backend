from __future__ import annotations

from typing import Any

from app.services.observability_signal_extractor import (
    SIGNAL_DRIFT_DETECTED,
    SIGNAL_HIGH_FAILURE_RATE,
    SIGNAL_RECENT_REGRESSION,
    SIGNAL_UNSTABLE_PATTERN,
)


def resolve_change_budget(
    *,
    observability_snapshot: dict[str, Any] | None,
    recommendation_count: int | None = None,
    candidate_apply_count: int | None = None,
) -> dict[str, Any]:
    observability_snapshot = observability_snapshot or {}
    signals = {
        str(signal or "").strip()
        for signal in (observability_snapshot.get("signals") or [])
        if str(signal or "").strip()
    }

    mode = "normal"
    max_changes = 3
    max_high_risk_changes = 1
    reasoning = "Normal mode: sin senales criticas activas."

    if SIGNAL_RECENT_REGRESSION in signals or SIGNAL_HIGH_FAILURE_RATE in signals:
        mode = "protective"
        max_changes = 1
        max_high_risk_changes = 0
        reasoning = "Protective mode: regression reciente o failure rate alta."
    elif SIGNAL_DRIFT_DETECTED in signals or SIGNAL_UNSTABLE_PATTERN in signals:
        mode = "restricted"
        max_changes = 2
        max_high_risk_changes = 0
        reasoning = "Restricted mode: drift o patron inestable detectado."
    elif not observability_snapshot.get("has_data", False):
        reasoning = "Normal mode por fallback seguro: sin observabilidad suficiente."

    effective_count = candidate_apply_count
    if effective_count is None:
        effective_count = recommendation_count

    if effective_count is not None and effective_count >= 0:
        max_changes = min(max_changes, max(0, int(effective_count)))
        max_high_risk_changes = min(max_high_risk_changes, max_changes)
        reasoning = f"{reasoning} candidate_apply_count={int(effective_count)}"

    return {
        "max_changes": max_changes,
        "max_high_risk_changes": max_high_risk_changes,
        "mode": mode,
        "reasoning": reasoning,
    }
