from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.services.self_tuning_constants import (
    ANTI_OSCILLATION_WINDOW_HOURS,
    DEFAULT_SELF_TUNING_MODE,
    INEFFECTIVE_TUNING_LOOKBACK_HOURS,
    MAX_ADJUSTMENTS_PER_CYCLE,
    MIN_EVIDENCE_SAMPLE_SIZE,
    PREFERRED_TUNING_SAMPLE_SIZE,
    ROLLBACK_PRESSURE_BLOCK_COUNT,
    ROLLBACK_PRESSURE_BLOCK_RATIO,
    SELF_TUNING_MODES,
    SELF_TUNING_SAFETY_LIMITS,
    TREND_STABILITY_MIN,
    TUNABLE_PARAMETER_SPECS,
    TUNING_BUDGET_WINDOW_HOURS_24,
    TUNING_BUDGET_WINDOW_HOURS_7D,
)
from app.services.utc import utc_now


def evaluate_self_tuning_candidates(
    *,
    signals: dict[str, Any],
    current_controls: dict[str, Any],
    tuning_history: list[dict[str, Any]],
    aggressiveness_mode: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    mode_name = aggressiveness_mode if aggressiveness_mode in SELF_TUNING_MODES else DEFAULT_SELF_TUNING_MODE
    mode_config = SELF_TUNING_MODES[mode_name]
    max_adjustments = min(int(mode_config["max_adjustments"]), MAX_ADJUSTMENTS_PER_CYCLE)
    confidence_multiplier = float(mode_config["confidence_multiplier"])

    signal_snapshot = _normalize_signals(signals)
    global_block_reasons = _resolve_global_block_reasons(signal_snapshot)
    candidates: list[dict[str, Any]] = []
    cycle_blocked_reasons: list[str] = list(global_block_reasons)

    if global_block_reasons:
        return [], cycle_blocked_reasons, signal_snapshot["risk_flags"]

    for parameter_name in TUNABLE_PARAMETER_SPECS:
        candidate = _build_candidate(
            parameter_name=parameter_name,
            signal_snapshot=signal_snapshot,
            current_controls=current_controls,
            tuning_history=tuning_history,
            confidence_multiplier=confidence_multiplier,
        )
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item["blocked"],
            -float(item["priority_score"]),
            -float(item["confidence"]),
            item["parameter_name"],
        )
    )
    selectable = [candidate for candidate in candidates if not candidate["blocked"]][:max_adjustments]

    # --- Safety envelope: cap total delta per cycle ---
    safety_max_delta = float(SELF_TUNING_SAFETY_LIMITS["max_total_delta_per_cycle"])
    envelope_selectable: list[dict[str, Any]] = []
    accumulated_delta = 0.0
    for candidate in selectable:
        candidate_abs_delta = _resolve_comparable_delta(
            parameter_name=str(candidate["parameter_name"]),
            delta=candidate["delta"],
        )
        if accumulated_delta + candidate_abs_delta <= safety_max_delta:
            accumulated_delta += candidate_abs_delta
            envelope_selectable.append(candidate)
        else:
            candidate["blocked"] = True
            candidate["blocked_reasons"] = list(candidate.get("blocked_reasons") or [])
            candidate["blocked_reasons"].append("safety_envelope_total_delta_exceeded")
    selectable = envelope_selectable

    blocked_candidates = [candidate for candidate in candidates if candidate["blocked"]]
    cycle_blocked_reasons.extend(_collect_blocked_reasons(blocked_candidates))
    return selectable + blocked_candidates, list(dict.fromkeys(cycle_blocked_reasons)), signal_snapshot["risk_flags"]


def should_apply_self_tuning(
    *,
    candidates: list[dict[str, Any]],
    blocked_reasons: list[str],
    dry_run: bool,
) -> tuple[bool, str, float, bool]:
    actionable = [candidate for candidate in candidates if not candidate["blocked"]]
    if not actionable:
        if "no_data" in blocked_reasons:
            return False, "no_data", 0.0, False
        if blocked_reasons:
            return False, "blocked", 0.0, False
        return False, "no_data", 0.0, False

    confidence = round(
        sum(float(candidate["confidence"]) for candidate in actionable) / max(len(actionable), 1),
        4,
    )
    requires_review = any(
        flag in candidate["risk_flags"]
        for candidate in actionable
        for flag in {"governance_watch", "rollback_pressure", "contradictory_recent_evidence"}
    )
    if dry_run:
        return False, "simulated", confidence, requires_review
    return True, "applied", confidence, requires_review


def _build_candidate(
    *,
    parameter_name: str,
    signal_snapshot: dict[str, Any],
    current_controls: dict[str, Any],
    tuning_history: list[dict[str, Any]],
    confidence_multiplier: float = 1.0,
) -> dict[str, Any] | None:
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    current_value = _coerce_parameter_value(parameter_name, current_controls.get(parameter_name, spec["default"]))
    direction = _resolve_direction(parameter_name=parameter_name, signal_snapshot=signal_snapshot)
    if direction == "hold":
        return None

    proposed_value = _apply_step(parameter_name=parameter_name, current_value=current_value, direction=direction)
    delta = proposed_value - current_value
    raw_confidence = _resolve_candidate_confidence(signal_snapshot=signal_snapshot, direction=direction)
    confidence = max(0.0, min(1.0, raw_confidence * confidence_multiplier))
    evidence = _build_candidate_evidence(signal_snapshot=signal_snapshot)
    risk_flags = list(signal_snapshot["risk_flags"])
    blocked_reasons: list[str] = []
    why_not_reasons: list[str] = []
    blocked = False

    if proposed_value == current_value:
        blocked = True
        blocked_reasons.append("parameter_at_bound")
        why_not_reasons.append("proposed value equals current (at parameter bound)")

    cooldown_reason = _resolve_cooldown_reason(
        parameter_name=parameter_name,
        tuning_history=tuning_history,
        cooldown_hours=int(spec["cooldown_hours"]),
    )
    if cooldown_reason:
        blocked = True
        blocked_reasons.append(cooldown_reason)
        why_not_reasons.append(f"cooldown active ({spec['cooldown_hours']}h)")

    oscillation_reason = _resolve_anti_oscillation_reason(
        parameter_name=parameter_name,
        direction=direction,
        tuning_history=tuning_history,
    )
    if oscillation_reason:
        blocked = True
        blocked_reasons.append(oscillation_reason)
        why_not_reasons.append("direction flip within anti-oscillation window")

    historical_ineffective_reason = _resolve_historical_ineffective_reason(
        parameter_name=parameter_name,
        tuning_history=tuning_history,
    )
    if historical_ineffective_reason:
        blocked = True
        blocked_reasons.append(historical_ineffective_reason)
        why_not_reasons.append("historically ineffective tuning for this parameter")

    # --- Parameter guardrails check ---
    guardrail_reason = _check_parameter_guardrails(
        parameter_name=parameter_name,
        current_value=current_value,
        proposed_value=proposed_value,
        tuning_history=tuning_history,
    )
    if guardrail_reason:
        blocked = True
        blocked_reasons.append(guardrail_reason)
        why_not_reasons.append(f"guardrail violated: {guardrail_reason}")

    # --- Tuning budget check ---
    budget_reason = _check_tuning_budget(
        parameter_name=parameter_name,
        tuning_history=tuning_history,
    )
    if budget_reason:
        blocked = True
        blocked_reasons.append(budget_reason)
        why_not_reasons.append(f"tuning budget exceeded: {budget_reason}")

    if confidence < 0.66:
        blocked = True
        blocked_reasons.append("insufficient_candidate_confidence")
        why_not_reasons.append(f"confidence {confidence:.4f} < 0.66 threshold")

    priority_score = _resolve_priority_score(
        parameter_name=parameter_name,
        confidence=confidence,
        delta=delta,
        signal_snapshot=signal_snapshot,
    )

    # --- Build explanation ---
    explanation = _build_explanation(
        parameter_name=parameter_name,
        direction=direction,
        signal_snapshot=signal_snapshot,
        tuning_history=tuning_history,
        blocked=blocked,
        why_not_reasons=why_not_reasons,
        risk_flags=risk_flags,
    )

    return {
        "parameter_name": parameter_name,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "direction": direction,
        "delta": _round_value(parameter_name, delta),
        "confidence": round(confidence, 4),
        "priority_score": round(priority_score, 4),
        "evidence": evidence,
        "risk_flags": risk_flags,
        "blocked": blocked,
        "blocked_reasons": list(dict.fromkeys(blocked_reasons)),
        "explanation": explanation,
    }


def _normalize_signals(signals: dict[str, Any]) -> dict[str, Any]:
    signals = dict(signals or {})
    sample_size = max(
        _safe_int(signals.get("sample_size")),
        _safe_int(signals.get("audited_count")),
        _safe_int(signals.get("impact_total")),
        _safe_int(signals.get("total_observations")),
    )
    failed_ratio = _safe_float(signals.get("failed_ratio"))
    regression_rate = _safe_float(signals.get("regression_rate"))
    improvement_rate = _safe_float(signals.get("improvement_rate"))
    neutral_rate = _safe_float(signals.get("neutral_rate"))
    questionable_ratio = _safe_float(signals.get("questionable_ratio"))
    recent_avg_score = _safe_float(signals.get("recent_avg_score"))
    previous_avg_score = _safe_float(signals.get("previous_avg_score"))
    historical_avg_score = _safe_float(signals.get("historical_avg_score"))
    recent_vs_historical_delta = _safe_float(signals.get("recent_vs_historical_delta"))
    trend_stability = _safe_float(signals.get("trend_stability"))
    consistency = _safe_float(signals.get("consistency"))
    top_flags = dict(signals.get("top_flag_counts") or {})
    drift_level = str(signals.get("drift_level") or "none").strip().lower()
    governance_status = str(signals.get("governance_status") or "healthy").strip().lower()
    rollback_ratio = _safe_float(signals.get("rollback_ratio"))
    rollback_candidates = _safe_int(signals.get("rollback_candidates"))

    risk_flags: list[str] = []
    if sample_size <= 0:
        risk_flags.append("insufficient_data_for_tuning")
    elif sample_size < MIN_EVIDENCE_SAMPLE_SIZE:
        risk_flags.append("insufficient_data_for_tuning")
    elif sample_size < PREFERRED_TUNING_SAMPLE_SIZE:
        risk_flags.append("cold_start_tuning_block")
    if drift_level in {"high", "medium"}:
        risk_flags.append("strong_drift" if drift_level == "high" else "drift_watch")
    if regression_rate >= 0.22 or failed_ratio >= 0.18:
        risk_flags.append("recent_regression")
    if consistency < 0.48 or questionable_ratio >= 0.35:
        risk_flags.append("mixed_evidence")
    if trend_stability < TREND_STABILITY_MIN:
        risk_flags.append("unstable_trend")
    if _is_contradictory_recent_evidence(
        recent_avg_score=recent_avg_score,
        previous_avg_score=previous_avg_score,
        historical_avg_score=historical_avg_score,
        recent_vs_historical_delta=recent_vs_historical_delta,
        regression_rate=regression_rate,
    ):
        risk_flags.append("contradictory_recent_evidence")
    if top_flags.get("simulation_overconfidence", 0) >= 3:
        risk_flags.append("simulation_overconfidence")
    if governance_status in {"watch", "degraded"}:
        risk_flags.append(f"governance_{governance_status}")
    if rollback_ratio >= ROLLBACK_PRESSURE_BLOCK_RATIO or rollback_candidates >= ROLLBACK_PRESSURE_BLOCK_COUNT:
        risk_flags.append("rollback_pressure")

    return {
        "sample_size": sample_size,
        "failed_ratio": failed_ratio,
        "regression_rate": regression_rate,
        "improvement_rate": improvement_rate,
        "neutral_rate": neutral_rate,
        "questionable_ratio": questionable_ratio,
        "recent_avg_score": recent_avg_score,
        "previous_avg_score": previous_avg_score,
        "historical_avg_score": historical_avg_score,
        "recent_vs_historical_delta": recent_vs_historical_delta,
        "trend_stability": trend_stability,
        "consistency": consistency,
        "drift_level": drift_level,
        "governance_status": governance_status,
        "rollback_ratio": rollback_ratio,
        "rollback_candidates": rollback_candidates,
        "top_flag_counts": top_flags,
        "risk_flags": list(dict.fromkeys(risk_flags)),
    }


def _resolve_global_block_reasons(signal_snapshot: dict[str, Any]) -> list[str]:
    blocked_reasons: list[str] = []
    risk_flags = set(signal_snapshot["risk_flags"])
    if signal_snapshot["sample_size"] <= 0:
        blocked_reasons.append("no_data")
    if "insufficient_data_for_tuning" in risk_flags:
        blocked_reasons.append("insufficient_data_for_tuning")
    if "cold_start_tuning_block" in risk_flags:
        blocked_reasons.append("cold_start_tuning_block")
    if "strong_drift" in risk_flags:
        blocked_reasons.append("recent_regression_or_drift")
    if "mixed_evidence" in risk_flags:
        blocked_reasons.append("mixed_evidence")
    if "unstable_trend" in risk_flags:
        blocked_reasons.append("unstable_trend")
    if "contradictory_recent_evidence" in risk_flags:
        blocked_reasons.append("contradictory_recent_evidence")
    if "rollback_pressure" in risk_flags:
        blocked_reasons.append("rollback_pressure_block")
    return list(dict.fromkeys(blocked_reasons))


def _resolve_direction(*, parameter_name: str, signal_snapshot: dict[str, Any]) -> str:
    positive_signal = (
        signal_snapshot["improvement_rate"] >= 0.68
        and signal_snapshot["regression_rate"] <= 0.08
        and signal_snapshot["consistency"] >= 0.72
        and signal_snapshot["trend_stability"] >= 0.65
        and signal_snapshot["recent_avg_score"] >= 0.22
        and signal_snapshot["historical_avg_score"] >= 0.08
        and signal_snapshot["rollback_ratio"] < 0.05
    )
    negative_signal = (
        signal_snapshot["regression_rate"] >= 0.16
        or signal_snapshot["failed_ratio"] >= 0.1
        or signal_snapshot["top_flag_counts"].get("simulation_overconfidence", 0) >= 2
        or signal_snapshot["rollback_ratio"] >= 0.05
    )
    if positive_signal and not negative_signal:
        if parameter_name in {"apply_confidence_delta", "min_sample_size_delta", "uncertain_apply_confidence_min"}:
            return "decrease"
        return "increase"
    if negative_signal:
        if parameter_name in {"apply_confidence_delta", "min_sample_size_delta", "uncertain_apply_confidence_min"}:
            return "increase"
        return "decrease"
    return "hold"


def _resolve_candidate_confidence(*, signal_snapshot: dict[str, Any], direction: str) -> float:
    base_confidence = 0.45
    base_confidence += min(signal_snapshot["sample_size"] / 160.0, 0.14)
    base_confidence += min(signal_snapshot["consistency"] * 0.18, 0.18)
    base_confidence += min(signal_snapshot["trend_stability"] * 0.14, 0.14)
    if direction == "increase":
        base_confidence += min(signal_snapshot["regression_rate"] * 0.35, 0.12)
    else:
        base_confidence += min(signal_snapshot["improvement_rate"] * 0.25, 0.1)
    if "simulation_overconfidence" in signal_snapshot["risk_flags"]:
        base_confidence += 0.05
    if "drift_watch" in signal_snapshot["risk_flags"]:
        base_confidence -= 0.08
    if "contradictory_recent_evidence" in signal_snapshot["risk_flags"]:
        base_confidence -= 0.12
    return max(0.0, min(1.0, base_confidence))


def _resolve_priority_score(
    *,
    parameter_name: str,
    confidence: float,
    delta: float | int,
    signal_snapshot: dict[str, Any],
) -> float:
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    param_priority = float(spec.get("priority_weight") or 0.5)
    range_span = max(float(spec["max_value"]) - float(spec["min_value"]), 1e-9)
    normalized_delta = min(abs(float(delta)) / range_span, 1.0)
    stability_component = min(signal_snapshot["trend_stability"], signal_snapshot["consistency"])
    return (
        confidence * 0.55
        + param_priority * 0.25
        + normalized_delta * 0.1
        + stability_component * 0.1
    )


def _build_candidate_evidence(signal_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_size": signal_snapshot["sample_size"],
        "improvement_rate": round(signal_snapshot["improvement_rate"], 4),
        "regression_rate": round(signal_snapshot["regression_rate"], 4),
        "neutral_rate": round(signal_snapshot["neutral_rate"], 4),
        "failed_ratio": round(signal_snapshot["failed_ratio"], 4),
        "questionable_ratio": round(signal_snapshot["questionable_ratio"], 4),
        "recent_avg_score": round(signal_snapshot["recent_avg_score"], 4),
        "previous_avg_score": round(signal_snapshot["previous_avg_score"], 4),
        "historical_avg_score": round(signal_snapshot["historical_avg_score"], 4),
        "recent_vs_historical_delta": round(signal_snapshot["recent_vs_historical_delta"], 4),
        "trend_stability": round(signal_snapshot["trend_stability"], 4),
        "consistency": round(signal_snapshot["consistency"], 4),
    }


def _resolve_cooldown_reason(
    *,
    parameter_name: str,
    tuning_history: list[dict[str, Any]],
    cooldown_hours: int,
) -> str | None:
    latest_event = _get_latest_parameter_event(parameter_name=parameter_name, tuning_history=tuning_history)
    if latest_event is None:
        return None
    created_at = latest_event.get("created_at")
    if created_at is None:
        return None
    if created_at >= utc_now() - timedelta(hours=cooldown_hours):
        return "cooldown_active"
    return None


def _resolve_anti_oscillation_reason(
    *,
    parameter_name: str,
    direction: str,
    tuning_history: list[dict[str, Any]],
) -> str | None:
    latest_event = _get_latest_parameter_event(parameter_name=parameter_name, tuning_history=tuning_history)
    if latest_event is None:
        return None
    created_at = latest_event.get("created_at")
    previous_direction = str(latest_event.get("direction") or "")
    if created_at is None:
        return None
    if created_at < utc_now() - timedelta(hours=ANTI_OSCILLATION_WINDOW_HOURS):
        return None
    if previous_direction and previous_direction != direction:
        return "anti_oscillation_block"
    return None


def _resolve_historical_ineffective_reason(
    *,
    parameter_name: str,
    tuning_history: list[dict[str, Any]],
) -> str | None:
    window_start = utc_now() - timedelta(hours=INEFFECTIVE_TUNING_LOOKBACK_HOURS)
    relevant_items = [
        item
        for item in tuning_history
        if str(item.get("parameter_name") or "") == parameter_name
        and item.get("created_at") is not None
        and item["created_at"] >= window_start
    ]
    known_items = [item for item in relevant_items if str(item.get("effectiveness") or "unknown") != "unknown"]
    if not known_items:
        return None
    latest_known = known_items[0]
    ineffective_count = sum(1 for item in known_items if item.get("effectiveness") == "ineffective")
    effective_count = sum(1 for item in known_items if item.get("effectiveness") == "effective")
    if str(latest_known.get("effectiveness") or "") == "ineffective" and effective_count == 0:
        return "historical_ineffective_tuning"
    if ineffective_count >= 2 and ineffective_count > effective_count:
        return "historical_ineffective_tuning"
    return None


def _get_latest_parameter_event(
    *,
    parameter_name: str,
    tuning_history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in tuning_history:
        if str(item.get("parameter_name") or "") == parameter_name:
            return item
    return None


def _apply_step(*, parameter_name: str, current_value: float | int, direction: str) -> float | int:
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    step = spec["step"]
    delta = step if direction == "increase" else -step
    raw_value = current_value + delta
    return _clamp_parameter_value(parameter_name, raw_value)


def _clamp_parameter_value(parameter_name: str, value: float | int) -> float | int:
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    bounded = max(spec["min_value"], min(spec["max_value"], value))
    if spec["kind"] == "int":
        return int(round(bounded))
    return round(float(bounded), 4)


def _coerce_parameter_value(parameter_name: str, value: Any) -> float | int:
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    if spec["kind"] == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(spec["default"])
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return round(float(spec["default"]), 4)


def _round_value(parameter_name: str, value: float | int) -> float | int:
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    if spec["kind"] == "int":
        return int(round(value))
    return round(float(value), 4)


def _is_contradictory_recent_evidence(
    *,
    recent_avg_score: float,
    previous_avg_score: float,
    historical_avg_score: float,
    recent_vs_historical_delta: float,
    regression_rate: float,
) -> bool:
    if historical_avg_score > 0.12 and recent_avg_score < -0.05:
        return True
    if previous_avg_score > 0.12 and recent_avg_score < 0.0:
        return True
    if abs(recent_vs_historical_delta) >= 0.28 and regression_rate >= 0.12:
        return True
    return False


def _check_parameter_guardrails(
    *,
    parameter_name: str,
    current_value: float | int,
    proposed_value: float | int,
    tuning_history: list[dict[str, Any]],
) -> str | None:
    spec = dict(TUNABLE_PARAMETER_SPECS[parameter_name])
    guardrails = spec.get("guardrails")
    if not guardrails:
        return None

    safe_zone = guardrails.get("safe_zone")
    if safe_zone is not None:
        safe_min, safe_max = float(safe_zone[0]), float(safe_zone[1])
        cur = float(current_value)
        prop = float(proposed_value)
        cur_inside = safe_min <= cur <= safe_max
        prop_inside = safe_min <= prop <= safe_max

        if cur_inside and not prop_inside:
            # A) Current is inside safe zone — block any move that exits it
            return "guardrail_safe_zone_exit_blocked"

        if not cur_inside and not prop_inside:
            # B) Current is outside — only allow moves that get closer to the zone
            cur_distance = max(cur - safe_max, safe_min - cur, 0.0)
            prop_distance = max(prop - safe_max, safe_min - prop, 0.0)
            if prop_distance >= cur_distance:
                # Not recovering — blocks
                return "guardrail_safe_zone_no_recovery"
            # prop_distance < cur_distance → recovering → allow

    now = utc_now()
    daily_delta = _compute_accumulated_delta(
        parameter_name=parameter_name,
        tuning_history=tuning_history,
        hours=TUNING_BUDGET_WINDOW_HOURS_24,
        now=now,
    )
    max_daily = float(guardrails.get("max_daily_shift", 999.0))
    if daily_delta >= max_daily:
        return "guardrail_max_daily_shift_exceeded"

    weekly_delta = _compute_accumulated_delta(
        parameter_name=parameter_name,
        tuning_history=tuning_history,
        hours=TUNING_BUDGET_WINDOW_HOURS_7D,
        now=now,
    )
    max_weekly = float(guardrails.get("max_weekly_shift", 999.0))
    if weekly_delta >= max_weekly:
        return "guardrail_max_weekly_shift_exceeded"

    return None


def _check_tuning_budget(
    *,
    parameter_name: str,
    tuning_history: list[dict[str, Any]],
) -> str | None:
    now = utc_now()
    max_daily_delta = float(SELF_TUNING_SAFETY_LIMITS["max_delta_per_parameter_per_day"])
    daily_delta = _compute_accumulated_delta(
        parameter_name=parameter_name,
        tuning_history=tuning_history,
        hours=TUNING_BUDGET_WINDOW_HOURS_24,
        now=now,
    )
    if daily_delta >= max_daily_delta:
        return "tuning_budget_daily_exceeded"

    # Limit the total number of recent changes for this parameter within the
    # 7-day window. This is intentionally a count-in-window heuristic, not a
    # strict consecutiveness check.
    max_changes = int(SELF_TUNING_SAFETY_LIMITS["max_changes_per_window"])
    recent_changes = [
        item for item in tuning_history
        if str(item.get("parameter_name") or "") == parameter_name
        and item.get("created_at") is not None
        and item["created_at"] >= now - timedelta(hours=TUNING_BUDGET_WINDOW_HOURS_7D)
    ]
    if len(recent_changes) >= max_changes:
        return "tuning_budget_recent_change_count_exceeded"

    return None


def _compute_accumulated_delta(
    *,
    parameter_name: str,
    tuning_history: list[dict[str, Any]],
    hours: int,
    now: Any,
) -> float:
    window_start = now - timedelta(hours=hours)
    total = 0.0
    for item in tuning_history:
        if str(item.get("parameter_name") or "") != parameter_name:
            continue
        created_at = item.get("created_at")
        if created_at is None or created_at < window_start:
            continue
        delta = item.get("delta")
        if delta is not None:
            total += _resolve_comparable_delta(parameter_name=parameter_name, delta=delta)
        else:
            spec = TUNABLE_PARAMETER_SPECS.get(parameter_name)
            if spec:
                total += _resolve_comparable_delta(parameter_name=parameter_name, delta=spec["step"])
    return total


def _distance_to_safe_zone(value: float, safe_min: float, safe_max: float) -> float:
    if safe_min <= value <= safe_max:
        return 0.0
    if value < safe_min:
        return safe_min - value
    return value - safe_max


def _resolve_comparable_delta(*, parameter_name: str, delta: float | int) -> float:
    _ = parameter_name
    # FASE 8.1B: keep the current absolute-delta contract for the envelope and
    # budget checks. This helper isolates the calculation so range-normalized
    # deltas can be introduced later without changing current callers.
    return abs(float(delta))


def _build_explanation(
    *,
    parameter_name: str,
    direction: str,
    signal_snapshot: dict[str, Any],
    tuning_history: list[dict[str, Any]],
    blocked: bool,
    why_not_reasons: list[str],
    risk_flags: list[str],
) -> dict[str, Any]:
    improvement_rate = signal_snapshot.get("improvement_rate", 0.0)
    regression_rate = signal_snapshot.get("regression_rate", 0.0)

    if improvement_rate > regression_rate:
        dominant_signal = "improvement"
    elif regression_rate > improvement_rate:
        dominant_signal = "regression"
    else:
        dominant_signal = "neutral"

    if direction == "hold":
        why = f"Signal for {parameter_name} is ambiguous — holding"
    elif blocked:
        why = f"Would {direction} {parameter_name} but blocked"
    else:
        why = f"Evidence supports {direction} for {parameter_name} (dominant: {dominant_signal})"

    stability = "stable" if signal_snapshot.get("trend_stability", 0) >= 0.65 else "unstable"

    risk_context: list[str] = []
    if "drift_watch" in risk_flags:
        risk_context.append("drift at medium level")
    if "recent_regression" in risk_flags:
        risk_context.append("recent regression detected")
    if "simulation_overconfidence" in risk_flags:
        risk_context.append("simulation overconfidence flagged")
    if "rollback_pressure" in risk_flags:
        risk_context.append("rollback pressure present")

    param_history = [
        item for item in tuning_history
        if str(item.get("parameter_name") or "") == parameter_name
    ]
    effective_count = sum(1 for item in param_history if item.get("effectiveness") == "effective")
    ineffective_count = sum(1 for item in param_history if item.get("effectiveness") == "ineffective")
    total_count = len(param_history)
    historical_context = {
        "total_adjustments": total_count,
        "effective": effective_count,
        "ineffective": ineffective_count,
        "unknown": total_count - effective_count - ineffective_count,
    }

    return {
        "why": why,
        "why_not": why_not_reasons if why_not_reasons else [],
        "risk_context": risk_context,
        "historical_context": historical_context,
        "dominant_signal": dominant_signal,
        "stability": stability,
    }


def _collect_blocked_reasons(candidates: list[dict[str, Any]]) -> list[str]:
    blocked_reasons: list[str] = []
    for candidate in candidates:
        blocked_reasons.extend(list(candidate.get("blocked_reasons") or []))
    return list(dict.fromkeys(blocked_reasons))


def _safe_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
