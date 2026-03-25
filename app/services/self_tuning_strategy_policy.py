from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.services.self_tuning_constants import SELF_TUNING_SAFETY_LIMITS, TUNABLE_PARAMETER_SPECS
from app.services.self_tuning_strategy_constants import (
    DEFAULT_SELF_TUNING_STRATEGY_PROFILE,
    SELF_TUNING_STRATEGY_PROFILES,
    STRATEGY_FLOAT_MAX_STEP_RATIO,
    STRATEGY_FLOAT_MIN_RESOLUTION_RATIO,
    STRATEGY_CONTROL_ALLOWLIST,
    STRATEGY_HYSTERESIS_WINDOW,
    STRATEGY_INT_MIN_RESOLUTION,
    STRATEGY_MAX_COOLDOWN_HOURS,
    STRATEGY_MIN_COOLDOWN_HOURS,
    STRATEGY_PROFILE_ORDER,
    STRATEGY_RELAXATION_MIN_META_CONFIDENCE,
)
from app.services.utc import utc_now


def build_strategy_recommendation(
    *,
    recommendation: dict[str, Any],
    meta_snapshot: dict[str, Any],
    current_signals: dict[str, Any],
    tuning_history: list[dict[str, Any]],
    strategy_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates = list(recommendation.get("candidate_adjustments") or [])
    actionable = [candidate for candidate in candidates if not candidate.get("blocked")]
    meta_confidence = float(meta_snapshot.get("meta_confidence") or 0.0)
    meta_action = str(meta_snapshot.get("recommended_action") or "observe_only")
    current_context = str(meta_snapshot.get("meta_signals", {}).get("current_context") or "stable")
    history_summary = dict(meta_snapshot.get("history_window_summary") or {})
    meta_risk_flags = list(meta_snapshot.get("meta_risk_flags") or [])
    risky_parameters = set(meta_snapshot.get("historical_support", {}).get("risky_parameters") or [])
    supportive_parameters = set(meta_snapshot.get("historical_support", {}).get("supportive_parameters") or [])
    weighted_unknown = float(history_summary.get("weighted_unknown_outcome_rate") or 0.0)
    rollback_ratio = float(current_signals.get("rollback_ratio") or 0.0)
    mode_support = dict(meta_snapshot.get("historical_support", {}).get("mode_support") or {})
    mode_evidence_status = str(mode_support.get("requested_mode_evidence_status") or "insufficient_mode_evidence")

    strategy_risk_flags: list[str] = []
    strategy_reasoning: list[str] = []
    support_level = "partial"
    base_profile = DEFAULT_SELF_TUNING_STRATEGY_PROFILE

    if meta_action in {"block", "observe_only"} or not actionable:
        base_profile = "observe_only_strategy"
        strategy_reasoning.append("meta-policy already requires observe-only or block semantics")
        support_level = "minimal"
    elif (
        "rollback_pressure" in recommendation.get("risk_flags", [])
        or "meta_rollback_after_tuning_pressure" in meta_risk_flags
        or current_context in {"rollback_pressure", "drift_context"}
        or rollback_ratio >= 0.08
    ):
        base_profile = "restricted_adjustment"
        strategy_risk_flags.append("strategy_restricted_due_to_risk_context")
        strategy_reasoning.append("contexto riesgoso o rollback pressure: strategy restringida")
        support_level = "low"
    elif (
        current_context in {"fragile", "low_evidence_context"}
        or meta_confidence < 0.55
        or weighted_unknown >= 0.45
        or meta_action == "simulate"
        or mode_evidence_status == "insufficient_mode_evidence"
    ):
        base_profile = DEFAULT_SELF_TUNING_STRATEGY_PROFILE
        strategy_risk_flags.append("strategy_micro_adjustment_preferred")
        strategy_reasoning.append("contexto fragil, evidencia limitada o confianza parcial: micro_adjustment")
        support_level = "medium"
    elif (
        current_context == "stable"
        and meta_confidence >= 0.8
        and meta_action == "apply"
        and not risky_parameters
        and bool(supportive_parameters)
        and mode_evidence_status == "sufficient_mode_evidence"
    ):
        base_profile = "standard_adjustment"
        strategy_reasoning.append("contexto estable y soporte meta alto: strategy standard")
        support_level = "high"
    else:
        base_profile = DEFAULT_SELF_TUNING_STRATEGY_PROFILE
        strategy_reasoning.append("ante duda se prioriza micro_adjustment")
        support_level = "medium"

    profile, hysteresis_trace = _apply_strategy_hysteresis(
        base_profile=base_profile,
        strategy_history=list(strategy_history or []),
        meta_confidence=meta_confidence,
        current_context=current_context,
    )
    if hysteresis_trace["strategy_hysteresis_applied"]:
        strategy_risk_flags.append("strategy_hysteresis_applied")
        strategy_reasoning.append(str(hysteresis_trace["strategy_transition_reason"]))

    controls = _build_strategy_controls(
        profile=profile,
        meta_confidence=meta_confidence,
        current_context=current_context,
        actionable_count=len(actionable),
    )
    adapted_candidates = _apply_strategy_to_candidates(
        candidates=candidates,
        controls=controls,
        tuning_history=tuning_history,
        risky_parameters=risky_parameters,
        supportive_parameters=supportive_parameters,
    )
    final_action = _resolve_strategy_action(
        base_action=meta_action,
        profile=profile,
        meta_confidence=meta_confidence,
        history_summary=history_summary,
        current_context=current_context,
        rollback_ratio=rollback_ratio,
    )
    strategy_override_applied = (
        final_action != meta_action
        or profile != "standard_adjustment"
        or controls["effective_max_adjustments"] < max(len(actionable), 1)
    )
    return {
        "strategy_profile": profile,
        "strategy_reasoning": strategy_reasoning,
        "strategy_controls": controls,
        "strategy_risk_flags": list(dict.fromkeys(strategy_risk_flags)),
        "strategy_override_applied": strategy_override_applied,
        "strategy_support_level": support_level,
        "recommended_action": final_action,
        "adapted_candidates": adapted_candidates,
        "base_strategy_profile": base_profile,
        "final_strategy_profile": profile,
        "strategy_transition_reason": hysteresis_trace["strategy_transition_reason"],
        "strategy_hysteresis_applied": hysteresis_trace["strategy_hysteresis_applied"],
        "strategy_hysteresis_state": hysteresis_trace,
    }


def _build_strategy_controls(
    *,
    profile: str,
    meta_confidence: float,
    current_context: str,
    actionable_count: int,
) -> dict[str, Any]:
    base_controls = dict(SELF_TUNING_STRATEGY_PROFILES[profile])
    controls: dict[str, Any] = {
        key: value for key, value in base_controls.items() if key in STRATEGY_CONTROL_ALLOWLIST
    }
    if current_context in {"fragile", "low_evidence_context"} and profile != "observe_only_strategy":
        controls["effective_cooldown_multiplier"] = round(float(controls["effective_cooldown_multiplier"]) + 0.25, 4)
        controls["effective_step_multiplier"] = round(float(controls["effective_step_multiplier"]) * 0.9, 4)
    if meta_confidence < 0.5 and profile != "observe_only_strategy":
        controls["effective_confidence_floor"] = round(max(float(controls["effective_confidence_floor"]), 0.76), 4)
    controls["effective_max_adjustments"] = min(int(controls["effective_max_adjustments"]), max(actionable_count, 0))
    return controls


def _apply_strategy_to_candidates(
    *,
    candidates: list[dict[str, Any]],
    controls: dict[str, Any],
    tuning_history: list[dict[str, Any]],
    risky_parameters: set[str],
    supportive_parameters: set[str],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    max_delta_budget = float(SELF_TUNING_SAFETY_LIMITS["max_total_delta_per_cycle"]) * float(controls["effective_budget_multiplier"])
    max_adjustments = int(controls["effective_max_adjustments"])
    confidence_floor = float(controls["effective_confidence_floor"])
    total_delta = 0.0

    for candidate in candidates:
        item = dict(candidate)
        if item.get("blocked"):
            item["strategy_controls"] = {}
            prepared.append(item)
            continue

        parameter_name = str(item.get("parameter_name") or "")
        param_controls = _resolve_parameter_strategy_controls(
            parameter_name=parameter_name,
            base_controls=controls,
            risky_parameters=risky_parameters,
            supportive_parameters=supportive_parameters,
        )
        delta_trace = _resolve_effective_delta(item=item, param_controls=param_controls)
        cooldown_trace = _resolve_effective_cooldown(
            parameter_name=parameter_name,
            tuning_history=tuning_history,
            cooldown_multiplier=float(param_controls["effective_cooldown_multiplier"]),
        )
        item["strategy_controls"] = {
            **param_controls,
            "effective_cooldown_hours": cooldown_trace["effective_cooldown_hours"],
            "cooldown_clamped": cooldown_trace["cooldown_clamped"],
            "strategy_cooldown_reason": cooldown_trace["strategy_cooldown_reason"],
            "effective_step_resolution": delta_trace["effective_step_resolution"],
        }
        item["strategy_delta_trace"] = delta_trace
        item["strategy_effective_delta"] = delta_trace["effective_delta"]
        item["strategy_effective_proposed_value"] = _resolve_effective_proposed_value(
            item=item,
            effective_delta=delta_trace["effective_delta"],
        )
        item["strategy_priority_score"] = round(
            float(item.get("priority_score") or 0.0) * float(param_controls["effective_priority_multiplier"]),
            4,
        )
        item["priority_contribution_breakdown"] = {
            "base_priority_score": round(float(item.get("priority_score") or 0.0), 4),
            "effective_priority_multiplier": round(float(param_controls["effective_priority_multiplier"]), 4),
            "watch_mode": bool(param_controls.get("watch_mode", False)),
            "meta_priority_score": round(float(item.get("meta_priority_score") or item.get("priority_score") or 0.0), 4),
            "strategy_priority_score": round(float(item["strategy_priority_score"] or 0.0), 4),
        }
        prepared.append(item)

    prepared.sort(
        key=lambda item: (
            item.get("blocked", False),
            -float(item.get("strategy_priority_score") or item.get("priority_score") or 0.0),
            -float(item.get("meta_priority_score") or item.get("priority_score") or 0.0),
            item.get("parameter_name") or "",
        )
    )

    adapted: list[dict[str, Any]] = []
    for item in prepared:
        if item.get("blocked"):
            adapted.append(item)
            continue

        blocked_reasons = list(item.get("blocked_reasons") or [])
        strategy_why_not = []
        delta_trace = dict(item.get("strategy_delta_trace") or {})
        cooldown_trace = _resolve_effective_cooldown(
            parameter_name=str(item.get("parameter_name") or ""),
            tuning_history=tuning_history,
            cooldown_multiplier=float(item["strategy_controls"]["effective_cooldown_multiplier"]),
        )
        if float(item.get("confidence") or 0.0) < confidence_floor:
            blocked_reasons.append("strategy_confidence_floor_block")
            strategy_why_not.append("strategy confidence floor exceeded")
        if cooldown_trace["cooldown_active"]:
            blocked_reasons.append("strategy_extended_cooldown_active")
            strategy_why_not.append(str(cooldown_trace["strategy_cooldown_reason"]))
        if delta_trace["blocked_by_resolution"]:
            blocked_reasons.append("strategy_micro_step_below_resolution")
            strategy_why_not.append("strategy reduced delta below parameter resolution")
        if delta_trace["delta_clamped"]:
            blocked_reasons = list(dict.fromkeys(blocked_reasons))
        if total_delta + abs(float(delta_trace["effective_delta"])) > max_delta_budget:
            blocked_reasons.append("strategy_budget_cap_exceeded")
            strategy_why_not.append("strategy budget cap exceeded")
        if max_adjustments <= 0:
            blocked_reasons.append("strategy_max_adjustments_exhausted")
            strategy_why_not.append("strategy allows no adjustments")

        if not blocked_reasons:
            total_delta += abs(float(delta_trace["effective_delta"]))
            max_adjustments -= 1

        item["blocked"] = bool(blocked_reasons)
        item["blocked_reasons"] = list(dict.fromkeys(blocked_reasons))
        explanation = dict(item.get("explanation") or {})
        why_not = list(explanation.get("why_not") or [])
        why_not.extend(strategy_why_not)
        explanation["why_not"] = list(dict.fromkeys(why_not))
        explanation["strategy_priority_score"] = item.get("strategy_priority_score")
        explanation["priority_contribution_breakdown"] = dict(item.get("priority_contribution_breakdown") or {})
        explanation["strategy_delta_trace"] = delta_trace
        explanation["strategy_cooldown_trace"] = cooldown_trace
        item["explanation"] = explanation
        adapted.append(item)
    return adapted


def _resolve_parameter_strategy_controls(
    *,
    parameter_name: str,
    base_controls: dict[str, Any],
    risky_parameters: set[str],
    supportive_parameters: set[str],
) -> dict[str, Any]:
    controls = dict(base_controls)
    controls["effective_priority_multiplier"] = 1.0
    if parameter_name in risky_parameters:
        controls["effective_step_multiplier"] = round(float(controls["effective_step_multiplier"]) * 0.7, 4)
        controls["effective_cooldown_multiplier"] = round(float(controls["effective_cooldown_multiplier"]) * 1.25, 4)
        controls["effective_priority_multiplier"] = 0.75
        controls["watch_mode"] = True
    elif parameter_name in supportive_parameters:
        controls["effective_priority_multiplier"] = 1.05
        controls["watch_mode"] = False
    else:
        controls["effective_step_multiplier"] = round(float(controls["effective_step_multiplier"]) * 0.85, 4)
        controls["effective_priority_multiplier"] = 0.9
        controls["watch_mode"] = False
    return controls


def _resolve_effective_delta(*, item: dict[str, Any], param_controls: dict[str, Any]) -> float | int:
    parameter_name = str(item["parameter_name"])
    base_delta = float(item.get("delta") or 0.0)
    multiplier = float(param_controls["effective_step_multiplier"])
    raw_delta = base_delta * multiplier
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    delta_clamped = False
    clamp_reason = None
    if spec["kind"] == "int":
        min_resolution = STRATEGY_INT_MIN_RESOLUTION
        max_delta = max(int(abs(round(base_delta))), int(spec["step"]), STRATEGY_INT_MIN_RESOLUTION)
        rounded_delta = int(round(raw_delta))
        blocked_by_resolution = rounded_delta == 0 and abs(base_delta) > 0
        effective_delta = max(-max_delta, min(max_delta, rounded_delta))
        if effective_delta != rounded_delta:
            delta_clamped = True
            clamp_reason = "strategy_delta_clamped"
        return {
            "base_delta": int(round(base_delta)),
            "multiplier_applied": round(multiplier, 4),
            "raw_effective_delta": raw_delta,
            "effective_delta": effective_delta,
            "effective_step_resolution": min_resolution,
            "delta_clamped": delta_clamped,
            "clamp_reason": clamp_reason,
            "blocked_by_resolution": blocked_by_resolution,
        }

    step = float(spec["step"])
    min_resolution = round(step * STRATEGY_FLOAT_MIN_RESOLUTION_RATIO, 4)
    max_delta = round(max(abs(base_delta), step * STRATEGY_FLOAT_MAX_STEP_RATIO), 4)
    blocked_by_resolution = abs(raw_delta) < min_resolution and abs(base_delta) > 0
    effective_delta = round(max(-max_delta, min(max_delta, raw_delta)), 4)
    if effective_delta != round(raw_delta, 4):
        delta_clamped = True
        clamp_reason = "strategy_delta_clamped"
    return {
        "base_delta": round(base_delta, 4),
        "multiplier_applied": round(multiplier, 4),
        "raw_effective_delta": round(raw_delta, 4),
        "effective_delta": effective_delta,
        "effective_step_resolution": min_resolution,
        "delta_clamped": delta_clamped,
        "clamp_reason": clamp_reason,
        "blocked_by_resolution": blocked_by_resolution,
    }


def _resolve_effective_proposed_value(*, item: dict[str, Any], effective_delta: float | int) -> float | int:
    parameter_name = str(item["parameter_name"])
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    raw_value = float(item["current_value"]) + float(effective_delta)
    bounded = max(float(spec["min_value"]), min(float(spec["max_value"]), raw_value))
    if spec["kind"] == "int":
        return int(round(bounded))
    return round(bounded, 4)


def _is_strategy_cooldown_active(
    *,
    parameter_name: str,
    tuning_history: list[dict[str, Any]],
    base_cooldown_hours: int,
    cooldown_multiplier: float,
) -> bool:
    cooldown_hours = max(int(round(base_cooldown_hours * cooldown_multiplier)), base_cooldown_hours)
    now = utc_now()
    for item in tuning_history:
        if str(item.get("parameter_name") or "") != parameter_name:
            continue
        created_at = item.get("created_at")
        if created_at is None:
            continue
        return created_at >= now - timedelta(hours=cooldown_hours)
    return False


def _resolve_effective_cooldown(
    *,
    parameter_name: str,
    tuning_history: list[dict[str, Any]],
    cooldown_multiplier: float,
) -> dict[str, Any]:
    base_cooldown_hours = int(TUNABLE_PARAMETER_SPECS[parameter_name]["cooldown_hours"])
    raw_cooldown = int(round(base_cooldown_hours * cooldown_multiplier))
    effective_cooldown_hours = max(
        STRATEGY_MIN_COOLDOWN_HOURS,
        min(STRATEGY_MAX_COOLDOWN_HOURS, max(raw_cooldown, base_cooldown_hours)),
    )
    cooldown_clamped = effective_cooldown_hours != max(raw_cooldown, base_cooldown_hours)
    strategy_cooldown_reason = "extended strategy cooldown active"
    if cooldown_clamped:
        strategy_cooldown_reason = "strategy cooldown clamped before evaluation"
    cooldown_active = _is_strategy_cooldown_active(
        parameter_name=parameter_name,
        tuning_history=tuning_history,
        base_cooldown_hours=effective_cooldown_hours,
        cooldown_multiplier=1.0,
    )
    if cooldown_active:
        strategy_cooldown_reason = f"extended strategy cooldown active ({effective_cooldown_hours}h)"
    return {
        "base_cooldown_hours": base_cooldown_hours,
        "raw_cooldown_hours": raw_cooldown,
        "effective_cooldown_hours": effective_cooldown_hours,
        "cooldown_clamped": cooldown_clamped,
        "strategy_cooldown_reason": strategy_cooldown_reason,
        "cooldown_active": cooldown_active,
    }


def _apply_strategy_hysteresis(
    *,
    base_profile: str,
    strategy_history: list[dict[str, Any]],
    meta_confidence: float,
    current_context: str,
) -> tuple[str, dict[str, Any]]:
    recent_profiles = [
        str(item.get("final_strategy_profile") or item.get("strategy_profile") or "")
        for item in strategy_history[:STRATEGY_HYSTERESIS_WINDOW]
        if str(item.get("final_strategy_profile") or item.get("strategy_profile") or "").strip()
    ]
    if not recent_profiles:
        return base_profile, {
            "strategy_hysteresis_applied": False,
            "strategy_transition_reason": "no_recent_strategy_history",
            "hysteresis_locked_profile": None,
            "hysteresis_window_size": STRATEGY_HYSTERESIS_WINDOW,
            "hysteresis_recent_profiles": [],
            "hysteresis_relaxation_allowed": False,
            "requested_strategy_profile": base_profile,
            "final_strategy_profile": base_profile,
        }

    previous_profile = recent_profiles[0]
    previous_rank = STRATEGY_PROFILE_ORDER.get(previous_profile, STRATEGY_PROFILE_ORDER[DEFAULT_SELF_TUNING_STRATEGY_PROFILE])
    base_rank = STRATEGY_PROFILE_ORDER.get(base_profile, STRATEGY_PROFILE_ORDER[DEFAULT_SELF_TUNING_STRATEGY_PROFILE])

    if base_rank <= previous_rank:
        if base_profile == previous_profile:
            return base_profile, {
                "strategy_hysteresis_applied": False,
                "strategy_transition_reason": "profile_unchanged",
                "hysteresis_locked_profile": previous_profile,
                "hysteresis_window_size": STRATEGY_HYSTERESIS_WINDOW,
                "hysteresis_recent_profiles": recent_profiles,
                "hysteresis_relaxation_allowed": False,
                "requested_strategy_profile": base_profile,
                "final_strategy_profile": base_profile,
            }
        return base_profile, {
            "strategy_hysteresis_applied": False,
            "strategy_transition_reason": "hardening_allowed_immediately",
            "hysteresis_locked_profile": previous_profile,
            "hysteresis_window_size": STRATEGY_HYSTERESIS_WINDOW,
            "hysteresis_recent_profiles": recent_profiles,
            "hysteresis_relaxation_allowed": False,
            "requested_strategy_profile": base_profile,
            "final_strategy_profile": base_profile,
        }

    if meta_confidence < STRATEGY_RELAXATION_MIN_META_CONFIDENCE or current_context != "stable":
        return previous_profile, {
            "strategy_hysteresis_applied": True,
            "strategy_transition_reason": "strategy_hysteresis_preserved_more_restrictive_profile",
            "hysteresis_locked_profile": previous_profile,
            "hysteresis_window_size": STRATEGY_HYSTERESIS_WINDOW,
            "hysteresis_recent_profiles": recent_profiles,
            "hysteresis_relaxation_allowed": False,
            "requested_strategy_profile": base_profile,
            "final_strategy_profile": previous_profile,
        }

    allowed_rank = min(previous_rank + 1, base_rank)
    if allowed_rank < base_rank:
        final_profile = _profile_from_rank(allowed_rank)
        return final_profile, {
            "strategy_hysteresis_applied": True,
            "strategy_transition_reason": "strategy_hysteresis_softened_only_one_level",
            "hysteresis_locked_profile": previous_profile,
            "hysteresis_window_size": STRATEGY_HYSTERESIS_WINDOW,
            "hysteresis_recent_profiles": recent_profiles,
            "hysteresis_relaxation_allowed": True,
            "requested_strategy_profile": base_profile,
            "final_strategy_profile": final_profile,
        }

    return base_profile, {
        "strategy_hysteresis_applied": False,
        "strategy_transition_reason": "relaxation_allowed_with_strong_evidence",
        "hysteresis_locked_profile": previous_profile,
        "hysteresis_window_size": STRATEGY_HYSTERESIS_WINDOW,
        "hysteresis_recent_profiles": recent_profiles,
        "hysteresis_relaxation_allowed": True,
        "requested_strategy_profile": base_profile,
        "final_strategy_profile": base_profile,
    }


def _profile_from_rank(rank: int) -> str:
    for profile, value in STRATEGY_PROFILE_ORDER.items():
        if value == rank:
            return profile
    return DEFAULT_SELF_TUNING_STRATEGY_PROFILE


def _resolve_strategy_action(
    *,
    base_action: str,
    profile: str,
    meta_confidence: float,
    history_summary: dict[str, Any],
    current_context: str,
    rollback_ratio: float,
) -> str:
    if base_action in {"block", "observe_only"}:
        return base_action
    weighted_unknown = float(history_summary.get("weighted_unknown_outcome_rate") or 0.0)
    if profile == "observe_only_strategy":
        return "observe_only"
    if profile == "restricted_adjustment":
        if meta_confidence < 0.3 or weighted_unknown >= 0.7 or rollback_ratio >= 0.12:
            return "observe_only"
        return "simulate" if base_action == "apply" else base_action
    if profile == "micro_adjustment":
        if base_action == "apply" and (
            weighted_unknown >= 0.6
            or (meta_confidence < 0.45 and current_context in {"fragile", "low_evidence_context"})
        ):
            return "simulate"
    return base_action
