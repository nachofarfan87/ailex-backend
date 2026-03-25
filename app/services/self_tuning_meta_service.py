from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.services.self_tuning_constants import (
    DEFAULT_SELF_TUNING_MODE,
    ROLLBACK_PRESSURE_BLOCK_RATIO,
    SELF_TUNING_EVENT_TYPE,
)
from app.services.self_tuning_meta_constants import (
    META_BUCKET_HIGH,
    META_BUCKET_LOW,
    META_BUCKET_MEDIUM,
    META_CONFIDENCE_HIGH,
    META_CONFIDENCE_LOW,
    META_CONFIDENCE_MEDIUM,
    META_CONTEXT_DRIFT,
    META_CONTEXT_FRAGILE,
    META_CONTEXT_LOW_EVIDENCE,
    META_CONTEXT_ROLLBACK_PRESSURE,
    META_CONTEXT_STABLE,
    META_HISTORY_LIMIT,
    META_MIN_CONTEXT_RECORDS,
    META_MIN_CONTEXT_WEIGHTED_RECORDS,
    META_MIN_MODE_CYCLES,
    META_MIN_MODE_KNOWN_OUTCOMES,
    META_TEMPORAL_WEIGHT_OLD,
    META_TEMPORAL_WEIGHT_RECENT,
    META_TEMPORAL_WEIGHT_RECENT_HOURS,
    META_TEMPORAL_WEIGHT_WEEK,
    META_TEMPORAL_WEIGHT_WEEK_HOURS,
)
from app.services.self_tuning_meta_policy import apply_meta_to_candidates, build_meta_signals, evaluate_meta_policy
from app.services.utc import utc_now


def collect_self_tuning_strategy_memory(
    db: Session,
    *,
    limit: int = META_HISTORY_LIMIT,
) -> dict[str, Any]:
    action_logs = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == SELF_TUNING_EVENT_TYPE)
        .order_by(LearningActionLog.created_at.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    cycle_records: list[dict[str, Any]] = []
    parameter_records: list[dict[str, Any]] = []
    now = utc_now()

    for action_log in action_logs:
        evidence = _safe_json_loads(action_log.evidence_json, {})
        changes = _safe_json_loads(action_log.changes_applied_json, {})
        status = str(changes.get("status") or _infer_status(action_log)).strip().lower()
        signals_snapshot = dict(evidence.get("signals_snapshot") or changes.get("signals_snapshot") or {})
        risk_flags = list(evidence.get("risk_flags") or [])
        meta_decision = dict(evidence.get("meta_decision") or {})
        requested_mode = str(
            meta_decision.get("requested_mode")
            or evidence.get("aggressiveness_mode_requested")
            or evidence.get("aggressiveness_mode")
            or DEFAULT_SELF_TUNING_MODE
        )
        effective_mode = str(
            meta_decision.get("recommended_mode")
            or evidence.get("aggressiveness_mode_effective")
            or evidence.get("aggressiveness_mode")
            or requested_mode
        )
        confidence_score = float(action_log.confidence_score or 0.0)
        effectiveness = _resolve_tuning_effectiveness(action_log)
        rollback_pressure = _has_rollback_pressure(signals_snapshot=signals_snapshot, risk_flags=risk_flags)
        drift_context = _has_drift_context(signals_snapshot=signals_snapshot, risk_flags=risk_flags)
        temporal_weight = _resolve_temporal_weight(created_at=action_log.created_at, now=now)
        dominant_context = _resolve_dominant_context(
            signals_snapshot=signals_snapshot,
            rollback_pressure=rollback_pressure,
            drift_context=drift_context,
        )

        cycle_records.append(
            {
                "status": status,
                "requested_mode": requested_mode,
                "effective_mode": effective_mode,
                "base_recommended_action": str(meta_decision.get("base_recommended_action") or ""),
                "final_recommended_action": str(meta_decision.get("final_recommended_action") or ""),
                "effectiveness": effectiveness,
                "rollback_pressure": rollback_pressure,
                "drift_context": drift_context,
                "dominant_context": dominant_context,
                "trend_stability_bucket": _bucketize_float(signals_snapshot.get("trend_stability")),
                "consistency_bucket": _bucketize_float(signals_snapshot.get("consistency")),
                "confidence_bucket": _bucketize_float(confidence_score),
                "confidence_score": confidence_score,
                "temporal_weight": temporal_weight,
                "created_at": action_log.created_at,
            }
        )

        applied_adjustments = list(changes.get("applied_adjustments") or [])
        candidate_adjustments = list(changes.get("candidate_adjustments") or [])
        records_source = candidate_adjustments or applied_adjustments
        applied_parameter_keys = {
            (str(item.get("parameter_name") or ""), str(item.get("direction") or ""))
            for item in applied_adjustments
        }

        for item in records_source:
            parameter_name = str(item.get("parameter_name") or "")
            direction = str(item.get("direction") or "")
            if not parameter_name:
                continue
            parameter_status = _resolve_parameter_status(
                cycle_status=status,
                parameter_key=(parameter_name, direction),
                applied_parameter_keys=applied_parameter_keys,
                candidate=item,
            )
            parameter_records.append(
                {
                    "parameter_name": parameter_name,
                    "direction": direction,
                    "status": parameter_status,
                    "effective_mode": effective_mode,
                    "requested_mode": requested_mode,
                    "effectiveness": effectiveness if parameter_status == "applied" else "unknown",
                    "rollback_pressure": rollback_pressure,
                    "drift_context": drift_context,
                    "dominant_context": dominant_context,
                    "trend_stability_bucket": _bucketize_float(signals_snapshot.get("trend_stability")),
                    "consistency_bucket": _bucketize_float(signals_snapshot.get("consistency")),
                    "confidence_bucket": _bucketize_float(item.get("confidence", confidence_score)),
                    "confidence_score": float(item.get("confidence", confidence_score) or 0.0),
                    "temporal_weight": temporal_weight,
                    "created_at": action_log.created_at,
                }
            )

    parameter_performance = _aggregate_parameter_performance(parameter_records)
    mode_performance = _aggregate_mode_performance(cycle_records)
    context_performance = _aggregate_context_performance(cycle_records)
    history_window_summary = _aggregate_history_window_summary(cycle_records)
    meta_confidence, meta_confidence_reasoning = _compute_meta_confidence(
        history_window_summary=history_window_summary,
        mode_performance=mode_performance,
    )

    return {
        "parameter_records": parameter_records,
        "cycle_records": cycle_records,
        "parameter_performance": parameter_performance,
        "mode_performance": mode_performance,
        "context_performance": context_performance,
        "history_window_summary": history_window_summary,
        "meta_confidence": meta_confidence,
        "meta_confidence_reasoning": meta_confidence_reasoning,
        "meta_confidence_components": history_window_summary.get("meta_confidence_components", {}),
    }


def build_self_tuning_meta_snapshot(
    db: Session,
    *,
    current_recommendation: dict[str, Any] | None,
    current_signals: dict[str, Any] | None,
    requested_mode: str,
    dry_run: bool,
    limit: int = META_HISTORY_LIMIT,
) -> dict[str, Any]:
    strategy_memory = collect_self_tuning_strategy_memory(db, limit=limit)
    meta_signals = build_meta_signals(
        strategy_memory=strategy_memory,
        current_recommendation=current_recommendation,
        current_signals=current_signals,
        requested_mode=requested_mode,
    )
    meta_decision = evaluate_meta_policy(
        meta_signals=meta_signals,
        dry_run=dry_run,
    )
    adjusted_candidates = apply_meta_to_candidates(
        candidates=list((current_recommendation or {}).get("candidate_adjustments") or []),
        parameter_assessments=dict(meta_signals.get("parameter_assessments") or {}),
    )
    top_effective_parameters = _select_top_parameters(
        parameter_performance=strategy_memory["parameter_performance"],
        reverse=True,
    )
    top_risky_parameters = _select_top_parameters(
        parameter_performance=strategy_memory["parameter_performance"],
        reverse=False,
    )

    return {
        "meta_status": meta_decision["meta_status"],
        "meta_reasoning": meta_decision["meta_reasoning"],
        "meta_risk_flags": list(meta_decision.get("meta_risk_flags") or []),
        "recommended_mode": meta_decision["recommended_mode"],
        "recommended_action": meta_decision["recommended_action"],
        "historical_support": dict(meta_decision.get("historical_support") or {}),
        "meta_signals": meta_signals,
        "parameter_assessments": meta_signals.get("parameter_assessments") or {},
        "adjusted_candidates": adjusted_candidates,
        "top_effective_parameters": top_effective_parameters,
        "top_risky_parameters": top_risky_parameters,
        "mode_performance": strategy_memory["mode_performance"],
        "parameter_performance": strategy_memory["parameter_performance"],
        "context_performance": strategy_memory["context_performance"],
        "history_window_summary": strategy_memory["history_window_summary"],
        "meta_confidence": strategy_memory["meta_confidence"],
        "meta_confidence_reasoning": strategy_memory["meta_confidence_reasoning"],
        "meta_confidence_components": strategy_memory.get("meta_confidence_components") or {},
        "mode_evidence_status": {
            mode: bucket.get("evidence_status", "insufficient_mode_evidence")
            for mode, bucket in strategy_memory["mode_performance"].items()
        },
        "override_summary": _aggregate_override_summary(cycle_records=strategy_memory["cycle_records"]),
    }


def get_self_tuning_meta_summary(
    db: Session,
    *,
    limit: int = META_HISTORY_LIMIT,
) -> dict[str, Any]:
    snapshot = build_self_tuning_meta_snapshot(
        db,
        current_recommendation=None,
        current_signals=None,
        requested_mode=DEFAULT_SELF_TUNING_MODE,
        dry_run=True,
        limit=limit,
    )
    return {
        "recommended_mode": snapshot["recommended_mode"],
        "recommended_action": snapshot["recommended_action"],
        "meta_status": snapshot["meta_status"],
        "meta_reasoning": snapshot["meta_reasoning"],
        "meta_risk_flags": snapshot["meta_risk_flags"],
        "meta_confidence": snapshot["meta_confidence"],
        "meta_confidence_reasoning": snapshot["meta_confidence_reasoning"],
        "meta_confidence_components": snapshot.get("meta_confidence_components") or {},
        "top_effective_parameters": snapshot["top_effective_parameters"],
        "top_risky_parameters": snapshot["top_risky_parameters"],
        "mode_performance": snapshot["mode_performance"],
        "parameter_performance": snapshot["parameter_performance"],
        "context_performance": snapshot["context_performance"],
        "history_window_summary": snapshot["history_window_summary"],
        "mode_evidence_status": snapshot["mode_evidence_status"],
        "override_summary": snapshot["override_summary"],
    }


def _aggregate_parameter_performance(parameter_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    performance: dict[str, dict[str, Any]] = {}
    for record in parameter_records:
        parameter_name = str(record.get("parameter_name") or "")
        if not parameter_name:
            continue
        bucket = performance.setdefault(
            parameter_name,
            {
                "parameter_name": parameter_name,
                "total_records": 0,
                "weighted_total_records": 0.0,
                "applied_count": 0,
                "blocked_count": 0,
                "simulated_count": 0,
                "observe_only_count": 0,
                "effective": 0,
                "ineffective": 0,
                "unknown": 0,
                "weighted_effective": 0.0,
                "weighted_ineffective": 0.0,
                "weighted_unknown": 0.0,
                "rollback_pressure_count": 0,
                "weighted_rollback_pressure": 0.0,
                "drift_context_count": 0,
                "high_confidence_bad_outcome_count": 0,
                "confidence_total": 0.0,
                "context_performance": {},
            },
        )
        status = str(record.get("status") or "unknown")
        effectiveness = str(record.get("effectiveness") or "unknown")
        confidence_score = float(record.get("confidence_score") or 0.0)
        temporal_weight = float(record.get("temporal_weight") or 0.0)
        dominant_context = str(record.get("dominant_context") or META_CONTEXT_STABLE)
        bucket["total_records"] += 1
        bucket["weighted_total_records"] += temporal_weight
        bucket["confidence_total"] += confidence_score
        if status == "applied":
            bucket["applied_count"] += 1
        elif status == "simulated":
            bucket["simulated_count"] += 1
        elif status == "observe_only":
            bucket["observe_only_count"] += 1
        else:
            bucket["blocked_count"] += 1
        if effectiveness == "effective":
            bucket["effective"] += 1
            bucket["weighted_effective"] += temporal_weight
        elif effectiveness == "ineffective":
            bucket["ineffective"] += 1
            bucket["weighted_ineffective"] += temporal_weight
        else:
            bucket["unknown"] += 1
            bucket["weighted_unknown"] += temporal_weight
        if record.get("rollback_pressure"):
            bucket["rollback_pressure_count"] += 1
            bucket["weighted_rollback_pressure"] += temporal_weight
        if record.get("drift_context"):
            bucket["drift_context_count"] += 1
        if confidence_score >= 0.75 and effectiveness == "ineffective":
            bucket["high_confidence_bad_outcome_count"] += 1

        context_bucket = bucket["context_performance"].setdefault(
            dominant_context,
            {
                "context": dominant_context,
                "total_records": 0,
                "weighted_total_records": 0.0,
                "effective": 0,
                "ineffective": 0,
                "unknown": 0,
                "weighted_effective": 0.0,
                "weighted_ineffective": 0.0,
                "weighted_unknown": 0.0,
                "weighted_rollback_pressure": 0.0,
                "known_outcomes": 0,
            },
        )
        context_bucket["total_records"] += 1
        context_bucket["weighted_total_records"] += temporal_weight
        if effectiveness == "effective":
            context_bucket["effective"] += 1
            context_bucket["weighted_effective"] += temporal_weight
            context_bucket["known_outcomes"] += 1
        elif effectiveness == "ineffective":
            context_bucket["ineffective"] += 1
            context_bucket["weighted_ineffective"] += temporal_weight
            context_bucket["known_outcomes"] += 1
        else:
            context_bucket["unknown"] += 1
            context_bucket["weighted_unknown"] += temporal_weight
        if record.get("rollback_pressure"):
            context_bucket["weighted_rollback_pressure"] += temporal_weight

    for bucket in performance.values():
        known_outcomes = bucket["effective"] + bucket["ineffective"]
        weighted_known_outcomes = bucket["weighted_effective"] + bucket["weighted_ineffective"]
        bucket["known_outcomes"] = known_outcomes
        bucket["weighted_known_outcomes"] = round(weighted_known_outcomes, 4)
        bucket["success_rate"] = _ratio(bucket["effective"], known_outcomes)
        bucket["failure_rate"] = _ratio(bucket["ineffective"], known_outcomes)
        bucket["unknown_outcome_rate"] = _ratio(bucket["unknown"], bucket["total_records"])
        bucket["weighted_success_rate"] = _weighted_ratio(bucket["weighted_effective"], weighted_known_outcomes)
        bucket["weighted_failure_rate"] = _weighted_ratio(bucket["weighted_ineffective"], weighted_known_outcomes)
        bucket["weighted_unknown_outcome_rate"] = _weighted_ratio(bucket["weighted_unknown"], bucket["weighted_total_records"])
        bucket["rollback_after_tuning_rate"] = _ratio(bucket["rollback_pressure_count"], max(bucket["applied_count"], 1))
        bucket["weighted_rollback_rate"] = _weighted_ratio(bucket["weighted_rollback_pressure"], bucket["weighted_total_records"])
        bucket["safe_cycles_after_tuning"] = max(bucket["effective"] - bucket["rollback_pressure_count"], 0)
        bucket["average_confidence"] = round(bucket["confidence_total"] / max(bucket["total_records"], 1), 4)
        bucket["meta_score"] = round(
            bucket["weighted_success_rate"] * 0.55
            - bucket["weighted_failure_rate"] * 0.65
            - bucket["weighted_rollback_rate"] * 0.4
            - bucket["weighted_unknown_outcome_rate"] * 0.2,
            4,
        )
        for context_bucket in bucket["context_performance"].values():
            context_weighted_known = context_bucket["weighted_effective"] + context_bucket["weighted_ineffective"]
            context_bucket["weighted_success_rate"] = _weighted_ratio(context_bucket["weighted_effective"], context_weighted_known)
            context_bucket["weighted_failure_rate"] = _weighted_ratio(context_bucket["weighted_ineffective"], context_weighted_known)
            context_bucket["weighted_unknown_outcome_rate"] = _weighted_ratio(
                context_bucket["weighted_unknown"],
                context_bucket["weighted_total_records"],
            )
            context_bucket["evidence_status"] = _resolve_context_evidence_status(context_bucket)
            context_bucket["weighted_rollback_rate"] = _weighted_ratio(
                context_bucket["weighted_rollback_pressure"],
                context_bucket["weighted_total_records"],
            )
            context_bucket["context_meta_score"] = round(
                context_bucket["weighted_success_rate"] * 0.55
                - context_bucket["weighted_failure_rate"] * 0.65
                - context_bucket["weighted_rollback_rate"] * 0.4
                - context_bucket["weighted_unknown_outcome_rate"] * 0.2,
                4,
            )
        bucket.pop("confidence_total", None)
    return performance


def _aggregate_mode_performance(cycle_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    performance: dict[str, dict[str, Any]] = {}
    for record in cycle_records:
        mode = str(record.get("effective_mode") or DEFAULT_SELF_TUNING_MODE)
        bucket = performance.setdefault(
            mode,
            {
                "mode": mode,
                "total_cycles": 0,
                "weighted_total_cycles": 0.0,
                "applied_count": 0,
                "blocked_count": 0,
                "simulated_count": 0,
                "observe_only_count": 0,
                "effective": 0,
                "ineffective": 0,
                "unknown": 0,
                "weighted_effective": 0.0,
                "weighted_ineffective": 0.0,
                "weighted_unknown": 0.0,
                "rollback_pressure_count": 0,
                "weighted_rollback_pressure": 0.0,
                "drift_context_count": 0,
                "confidence_total": 0.0,
            },
        )
        status = str(record.get("status") or "unknown")
        effectiveness = str(record.get("effectiveness") or "unknown")
        temporal_weight = float(record.get("temporal_weight") or 0.0)
        bucket["total_cycles"] += 1
        bucket["weighted_total_cycles"] += temporal_weight
        bucket["confidence_total"] += float(record.get("confidence_score") or 0.0)
        if status == "applied":
            bucket["applied_count"] += 1
        elif status == "simulated":
            bucket["simulated_count"] += 1
        elif status == "observe_only":
            bucket["observe_only_count"] += 1
        else:
            bucket["blocked_count"] += 1
        if effectiveness == "effective":
            bucket["effective"] += 1
            bucket["weighted_effective"] += temporal_weight
        elif effectiveness == "ineffective":
            bucket["ineffective"] += 1
            bucket["weighted_ineffective"] += temporal_weight
        else:
            bucket["unknown"] += 1
            bucket["weighted_unknown"] += temporal_weight
        if record.get("rollback_pressure"):
            bucket["rollback_pressure_count"] += 1
            bucket["weighted_rollback_pressure"] += temporal_weight
        if record.get("drift_context"):
            bucket["drift_context_count"] += 1

    for bucket in performance.values():
        known_outcomes = bucket["effective"] + bucket["ineffective"]
        weighted_known_outcomes = bucket["weighted_effective"] + bucket["weighted_ineffective"]
        bucket["known_outcomes"] = known_outcomes
        bucket["weighted_known_outcomes"] = round(weighted_known_outcomes, 4)
        bucket["success_rate"] = _ratio(bucket["effective"], known_outcomes)
        bucket["failure_rate"] = _ratio(bucket["ineffective"], known_outcomes)
        bucket["unknown_outcome_rate"] = _ratio(bucket["unknown"], bucket["total_cycles"])
        bucket["weighted_success_rate"] = _weighted_ratio(bucket["weighted_effective"], weighted_known_outcomes)
        bucket["weighted_failure_rate"] = _weighted_ratio(bucket["weighted_ineffective"], weighted_known_outcomes)
        bucket["weighted_unknown_outcome_rate"] = _weighted_ratio(bucket["weighted_unknown"], bucket["weighted_total_cycles"])
        bucket["rollback_after_tuning_rate"] = _ratio(bucket["rollback_pressure_count"], max(bucket["applied_count"], 1))
        bucket["weighted_rollback_rate"] = _weighted_ratio(bucket["weighted_rollback_pressure"], bucket["weighted_total_cycles"])
        bucket["average_confidence"] = round(bucket["confidence_total"] / max(bucket["total_cycles"], 1), 4)
        bucket["evidence_status"] = _resolve_mode_evidence_status(bucket)
        bucket.pop("confidence_total", None)
    return performance


def _aggregate_history_window_summary(cycle_records: list[dict[str, Any]]) -> dict[str, Any]:
    total_cycles = len(cycle_records)
    weighted_total_cycles = sum(float(item.get("temporal_weight") or 0.0) for item in cycle_records)
    applied_count = sum(1 for item in cycle_records if item.get("status") == "applied")
    blocked_count = sum(1 for item in cycle_records if item.get("status") == "blocked")
    simulated_count = sum(1 for item in cycle_records if item.get("status") == "simulated")
    observe_only_count = sum(1 for item in cycle_records if item.get("status") == "observe_only")
    effective = sum(1 for item in cycle_records if item.get("effectiveness") == "effective")
    ineffective = sum(1 for item in cycle_records if item.get("effectiveness") == "ineffective")
    unknown = sum(1 for item in cycle_records if item.get("effectiveness") == "unknown")
    weighted_effective = sum(float(item.get("temporal_weight") or 0.0) for item in cycle_records if item.get("effectiveness") == "effective")
    weighted_ineffective = sum(float(item.get("temporal_weight") or 0.0) for item in cycle_records if item.get("effectiveness") == "ineffective")
    weighted_unknown = sum(float(item.get("temporal_weight") or 0.0) for item in cycle_records if item.get("effectiveness") == "unknown")
    known_outcomes = effective + ineffective
    weighted_known_outcomes = weighted_effective + weighted_ineffective
    rollback_pressure_count = sum(1 for item in cycle_records if item.get("rollback_pressure"))
    weighted_rollback_pressure = sum(float(item.get("temporal_weight") or 0.0) for item in cycle_records if item.get("rollback_pressure"))
    high_confidence_bad_outcome_count = sum(
        1
        for item in cycle_records
        if float(item.get("confidence_score") or 0.0) >= 0.75 and item.get("effectiveness") == "ineffective"
    )
    context_counts = {
        META_CONTEXT_STABLE: 0.0,
        META_CONTEXT_FRAGILE: 0.0,
        META_CONTEXT_ROLLBACK_PRESSURE: 0.0,
        META_CONTEXT_DRIFT: 0.0,
        META_CONTEXT_LOW_EVIDENCE: 0.0,
    }
    for item in cycle_records:
        context = str(item.get("dominant_context") or META_CONTEXT_STABLE)
        context_counts[context] = context_counts.get(context, 0.0) + float(item.get("temporal_weight") or 0.0)
    return {
        "total_cycles": total_cycles,
        "weighted_total_cycles": round(weighted_total_cycles, 4),
        "applied_count": applied_count,
        "blocked_count": blocked_count,
        "simulated_count": simulated_count,
        "observe_only_count": observe_only_count,
        "known_outcomes": known_outcomes,
        "weighted_known_outcomes": round(weighted_known_outcomes, 4),
        "effective": effective,
        "ineffective": ineffective,
        "unknown": unknown,
        "ineffective_tuning_rate": _ratio(ineffective, known_outcomes),
        "unknown_outcome_rate": _ratio(unknown, total_cycles),
        "rollback_after_tuning_rate": _ratio(rollback_pressure_count, max(applied_count, 1)),
        "weighted_success_rate": _weighted_ratio(weighted_effective, weighted_known_outcomes),
        "weighted_failure_rate": _weighted_ratio(weighted_ineffective, weighted_known_outcomes),
        "weighted_unknown_outcome_rate": _weighted_ratio(weighted_unknown, weighted_total_cycles),
        "weighted_rollback_rate": _weighted_ratio(weighted_rollback_pressure, weighted_total_cycles),
        "high_confidence_bad_outcome_rate": _ratio(high_confidence_bad_outcome_count, max(known_outcomes, 1)),
        "safe_cycles_after_tuning": max(effective - rollback_pressure_count, 0),
        "context_weight_distribution": {key: round(value, 4) for key, value in context_counts.items()},
    }


def _aggregate_context_performance(cycle_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    performance: dict[str, dict[str, Any]] = {}
    for record in cycle_records:
        context = str(record.get("dominant_context") or META_CONTEXT_STABLE)
        temporal_weight = float(record.get("temporal_weight") or 0.0)
        effectiveness = str(record.get("effectiveness") or "unknown")
        bucket = performance.setdefault(
            context,
            {
                "context": context,
                "total_cycles": 0,
                "weighted_total_cycles": 0.0,
                "weighted_effective": 0.0,
                "weighted_ineffective": 0.0,
                "weighted_unknown": 0.0,
                "known_outcomes": 0,
            },
        )
        bucket["total_cycles"] += 1
        bucket["weighted_total_cycles"] += temporal_weight
        if effectiveness == "effective":
            bucket["weighted_effective"] += temporal_weight
            bucket["known_outcomes"] += 1
        elif effectiveness == "ineffective":
            bucket["weighted_ineffective"] += temporal_weight
            bucket["known_outcomes"] += 1
        else:
            bucket["weighted_unknown"] += temporal_weight

    for bucket in performance.values():
        weighted_known_outcomes = bucket["weighted_effective"] + bucket["weighted_ineffective"]
        bucket["weighted_success_rate"] = _weighted_ratio(bucket["weighted_effective"], weighted_known_outcomes)
        bucket["weighted_failure_rate"] = _weighted_ratio(bucket["weighted_ineffective"], weighted_known_outcomes)
        bucket["weighted_unknown_outcome_rate"] = _weighted_ratio(bucket["weighted_unknown"], bucket["weighted_total_cycles"])
        bucket["evidence_status"] = _resolve_context_evidence_status(bucket)
    return performance


def _compute_meta_confidence(
    *,
    history_window_summary: dict[str, Any],
    mode_performance: dict[str, dict[str, Any]],
) -> tuple[float, list[str]]:
    weighted_known_outcomes = float(history_window_summary.get("weighted_known_outcomes") or 0.0)
    weighted_total_cycles = float(history_window_summary.get("weighted_total_cycles") or 0.0)
    weighted_unknown_outcome_rate = float(history_window_summary.get("weighted_unknown_outcome_rate") or 0.0)
    weighted_failure_rate = float(history_window_summary.get("weighted_failure_rate") or 0.0)
    weighted_success_rate = float(history_window_summary.get("weighted_success_rate") or 0.0)
    weighted_rollback_rate = float(history_window_summary.get("weighted_rollback_rate") or 0.0)
    stable_context_weight = float(history_window_summary.get("context_weight_distribution", {}).get(META_CONTEXT_STABLE, 0.0))
    fragile_context_weight = (
        float(history_window_summary.get("context_weight_distribution", {}).get(META_CONTEXT_FRAGILE, 0.0))
        + float(history_window_summary.get("context_weight_distribution", {}).get(META_CONTEXT_DRIFT, 0.0))
        + float(history_window_summary.get("context_weight_distribution", {}).get(META_CONTEXT_ROLLBACK_PRESSURE, 0.0))
    )
    stable_context_share = stable_context_weight / weighted_total_cycles if weighted_total_cycles > 0 else 0.0
    fragile_context_share = fragile_context_weight / weighted_total_cycles if weighted_total_cycles > 0 else 0.0
    sufficient_modes = sum(1 for bucket in mode_performance.values() if bucket.get("evidence_status") == "sufficient_mode_evidence")

    evidence_component = min(weighted_known_outcomes / 5.0, 1.0) * 0.42
    recency_component = min(weighted_total_cycles / 8.0, 1.0) * 0.18
    stability_component = max(0.0, stable_context_share - fragile_context_share + 0.35) * 0.18
    mode_support_component = min(float(sufficient_modes), 2.0) / 2.0 * 0.12
    outcome_quality_component = min(weighted_success_rate, 1.0) * 0.14
    uncertainty_penalty = min(weighted_unknown_outcome_rate, 1.0) * 0.28
    failure_penalty = min(weighted_failure_rate, 1.0) * 0.2
    rollback_penalty = min(weighted_rollback_rate, 1.0) * 0.22
    confidence = (
        evidence_component
        + recency_component
        + stability_component
        + mode_support_component
        + outcome_quality_component
        - uncertainty_penalty
        - failure_penalty
        - rollback_penalty
    )
    confidence = round(max(0.0, min(1.0, confidence)), 4)
    components = {
        "evidence_component": round(evidence_component, 4),
        "recency_component": round(recency_component, 4),
        "stability_component": round(stability_component, 4),
        "mode_support_component": round(mode_support_component, 4),
        "outcome_quality_component": round(outcome_quality_component, 4),
        "uncertainty_penalty": round(uncertainty_penalty, 4),
        "failure_penalty": round(failure_penalty, 4),
        "rollback_penalty": round(rollback_penalty, 4),
    }
    history_window_summary["meta_confidence_components"] = components

    reasoning = [
        f"weighted_known_outcomes={round(weighted_known_outcomes, 4)}",
        f"weighted_total_cycles={round(weighted_total_cycles, 4)}",
        f"weighted_unknown_outcome_rate={round(weighted_unknown_outcome_rate, 4)}",
        f"weighted_success_rate={round(weighted_success_rate, 4)}",
        f"weighted_failure_rate={round(weighted_failure_rate, 4)}",
        f"weighted_rollback_rate={round(weighted_rollback_rate, 4)}",
        f"stable_context_share={round(stable_context_share, 4)}",
        f"sufficient_modes={sufficient_modes}",
        f"evidence_component={components['evidence_component']}",
        f"stability_component={components['stability_component']}",
        f"outcome_quality_component={components['outcome_quality_component']}",
        f"uncertainty_penalty={components['uncertainty_penalty']}",
        f"rollback_penalty={components['rollback_penalty']}",
    ]
    if confidence < META_CONFIDENCE_LOW:
        reasoning.append("meta_confidence_level=low")
    elif confidence < META_CONFIDENCE_MEDIUM:
        reasoning.append("meta_confidence_level=medium")
    elif confidence >= META_CONFIDENCE_HIGH:
        reasoning.append("meta_confidence_level=high")
    else:
        reasoning.append("meta_confidence_level=upper_medium")
    return confidence, reasoning


def _aggregate_override_summary(*, cycle_records: list[dict[str, Any]]) -> dict[str, Any]:
    total_cycles = len(cycle_records)
    action_overrides = 0
    mode_overrides = 0
    both_overrides = 0
    total_overrides = 0
    apply_to_simulate = 0
    apply_to_observe_only = 0
    action_override_count = 0
    mode_override_count = 0
    for record in cycle_records:
        base_action = str(record.get("base_recommended_action") or "")
        final_action = str(record.get("final_recommended_action") or "")
        base_mode = str(record.get("requested_mode") or "")
        final_mode = str(record.get("effective_mode") or "")
        action_changed = bool(base_action and final_action and base_action != final_action)
        mode_changed = bool(base_mode and final_mode and base_mode != final_mode)
        if action_changed:
            action_overrides += 1
            action_override_count += 1
            if base_action == "apply" and final_action == "simulate":
                apply_to_simulate += 1
            if base_action == "apply" and final_action == "observe_only":
                apply_to_observe_only += 1
        if mode_changed:
            mode_overrides += 1
            mode_override_count += 1
        if action_changed and mode_changed:
            both_overrides += 1
        if action_changed or mode_changed:
            total_overrides += 1
    return {
        "meta_override_rate": _ratio(total_overrides, total_cycles),
        "meta_action_override_rate": _ratio(action_overrides, total_cycles),
        "meta_mode_override_rate": _ratio(mode_overrides, total_cycles),
        "override_counts": {
            "total_overrides": total_overrides,
            "action_overrides": action_override_count,
            "mode_overrides": mode_override_count,
            "both_overrides": both_overrides,
            "apply_to_simulate": apply_to_simulate,
            "apply_to_observe_only": apply_to_observe_only,
        },
    }


def _resolve_context_evidence_status(bucket: dict[str, Any]) -> str:
    if int(bucket.get("total_records") or 0) < META_MIN_CONTEXT_RECORDS:
        return "insufficient_context_evidence"
    if float(bucket.get("weighted_total_records") or 0.0) < META_MIN_CONTEXT_WEIGHTED_RECORDS:
        return "insufficient_context_evidence"
    if int(bucket.get("known_outcomes") or 0) < 1:
        return "insufficient_context_evidence"
    return "sufficient_context_evidence"


def _resolve_parameter_status(
    *,
    cycle_status: str,
    parameter_key: tuple[str, str],
    applied_parameter_keys: set[tuple[str, str]],
    candidate: dict[str, Any],
) -> str:
    if parameter_key in applied_parameter_keys:
        return "applied"
    if cycle_status in {"simulated", "observe_only"}:
        return cycle_status
    if bool(candidate.get("blocked")) or cycle_status in {"blocked", "no_data"}:
        return "blocked"
    return cycle_status


def _select_top_parameters(
    *,
    parameter_performance: dict[str, dict[str, Any]],
    reverse: bool,
) -> list[dict[str, Any]]:
    items = list(parameter_performance.values())
    items.sort(
        key=lambda item: (
            float(item.get("meta_score") or 0.0),
            float(item.get("weighted_success_rate") or 0.0),
            -float(item.get("weighted_failure_rate") or 0.0),
            item.get("parameter_name") or "",
        ),
        reverse=reverse,
    )
    top_items = items[:3]
    return [
        {
            "parameter_name": item.get("parameter_name"),
            "meta_score": round(float(item.get("meta_score") or 0.0), 4),
            "weighted_success_rate": round(float(item.get("weighted_success_rate") or 0.0), 4),
            "weighted_failure_rate": round(float(item.get("weighted_failure_rate") or 0.0), 4),
            "weighted_rollback_rate": round(float(item.get("weighted_rollback_rate") or 0.0), 4),
            "known_outcomes": int(item.get("known_outcomes") or 0),
        }
        for item in top_items
    ]


def _resolve_mode_evidence_status(bucket: dict[str, Any]) -> str:
    if int(bucket.get("total_cycles") or 0) < META_MIN_MODE_CYCLES:
        return "insufficient_mode_evidence"
    if int(bucket.get("known_outcomes") or 0) < META_MIN_MODE_KNOWN_OUTCOMES:
        return "insufficient_mode_evidence"
    return "sufficient_mode_evidence"


def _resolve_tuning_effectiveness(action_log: LearningActionLog) -> str:
    impact_status = str(action_log.impact_status or "").strip().lower()
    if impact_status == "improved":
        return "effective"
    if impact_status in {"neutral", "regressed"}:
        return "ineffective"
    return "unknown"


def _infer_status(action_log: LearningActionLog) -> str:
    reason = str(action_log.reason or "").strip().lower()
    if "observe_only" in reason:
        return "observe_only"
    if "simulated" in reason:
        return "simulated"
    if action_log.applied:
        return "applied"
    if "blocked" in reason:
        return "blocked"
    return "blocked"


def _has_rollback_pressure(*, signals_snapshot: dict[str, Any], risk_flags: list[str]) -> bool:
    if "rollback_pressure" in risk_flags:
        return True
    rollback_ratio = float(signals_snapshot.get("rollback_ratio") or 0.0)
    return rollback_ratio >= ROLLBACK_PRESSURE_BLOCK_RATIO


def _has_drift_context(*, signals_snapshot: dict[str, Any], risk_flags: list[str]) -> bool:
    drift_level = str(signals_snapshot.get("drift_level") or "none").strip().lower()
    return drift_level in {"high", "medium"} or "recent_regression" in risk_flags


def _resolve_dominant_context(
    *,
    signals_snapshot: dict[str, Any],
    rollback_pressure: bool,
    drift_context: bool,
) -> str:
    sample_size = int(signals_snapshot.get("sample_size") or 0)
    trend_stability = float(signals_snapshot.get("trend_stability") or 0.0)
    consistency = float(signals_snapshot.get("consistency") or 0.0)
    if rollback_pressure:
        return META_CONTEXT_ROLLBACK_PRESSURE
    if drift_context:
        return META_CONTEXT_DRIFT
    if sample_size and sample_size < 40:
        return META_CONTEXT_LOW_EVIDENCE
    if trend_stability < 0.6 or consistency < 0.6:
        return META_CONTEXT_FRAGILE
    return META_CONTEXT_STABLE


def _resolve_temporal_weight(*, created_at: Any, now: Any) -> float:
    if created_at is None:
        return META_TEMPORAL_WEIGHT_OLD
    elapsed_hours = max((now - created_at).total_seconds() / 3600.0, 0.0)
    if elapsed_hours <= META_TEMPORAL_WEIGHT_RECENT_HOURS:
        return META_TEMPORAL_WEIGHT_RECENT
    if elapsed_hours <= META_TEMPORAL_WEIGHT_WEEK_HOURS:
        return META_TEMPORAL_WEIGHT_WEEK
    return META_TEMPORAL_WEIGHT_OLD


def _bucketize_float(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return META_BUCKET_LOW
    if numeric >= 0.75:
        return META_BUCKET_HIGH
    if numeric >= 0.45:
        return META_BUCKET_MEDIUM
    return META_BUCKET_LOW


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _weighted_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback
