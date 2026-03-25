from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.services.self_tuning_constants import DEFAULT_SELF_TUNING_MODE, SELF_TUNING_EVENT_TYPE
from app.services.self_tuning_strategy_policy import build_strategy_recommendation


def build_self_tuning_strategy_snapshot(
    *,
    recommendation: dict[str, Any],
    meta_snapshot: dict[str, Any],
    current_signals: dict[str, Any],
    tuning_history: list[dict[str, Any]],
    strategy_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    strategy = build_strategy_recommendation(
        recommendation=recommendation,
        meta_snapshot=meta_snapshot,
        current_signals=current_signals,
        tuning_history=tuning_history,
        strategy_history=strategy_history,
    )
    return {
        "strategy_profile": strategy["strategy_profile"],
        "strategy_reasoning": strategy["strategy_reasoning"],
        "strategy_controls": strategy["strategy_controls"],
        "strategy_risk_flags": strategy["strategy_risk_flags"],
        "strategy_override_applied": strategy["strategy_override_applied"],
        "strategy_support_level": strategy["strategy_support_level"],
        "recommended_action": strategy["recommended_action"],
        "adapted_candidates": strategy["adapted_candidates"],
        "base_strategy_profile": strategy["base_strategy_profile"],
        "final_strategy_profile": strategy["final_strategy_profile"],
        "strategy_transition_reason": strategy["strategy_transition_reason"],
        "strategy_hysteresis_applied": strategy["strategy_hysteresis_applied"],
        "strategy_hysteresis_state": strategy["strategy_hysteresis_state"],
    }


def get_self_tuning_strategy_summary(
    db: Session,
    *,
    limit: int = 120,
) -> dict[str, Any]:
    action_logs = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == SELF_TUNING_EVENT_TYPE)
        .order_by(LearningActionLog.created_at.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    profile_counts: dict[str, int] = {}
    profile_transitions: dict[str, int] = {}
    restricted_parameters: dict[str, int] = {}
    micro_contexts: dict[str, int] = {}
    last_strategy: dict[str, Any] | None = None
    previous_profile: str | None = None
    hysteresis_events = 0
    conflict_count = 0
    total_controls = 0
    total_step_multiplier = 0.0
    total_cooldown_hours = 0.0
    restriction_profiles = 0

    for action_log in action_logs:
        evidence = _safe_json_loads(action_log.evidence_json, {})
        strategy = dict(evidence.get("strategy_decision") or {})
        if not strategy:
            continue
        profile = str(strategy.get("final_strategy_profile") or strategy.get("strategy_profile") or "unknown")
        profile_counts[profile] = profile_counts.get(profile, 0) + 1
        if last_strategy is None:
            last_strategy = strategy
        if previous_profile is not None and previous_profile != profile:
            transition_key = f"{previous_profile}->{profile}"
            profile_transitions[transition_key] = profile_transitions.get(transition_key, 0) + 1
        previous_profile = profile
        if profile == "micro_adjustment":
            context = str(strategy.get("current_context") or "unknown")
            micro_contexts[context] = micro_contexts.get(context, 0) + 1
        if profile in {"micro_adjustment", "restricted_adjustment", "observe_only_strategy"}:
            restriction_profiles += 1
        for item in strategy.get("restricted_parameters") or []:
            restricted_parameters[str(item)] = restricted_parameters.get(str(item), 0) + 1
        if bool(strategy.get("strategy_hysteresis_applied", False)):
            hysteresis_events += 1
        if bool(strategy.get("strategy_conflict_resolved", False)):
            conflict_count += 1
        controls = dict(strategy.get("strategy_controls") or {})
        if controls:
            total_controls += 1
            total_step_multiplier += float(controls.get("effective_step_multiplier") or 0.0)
            total_cooldown_hours += float(controls.get("effective_cooldown_hours") or 0.0)

    total_profiles = sum(profile_counts.values())
    transition_count = sum(profile_transitions.values())
    stability_score, stability_label = _compute_strategy_stability(
        total_profiles=total_profiles,
        transition_count=transition_count,
        hysteresis_events=hysteresis_events,
        conflict_count=conflict_count,
        restriction_profiles=restriction_profiles,
    )

    return {
        "strategy_profile_current": str((last_strategy or {}).get("final_strategy_profile") or (last_strategy or {}).get("strategy_profile") or "unknown"),
        "strategy_controls_current": dict((last_strategy or {}).get("strategy_controls") or {}),
        "strategy_profiles_used": profile_counts,
        "strategy_profile_rates": {
            key: round(value / total_profiles, 4) if total_profiles else 0.0
            for key, value in profile_counts.items()
        },
        "strategy_profile_transitions": profile_transitions,
        "strategy_transition_summary": {
            "total_transitions": transition_count,
            "most_recent_profile": str((last_strategy or {}).get("final_strategy_profile") or (last_strategy or {}).get("strategy_profile") or "unknown"),
        },
        "parameters_most_restricted": restricted_parameters,
        "micro_adjustment_contexts": micro_contexts,
        "strategy_override_applied": bool((last_strategy or {}).get("strategy_override_applied", False)),
        "strategy_hysteresis_events": hysteresis_events,
        "strategy_conflict_count": conflict_count,
        "strategy_restriction_rate": round(restriction_profiles / total_profiles, 4) if total_profiles else 0.0,
        "micro_adjustment_rate": round(profile_counts.get("micro_adjustment", 0) / total_profiles, 4) if total_profiles else 0.0,
        "restricted_adjustment_rate": round(profile_counts.get("restricted_adjustment", 0) / total_profiles, 4) if total_profiles else 0.0,
        "observe_only_strategy_rate": round(profile_counts.get("observe_only_strategy", 0) / total_profiles, 4) if total_profiles else 0.0,
        "average_effective_step_multiplier": round(total_step_multiplier / total_controls, 4) if total_controls else 0.0,
        "average_effective_cooldown_hours": round(total_cooldown_hours / total_controls, 4) if total_controls else 0.0,
        "strategy_stability_score": stability_score,
        "strategy_stability_label": stability_label,
    }


def summarize_strategy_decision(
    *,
    strategy_snapshot: dict[str, Any],
    current_context: str,
) -> dict[str, Any]:
    adapted_candidates = list(strategy_snapshot.get("adapted_candidates") or [])
    restricted_parameters = [
        str(item.get("parameter_name") or "")
        for item in adapted_candidates
        if item.get("blocked") and any(str(reason).startswith("strategy_") for reason in item.get("blocked_reasons") or [])
    ]
    return {
        "strategy_profile": strategy_snapshot.get("final_strategy_profile") or strategy_snapshot.get("strategy_profile"),
        "strategy_reasoning": list(strategy_snapshot.get("strategy_reasoning") or []),
        "strategy_controls": dict(strategy_snapshot.get("strategy_controls") or {}),
        "strategy_risk_flags": list(strategy_snapshot.get("strategy_risk_flags") or []),
        "strategy_override_applied": bool(strategy_snapshot.get("strategy_override_applied", False)),
        "strategy_support_level": strategy_snapshot.get("strategy_support_level"),
        "current_context": current_context,
        "restricted_parameters": restricted_parameters,
        "base_strategy_profile": strategy_snapshot.get("base_strategy_profile"),
        "final_strategy_profile": strategy_snapshot.get("final_strategy_profile"),
        "strategy_transition_reason": strategy_snapshot.get("strategy_transition_reason"),
        "strategy_hysteresis_applied": bool(strategy_snapshot.get("strategy_hysteresis_applied", False)),
        "strategy_hysteresis_state": dict(strategy_snapshot.get("strategy_hysteresis_state") or {}),
    }


def resolve_final_tuning_action(
    *,
    meta_recommended_action: str,
    strategy_recommended_action: str,
) -> dict[str, Any]:
    precedence = {
        "apply": 0,
        "simulate": 1,
        "observe_only": 2,
        "block": 3,
    }
    meta_action = str(meta_recommended_action or "observe_only")
    strategy_action = str(strategy_recommended_action or meta_action)
    if precedence.get(strategy_action, 2) > precedence.get(meta_action, 2):
        final_action = strategy_action
        return {
            "meta_recommended_action": meta_action,
            "strategy_recommended_action": strategy_action,
            "final_resolved_action": final_action,
            "decision_precedence": "strategy_hardens_meta",
            "strategy_conflict_resolved": True,
            "strategy_conflict_reason": "strategy layer can only preserve or harden meta-policy",
        }
    if precedence.get(strategy_action, 2) < precedence.get(meta_action, 2):
        return {
            "meta_recommended_action": meta_action,
            "strategy_recommended_action": strategy_action,
            "final_resolved_action": meta_action,
            "decision_precedence": "meta_dominates",
            "strategy_conflict_resolved": True,
            "strategy_conflict_reason": "strategy layer cannot relax a stricter meta-policy decision",
        }
    return {
        "meta_recommended_action": meta_action,
        "strategy_recommended_action": strategy_action,
        "final_resolved_action": meta_action,
        "decision_precedence": "aligned",
        "strategy_conflict_resolved": False,
        "strategy_conflict_reason": None,
    }


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


def _compute_strategy_stability(
    *,
    total_profiles: int,
    transition_count: int,
    hysteresis_events: int,
    conflict_count: int,
    restriction_profiles: int,
) -> tuple[float, str]:
    if total_profiles <= 0:
        return 1.0, "stable"
    transition_penalty = min(transition_count / total_profiles, 1.0) * 0.45
    hysteresis_penalty = min(hysteresis_events / total_profiles, 1.0) * 0.25
    conflict_penalty = min(conflict_count / total_profiles, 1.0) * 0.2
    restriction_credit = min(restriction_profiles / total_profiles, 1.0) * 0.1
    score = round(max(0.0, min(1.0, 1.0 - transition_penalty - hysteresis_penalty - conflict_penalty + restriction_credit)), 4)
    if score >= 0.72:
        return score, "stable"
    if score >= 0.45:
        return score, "mixed"
    return score, "unstable"
