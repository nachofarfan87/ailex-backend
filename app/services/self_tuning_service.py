from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.services import learning_runtime_config
from app.services.learning_governance_service import get_learning_governance_summary
from app.services.learning_impact_service import get_impact_summary
from app.services.learning_observability_service import detect_drift, get_overview
from app.services.learning_runtime_config_store import load_latest_runtime_config, save_runtime_config
from app.services.self_tuning_constants import (
    DEFAULT_SELF_TUNING_MODE,
    SELF_TUNING_EVENT_TYPE,
    SELF_TUNING_MODES,
    SELF_TUNING_RECOMMENDATION_TYPE,
)
from app.services.self_tuning_meta_constants import MODE_ORDER
from app.services.self_tuning_meta_service import build_self_tuning_meta_snapshot, get_self_tuning_meta_summary
from app.services.self_tuning_policy import evaluate_self_tuning_candidates, should_apply_self_tuning
from app.services.self_tuning_human_control import (
    evaluate_human_control_before_execution,
    get_human_control_snapshot,
)
from app.services.self_tuning_strategy_service import (
    build_self_tuning_strategy_snapshot,
    get_self_tuning_strategy_summary,
    resolve_final_tuning_action,
    summarize_strategy_decision,
)
from app.services.utc import utc_now


_current_self_tuning_mode: str = DEFAULT_SELF_TUNING_MODE


def get_self_tuning_mode() -> str:
    return _current_self_tuning_mode


def set_self_tuning_mode(mode: str) -> str:
    global _current_self_tuning_mode
    if mode not in SELF_TUNING_MODES:
        raise ValueError(f"Invalid self-tuning mode '{mode}'. Valid: {list(SELF_TUNING_MODES.keys())}")
    _current_self_tuning_mode = mode
    return _current_self_tuning_mode


def collect_self_tuning_signals(
    db: Session,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    overview = get_overview(db)
    drift = detect_drift(db)
    impact_summary = get_impact_summary(db)
    governance_summary = get_learning_governance_summary(db, limit=limit)
    top_flag_counts = {
        str(item.get("flag") or ""): int(item.get("count") or 0)
        for item in governance_summary.get("top_flags") or []
        if str(item.get("flag") or "").strip()
    }
    total_evaluated = max(int(impact_summary.get("total_evaluated") or 0), 0)
    improved = int(impact_summary.get("improved") or 0)
    regressed = int(impact_summary.get("regressed") or 0)
    neutral = int(impact_summary.get("neutral") or 0)
    audited_count = int(governance_summary.get("audited_count") or 0)
    failed_count = int(governance_summary.get("failed_count") or 0)
    questionable_count = int(governance_summary.get("questionable_count") or 0)
    rollback_candidates = int(governance_summary.get("rollback_candidates") or 0)

    total_outcomes = max(improved + regressed + neutral, 1)
    improvement_rate = float(impact_summary.get("improvement_rate") or 0.0)
    regression_rate = float(impact_summary.get("regression_rate") or 0.0)
    neutral_rate = round(neutral / total_outcomes, 4)

    compared_windows = dict(drift.get("compared_windows") or {})
    recent_window = dict(compared_windows.get("recent") or {})
    previous_window = dict(compared_windows.get("previous") or {})
    recent_avg_score = float(recent_window.get("avg_score") or overview.get("recency_weighted_avg_score") or 0.0)
    previous_avg_score = float(previous_window.get("avg_score") or 0.0)
    historical_avg_score = float(overview.get("avg_impact_score") or 0.0)

    consistency = _compute_consistency(
        improvement_rate=improvement_rate,
        regression_rate=regression_rate,
        neutral_rate=neutral_rate,
    )
    trend_stability = _compute_trend_stability(
        recent_avg_score=recent_avg_score,
        previous_avg_score=previous_avg_score,
        historical_avg_score=historical_avg_score,
        recent_block_rate=float(recent_window.get("block_rate") or 0.0),
        previous_block_rate=float(previous_window.get("block_rate") or 0.0),
    )
    recent_vs_historical_delta = round(recent_avg_score - historical_avg_score, 4)

    return {
        "sample_size": max(
            int(overview.get("total_observations") or 0),
            total_evaluated,
            audited_count,
        ),
        "impact_total": total_evaluated,
        "total_observations": int(overview.get("total_observations") or 0),
        "audited_count": audited_count,
        "improvement_rate": round(improvement_rate, 4),
        "regression_rate": round(regression_rate, 4),
        "neutral_rate": neutral_rate,
        "failed_ratio": round(failed_count / audited_count, 4) if audited_count else 0.0,
        "questionable_ratio": round(questionable_count / audited_count, 4) if audited_count else 0.0,
        "rollback_ratio": round(rollback_candidates / audited_count, 4) if audited_count else 0.0,
        "rollback_candidates": rollback_candidates,
        "recent_avg_score": round(recent_avg_score, 4),
        "previous_avg_score": round(previous_avg_score, 4),
        "historical_avg_score": round(historical_avg_score, 4),
        "recent_vs_historical_delta": recent_vs_historical_delta,
        "trend_stability": trend_stability,
        "consistency": consistency,
        "drift_level": str(drift.get("drift_level") or "none"),
        "drift_detected": bool(drift.get("drift_detected", False)),
        "governance_status": str(governance_summary.get("status") or "healthy"),
        "top_flag_counts": top_flag_counts,
        "overview": overview,
        "impact_summary": impact_summary,
        "governance_summary": governance_summary,
        "drift": drift,
    }


def build_self_tuning_recommendation(
    *,
    signals: dict[str, Any],
    current_controls: dict[str, Any],
    tuning_history: list[dict[str, Any]],
    aggressiveness_mode: str | None = None,
) -> dict[str, Any]:
    mode = aggressiveness_mode or get_self_tuning_mode()
    candidates, blocked_reasons, risk_flags = evaluate_self_tuning_candidates(
        signals=signals,
        current_controls=current_controls,
        tuning_history=tuning_history,
        aggressiveness_mode=mode,
    )
    actionable_candidates = [candidate for candidate in candidates if not candidate["blocked"]]
    summary = _build_summary(
        signals=signals,
        actionable_candidates=actionable_candidates,
        blocked_reasons=blocked_reasons,
    )
    return {
        "summary": summary,
        "candidate_adjustments": candidates,
        "blocked_reasons": blocked_reasons,
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "signals_snapshot": dict(signals or {}),
        "tuning_history_snapshot": _summarize_tuning_history(tuning_history),
        "aggressiveness_mode": mode,
    }


def apply_self_tuning_adjustments(
    db: Session,
    *,
    recommendation: dict[str, Any],
    dry_run: bool,
    persist_trace: bool,
    decision_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actionable_candidates = [
        candidate for candidate in recommendation.get("candidate_adjustments") or []
        if not candidate.get("blocked")
    ]
    override = dict(decision_override or {})
    override_action = str(override.get("recommended_action") or "").strip().lower()

    if override_action == "observe_only":
        confidence = _average_candidate_confidence(actionable_candidates)
        requires_review = True
        previous_runtime_config = dict(load_latest_runtime_config(db) or learning_runtime_config.get_effective_runtime_config())
        action_log_id = None
        if persist_trace:
            action_log = _create_self_tuning_action_log(
                db=db,
                status="observe_only",
                recommendation=recommendation,
                previous_runtime_config=previous_runtime_config,
                effective_runtime_config=previous_runtime_config,
                applied_adjustments=[],
                confidence=confidence,
                requires_review=requires_review,
                applied=False,
            )
            action_log_id = action_log.id
        return {
            "status": "observe_only",
            "applied_adjustments": [],
            "confidence": confidence,
            "requires_review": requires_review,
            "rollback_reference": None,
            "action_log_id": action_log_id,
        }

    if override_action == "block":
        confidence = _average_candidate_confidence(actionable_candidates)
        requires_review = True
        previous_runtime_config = dict(load_latest_runtime_config(db) or learning_runtime_config.get_effective_runtime_config())
        action_log_id = None
        if persist_trace:
            action_log = _create_self_tuning_action_log(
                db=db,
                status="blocked",
                recommendation=recommendation,
                previous_runtime_config=previous_runtime_config,
                effective_runtime_config=previous_runtime_config,
                applied_adjustments=[],
                confidence=confidence,
                requires_review=requires_review,
                applied=False,
            )
            action_log_id = action_log.id
        return {
            "status": "blocked",
            "applied_adjustments": [],
            "confidence": confidence,
            "requires_review": requires_review,
            "rollback_reference": None,
            "action_log_id": action_log_id,
        }

    effective_dry_run = dry_run or override_action == "simulate"
    should_apply, status, confidence, requires_review = should_apply_self_tuning(
        candidates=actionable_candidates,
        blocked_reasons=list(recommendation.get("blocked_reasons") or []),
        dry_run=effective_dry_run,
    )
    previous_runtime_config = dict(load_latest_runtime_config(db) or learning_runtime_config.get_effective_runtime_config())
    applied_adjustments: list[dict[str, Any]] = []
    action_log_id = None

    if should_apply:
        learning_runtime_config.apply_persisted_runtime_config(previous_runtime_config)
        for candidate in actionable_candidates:
            parameter_name = str(candidate["parameter_name"])
            proposed_value = candidate.get("strategy_effective_proposed_value", candidate["proposed_value"])
            effective_delta = candidate.get("strategy_effective_delta", candidate["delta"])
            learning_runtime_config.set_self_tuning_control(parameter_name, proposed_value)
            applied_adjustments.append(
                {
                    "parameter_name": parameter_name,
                    "previous_value": candidate["current_value"],
                    "new_value": proposed_value,
                    "direction": candidate["direction"],
                    "delta": effective_delta,
                    "priority_score": candidate.get("priority_score"),
                    "meta_score": candidate.get("meta_score"),
                    "strategy_priority_score": candidate.get("strategy_priority_score"),
                }
            )
        effective_runtime_config = learning_runtime_config.get_effective_runtime_config()
        save_runtime_config(db, effective_runtime_config)
        if persist_trace:
            action_log = _create_self_tuning_action_log(
                db=db,
                status=status,
                recommendation=recommendation,
                previous_runtime_config=previous_runtime_config,
                effective_runtime_config=effective_runtime_config,
                applied_adjustments=applied_adjustments,
                confidence=confidence,
                requires_review=requires_review,
                applied=True,
            )
            action_log_id = action_log.id
        else:
            db.commit()
    elif persist_trace and status in {"simulated", "blocked", "no_data"}:
        action_log = _create_self_tuning_action_log(
            db=db,
            status=status,
            recommendation=recommendation,
            previous_runtime_config=previous_runtime_config,
            effective_runtime_config=previous_runtime_config,
            applied_adjustments=[],
            confidence=confidence,
            requires_review=requires_review,
            applied=False,
        )
        action_log_id = action_log.id

    return {
        "status": status,
        "applied_adjustments": applied_adjustments,
        "confidence": confidence,
        "requires_review": requires_review,
        "rollback_reference": "manual_runtime_rollback" if should_apply and applied_adjustments else None,
        "action_log_id": action_log_id,
    }


def run_self_tuning_cycle(
    db: Session,
    *,
    dry_run: bool = True,
    limit: int = 100,
    persist_trace: bool = True,
    aggressiveness_mode: str | None = None,
) -> dict[str, Any]:
    requested_mode = aggressiveness_mode or get_self_tuning_mode()
    signals = collect_self_tuning_signals(db, limit=limit)
    current_controls = learning_runtime_config.get_self_tuning_controls()
    tuning_history = _get_recent_tuning_history(db)
    strategy_history = _get_recent_strategy_history(db)
    recommendation = build_self_tuning_recommendation(
        signals=signals,
        current_controls=current_controls,
        tuning_history=tuning_history,
        aggressiveness_mode=requested_mode,
    )
    base_has_actionable = any(not candidate.get("blocked") for candidate in recommendation.get("candidate_adjustments") or [])
    base_recommended_action = _resolve_base_recommended_action(
        recommendation=recommendation,
        dry_run=dry_run,
    )
    meta_snapshot = build_self_tuning_meta_snapshot(
        db,
        current_recommendation=recommendation,
        current_signals=signals,
        requested_mode=requested_mode,
        dry_run=dry_run,
    )
    effective_mode = _resolve_effective_mode(
        requested_mode=requested_mode,
        recommended_mode=str(meta_snapshot.get("recommended_mode") or requested_mode),
    )
    if effective_mode != recommendation.get("aggressiveness_mode"):
        recommendation = build_self_tuning_recommendation(
            signals=signals,
            current_controls=current_controls,
            tuning_history=tuning_history,
            aggressiveness_mode=effective_mode,
        )
        recommendation["meta_decision"] = {
            "requested_mode": requested_mode,
            "recommended_mode": str(meta_snapshot.get("recommended_mode") or effective_mode),
            "recommended_action": str(meta_snapshot.get("recommended_action") or "simulate"),
            "meta_status": str(meta_snapshot.get("meta_status") or "supported"),
        }

    strategy_snapshot = build_self_tuning_strategy_snapshot(
        recommendation=recommendation,
        meta_snapshot=meta_snapshot,
        current_signals=signals,
        tuning_history=tuning_history,
        strategy_history=strategy_history,
    )
    recommendation = _merge_meta_snapshot_into_recommendation(
        recommendation=recommendation,
        meta_snapshot=meta_snapshot,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        base_recommended_action=base_recommended_action,
    )
    recommendation = _merge_strategy_snapshot_into_recommendation(
        recommendation=recommendation,
        strategy_snapshot=strategy_snapshot,
        current_context=str(meta_snapshot.get("meta_signals", {}).get("current_context") or "stable"),
    )
    final_action_trace = _resolve_final_tuning_action(
        meta_snapshot=meta_snapshot,
        strategy_snapshot=strategy_snapshot,
        base_has_actionable=base_has_actionable,
    )
    original_resolved_action = final_action_trace["action_trace"]["final_resolved_action"]
    human_control = evaluate_human_control_before_execution(
        db,
        recommendation=recommendation,
        meta_snapshot=meta_snapshot,
        strategy_snapshot=strategy_snapshot,
        final_action_trace=final_action_trace,
    )
    recommendation = dict(human_control["recommendation"])
    recommendation["strategy_decision"] = {
        **dict(recommendation.get("strategy_decision") or {}),
        **final_action_trace["action_trace"],
    }
    recommendation["human_control"] = {
        "system_mode": human_control["system_mode"],
        "review_required": human_control["review_required"],
        "review_entry_id": human_control["review_entry_id"],
        "review_status": human_control.get("review_status"),
        "applied_overrides": human_control["applied_overrides"],
        "blocked_overrides": human_control["blocked_overrides"],
        "overrides_active": human_control["overrides_active"],
        "human_control_reason": human_control["human_control_reason"],
        "review_queue_size": human_control["review_snapshot"]["review_queue_size"],
        "pending_reviews": human_control["review_snapshot"]["pending_reviews"],
        "human_interventions_last_24h": human_control["human_interventions_last_24h"],
    }
    if human_control["force_decision_override"]:
        final_action_trace["action_trace"]["final_resolved_action"] = human_control["final_action"]
    if human_control["review_required"]:
        final_recommended_action = human_control["final_action"]
        return {
            "status": "review_pending",
            "summary": recommendation["summary"],
            "candidate_adjustments": recommendation["candidate_adjustments"],
            "applied_adjustments": [],
            "blocked_reasons": recommendation["blocked_reasons"],
            "evidence_snapshot": signals,
            "risk_flags": recommendation["risk_flags"],
            "confidence": 0.0,
            "requires_review": True,
            "tuning_decision_reason": recommendation["summary"],
            "rollback_reference": None,
            "meta_status": meta_snapshot.get("meta_status"),
            "meta_reasoning": meta_snapshot.get("meta_reasoning"),
            "meta_risk_flags": meta_snapshot.get("meta_risk_flags"),
            "recommended_mode": meta_snapshot.get("recommended_mode"),
            "recommended_action": final_recommended_action,
            "meta_recommended_action": meta_snapshot.get("recommended_action"),
            "meta_confidence": meta_snapshot.get("meta_confidence"),
            "meta_confidence_reasoning": meta_snapshot.get("meta_confidence_reasoning"),
            "meta_confidence_components": meta_snapshot.get("meta_confidence_components"),
            "historical_support": meta_snapshot.get("historical_support"),
            "meta_signals": meta_snapshot.get("meta_signals"),
            "override_summary": {
                "base_recommended_action": base_recommended_action,
                "final_recommended_action": final_recommended_action,
                "meta_override_applied": base_recommended_action != final_recommended_action or requested_mode != effective_mode,
                "meta_override_reason": meta_snapshot.get("meta_reasoning"),
                "base_mode": requested_mode,
                "final_mode": effective_mode,
            },
            "strategy_profile": strategy_snapshot.get("strategy_profile"),
            "strategy_reasoning": strategy_snapshot.get("strategy_reasoning"),
            "strategy_controls": strategy_snapshot.get("strategy_controls"),
            "strategy_risk_flags": strategy_snapshot.get("strategy_risk_flags"),
            "strategy_override_applied": strategy_snapshot.get("strategy_override_applied"),
            "strategy_support_level": strategy_snapshot.get("strategy_support_level"),
            "strategy_recommended_action": strategy_snapshot.get("recommended_action"),
            "base_strategy_profile": strategy_snapshot.get("base_strategy_profile"),
            "final_strategy_profile": strategy_snapshot.get("final_strategy_profile"),
            "strategy_transition_reason": strategy_snapshot.get("strategy_transition_reason"),
            "strategy_hysteresis_applied": strategy_snapshot.get("strategy_hysteresis_applied"),
            "strategy_hysteresis_state": strategy_snapshot.get("strategy_hysteresis_state"),
            "final_resolved_action": final_recommended_action,
            "decision_precedence": final_action_trace["action_trace"]["decision_precedence"],
            "strategy_conflict_resolved": final_action_trace["action_trace"]["strategy_conflict_resolved"],
            "strategy_conflict_reason": final_action_trace["action_trace"]["strategy_conflict_reason"],
            "human_control": recommendation["human_control"],
            "review_queue_size": recommendation["human_control"]["review_queue_size"],
            "pending_reviews": recommendation["human_control"]["pending_reviews"],
            "overrides_active": recommendation["human_control"]["overrides_active"],
            "system_mode": recommendation["human_control"]["system_mode"],
            "human_interventions_last_24h": recommendation["human_control"]["human_interventions_last_24h"],
            "metadata": {
                "dry_run": bool(dry_run),
                "action_log_id": None,
                "evaluated_at": utc_now().isoformat(),
                "self_tuning_mode": requested_mode,
                "effective_self_tuning_mode": effective_mode,
            },
        }
    outcome = apply_self_tuning_adjustments(
        db,
        recommendation=recommendation,
        dry_run=dry_run,
        persist_trace=persist_trace,
        decision_override=(
            {
                **dict(final_action_trace["decision_override"] or {}),
                "recommended_action": human_control["final_action"],
            }
            if human_control["force_decision_override"]
            else final_action_trace["decision_override"]
        ),
    )
    final_recommended_action = _status_to_recommended_action(outcome["status"])
    meta_override_applied = (
        base_recommended_action != final_recommended_action
        or requested_mode != effective_mode
    )
    override_summary = {
        "base_recommended_action": base_recommended_action,
        "final_recommended_action": final_recommended_action,
        "meta_override_applied": meta_override_applied,
        "meta_override_reason": meta_snapshot.get("meta_reasoning") if meta_override_applied else None,
        "base_mode": requested_mode,
        "final_mode": effective_mode,
    }
    recommendation["meta_decision"] = {
        **dict(recommendation.get("meta_decision") or {}),
        **override_summary,
        "meta_confidence": meta_snapshot.get("meta_confidence"),
        "meta_confidence_reasoning": meta_snapshot.get("meta_confidence_reasoning"),
        "meta_confidence_components": meta_snapshot.get("meta_confidence_components"),
    }
    return {
        "status": outcome["status"],
        "summary": recommendation["summary"],
        "candidate_adjustments": recommendation["candidate_adjustments"],
        "applied_adjustments": outcome["applied_adjustments"],
        "blocked_reasons": recommendation["blocked_reasons"],
        "evidence_snapshot": signals,
        "risk_flags": recommendation["risk_flags"],
        "confidence": outcome["confidence"],
        "requires_review": outcome["requires_review"],
        "tuning_decision_reason": recommendation["summary"],
        "rollback_reference": outcome["rollback_reference"],
        "meta_status": meta_snapshot.get("meta_status"),
        "meta_reasoning": meta_snapshot.get("meta_reasoning"),
        "meta_risk_flags": meta_snapshot.get("meta_risk_flags"),
        "recommended_mode": meta_snapshot.get("recommended_mode"),
        "recommended_action": final_recommended_action,
        "meta_recommended_action": meta_snapshot.get("recommended_action"),
        "meta_confidence": meta_snapshot.get("meta_confidence"),
        "meta_confidence_reasoning": meta_snapshot.get("meta_confidence_reasoning"),
        "meta_confidence_components": meta_snapshot.get("meta_confidence_components"),
        "historical_support": meta_snapshot.get("historical_support"),
        "meta_signals": meta_snapshot.get("meta_signals"),
        "override_summary": override_summary,
        "strategy_profile": strategy_snapshot.get("strategy_profile"),
        "strategy_reasoning": strategy_snapshot.get("strategy_reasoning"),
        "strategy_controls": strategy_snapshot.get("strategy_controls"),
        "strategy_risk_flags": strategy_snapshot.get("strategy_risk_flags"),
        "strategy_override_applied": strategy_snapshot.get("strategy_override_applied"),
        "strategy_support_level": strategy_snapshot.get("strategy_support_level"),
        "strategy_recommended_action": strategy_snapshot.get("recommended_action"),
        "base_strategy_profile": strategy_snapshot.get("base_strategy_profile"),
        "final_strategy_profile": strategy_snapshot.get("final_strategy_profile"),
        "strategy_transition_reason": strategy_snapshot.get("strategy_transition_reason"),
        "strategy_hysteresis_applied": strategy_snapshot.get("strategy_hysteresis_applied"),
        "strategy_hysteresis_state": strategy_snapshot.get("strategy_hysteresis_state"),
        "final_resolved_action": (
            human_control["final_action"]
            if human_control["force_decision_override"]
            else original_resolved_action
        ),
        "decision_precedence": final_action_trace["action_trace"]["decision_precedence"],
        "strategy_conflict_resolved": final_action_trace["action_trace"]["strategy_conflict_resolved"],
        "strategy_conflict_reason": final_action_trace["action_trace"]["strategy_conflict_reason"],
        "human_control": recommendation.get("human_control"),
        "review_queue_size": recommendation["human_control"]["review_queue_size"],
        "pending_reviews": recommendation["human_control"]["pending_reviews"],
        "overrides_active": recommendation["human_control"]["overrides_active"],
        "system_mode": recommendation["human_control"]["system_mode"],
        "human_interventions_last_24h": recommendation["human_control"]["human_interventions_last_24h"],
        "metadata": {
            "dry_run": bool(dry_run),
            "action_log_id": outcome["action_log_id"],
            "evaluated_at": utc_now().isoformat(),
            "self_tuning_mode": requested_mode,
            "effective_self_tuning_mode": effective_mode,
        },
    }


def get_latest_self_tuning_cycle(db: Session) -> dict[str, Any] | None:
    action_log = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == SELF_TUNING_EVENT_TYPE)
        .order_by(LearningActionLog.created_at.desc())
        .first()
    )
    if action_log is None:
        return None
    return action_log.to_dict()


def _create_self_tuning_action_log(
    *,
    db: Session,
    status: str,
    recommendation: dict[str, Any],
    previous_runtime_config: dict[str, Any],
    effective_runtime_config: dict[str, Any],
    applied_adjustments: list[dict[str, Any]],
    confidence: float,
    requires_review: bool,
    applied: bool,
) -> LearningActionLog:
    meta_decision = dict(recommendation.get("meta_decision") or {})
    action_log = LearningActionLog(
        event_type=SELF_TUNING_EVENT_TYPE,
        recommendation_type=SELF_TUNING_RECOMMENDATION_TYPE,
        applied=applied,
        reason=f"self_tuning_{status}",
        confidence_score=confidence,
        priority=None,
        impact_status="pending" if applied else None,
        applied_at=utc_now() if applied else None,
        evidence_json=json.dumps(
            {
                "summary": recommendation.get("summary"),
                "blocked_reasons": list(recommendation.get("blocked_reasons") or []),
                "risk_flags": list(recommendation.get("risk_flags") or []),
                "requires_review": requires_review,
                "signals_snapshot": dict(recommendation.get("signals_snapshot") or {}),
                "tuning_history_snapshot": dict(recommendation.get("tuning_history_snapshot") or {}),
                "safety_checks": _extract_safety_checks(recommendation),
                "budget_usage": _extract_budget_usage(recommendation),
                "aggressiveness_mode": recommendation.get("aggressiveness_mode") or get_self_tuning_mode(),
                "aggressiveness_mode_requested": recommendation.get("aggressiveness_mode_requested") or get_self_tuning_mode(),
                "aggressiveness_mode_effective": recommendation.get("aggressiveness_mode") or get_self_tuning_mode(),
                "meta_decision": meta_decision,
                "meta_signals": dict(recommendation.get("meta_signals") or {}),
                "meta_risk_flags": list(recommendation.get("meta_risk_flags") or []),
                "strategy_decision": dict(recommendation.get("strategy_decision") or {}),
                "human_control": dict(recommendation.get("human_control") or {}),
            }
        ),
        changes_applied_json=json.dumps(
            {
                "status": status,
                "candidate_adjustments": list(recommendation.get("candidate_adjustments") or []),
                "applied_adjustments": applied_adjustments,
                "previous_runtime_config": previous_runtime_config,
                "runtime_config": effective_runtime_config,
                "signals_snapshot": dict(recommendation.get("signals_snapshot") or {}),
            },
            default=str,
        ),
    )
    db.add(action_log)
    db.commit()
    db.refresh(action_log)
    return action_log


def _get_recent_tuning_history(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    action_logs = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == SELF_TUNING_EVENT_TYPE)
        .order_by(LearningActionLog.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    history: list[dict[str, Any]] = []
    for action_log in action_logs:
        payload = _safe_json_loads(action_log.changes_applied_json, {})
        effectiveness = _resolve_tuning_effectiveness(action_log)
        for adjustment in payload.get("applied_adjustments") or []:
            history.append(
                {
                    "parameter_name": str(adjustment.get("parameter_name") or ""),
                    "direction": str(adjustment.get("direction") or ""),
                    "created_at": action_log.created_at,
                    "effectiveness": effectiveness,
                    "delta": adjustment.get("delta"),
                }
            )
    return history


def _get_recent_strategy_history(db: Session, limit: int = 12) -> list[dict[str, Any]]:
    action_logs = (
        db.query(LearningActionLog)
        .filter(LearningActionLog.event_type == SELF_TUNING_EVENT_TYPE)
        .order_by(LearningActionLog.created_at.desc())
        .limit(max(1, min(limit, 50)))
        .all()
    )
    history: list[dict[str, Any]] = []
    for action_log in action_logs:
        evidence = _safe_json_loads(action_log.evidence_json, {})
        strategy = dict(evidence.get("strategy_decision") or {})
        if not strategy:
            continue
        history.append(
            {
                "strategy_profile": strategy.get("strategy_profile"),
                "final_strategy_profile": strategy.get("final_strategy_profile") or strategy.get("strategy_profile"),
                "strategy_hysteresis_applied": bool(strategy.get("strategy_hysteresis_applied", False)),
                "final_resolved_action": strategy.get("final_resolved_action"),
                "created_at": action_log.created_at,
            }
        )
    return history


def _resolve_tuning_effectiveness(action_log: LearningActionLog) -> str:
    impact_status = str(action_log.impact_status or "").strip().lower()
    if impact_status == "improved":
        return "effective"
    if impact_status in {"neutral", "regressed"}:
        return "ineffective"
    return "unknown"


def _compute_consistency(
    *,
    improvement_rate: float,
    regression_rate: float,
    neutral_rate: float,
) -> float:
    positive_balance = max(improvement_rate - regression_rate, 0.0)
    conflict_penalty = min(improvement_rate, regression_rate) * 1.7
    negative_penalty = regression_rate * 0.9
    neutral_penalty = max(neutral_rate - 0.45, 0.0) * 0.8
    consistency = 0.35 + (positive_balance * 0.9) - conflict_penalty - negative_penalty - neutral_penalty
    return round(max(0.0, min(1.0, consistency)), 4)


def _compute_trend_stability(
    *,
    recent_avg_score: float,
    previous_avg_score: float,
    historical_avg_score: float,
    recent_block_rate: float,
    previous_block_rate: float,
) -> float:
    window_shift = abs(recent_avg_score - previous_avg_score)
    historical_shift = abs(recent_avg_score - historical_avg_score)
    block_shift = abs(recent_block_rate - previous_block_rate)
    instability = min((window_shift * 1.4) + (historical_shift * 0.9) + (block_shift * 1.2), 1.0)
    return round(max(0.0, 1.0 - instability), 4)


def _build_summary(
    *,
    signals: dict[str, Any],
    actionable_candidates: list[dict[str, Any]],
    blocked_reasons: list[str],
) -> str:
    if actionable_candidates:
        return (
            f"Self-tuning con sample_size={signals.get('sample_size', 0)}, "
            f"consistency={signals.get('consistency', 0.0)}, "
            f"trend_stability={signals.get('trend_stability', 0.0)}, "
            f"rollback_ratio={signals.get('rollback_ratio', 0.0)}, "
            f"candidates={len(actionable_candidates)}"
        )
    if blocked_reasons:
        return f"Self-tuning bloqueado por {','.join(blocked_reasons[:5])}"
    return "Self-tuning sin evidencia suficiente"


def _summarize_tuning_history(tuning_history: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, dict[str, int]] = {}
    for item in tuning_history:
        parameter_name = str(item.get("parameter_name") or "")
        if not parameter_name:
            continue
        effectiveness = str(item.get("effectiveness") or "unknown")
        bucket = summary.setdefault(parameter_name, {"effective": 0, "ineffective": 0, "unknown": 0})
        if effectiveness not in bucket:
            effectiveness = "unknown"
        bucket[effectiveness] += 1
    return summary


def _merge_meta_snapshot_into_recommendation(
    *,
    recommendation: dict[str, Any],
    meta_snapshot: dict[str, Any],
    requested_mode: str,
    effective_mode: str,
    base_recommended_action: str,
) -> dict[str, Any]:
    merged = dict(recommendation)
    merged["candidate_adjustments"] = list(meta_snapshot.get("adjusted_candidates") or recommendation.get("candidate_adjustments") or [])
    merged["blocked_reasons"] = _merge_blocked_reasons(
        original=list(recommendation.get("blocked_reasons") or []),
        candidates=merged["candidate_adjustments"],
    )
    merged["meta_signals"] = dict(meta_snapshot.get("meta_signals") or {})
    merged["meta_risk_flags"] = list(meta_snapshot.get("meta_risk_flags") or [])
    merged["meta_decision"] = {
        "meta_status": meta_snapshot.get("meta_status"),
        "meta_reasoning": meta_snapshot.get("meta_reasoning"),
        "recommended_mode": meta_snapshot.get("recommended_mode"),
        "recommended_action": meta_snapshot.get("recommended_action"),
        "requested_mode": requested_mode,
        "base_recommended_action": base_recommended_action,
        "final_recommended_action": meta_snapshot.get("recommended_action") if meta_snapshot.get("recommended_action") else base_recommended_action,
        "meta_override_applied": (
            base_recommended_action != (meta_snapshot.get("recommended_action") or base_recommended_action)
            or requested_mode != effective_mode
        ),
        "meta_override_reason": meta_snapshot.get("meta_reasoning"),
        "base_mode": requested_mode,
        "final_mode": effective_mode,
        "meta_confidence": meta_snapshot.get("meta_confidence"),
        "meta_confidence_reasoning": meta_snapshot.get("meta_confidence_reasoning"),
        "meta_confidence_components": meta_snapshot.get("meta_confidence_components"),
    }
    merged["aggressiveness_mode_requested"] = requested_mode
    merged["aggressiveness_mode"] = effective_mode
    return merged


def _merge_strategy_snapshot_into_recommendation(
    *,
    recommendation: dict[str, Any],
    strategy_snapshot: dict[str, Any],
    current_context: str,
) -> dict[str, Any]:
    merged = dict(recommendation)
    merged["candidate_adjustments"] = list(strategy_snapshot.get("adapted_candidates") or recommendation.get("candidate_adjustments") or [])
    merged["blocked_reasons"] = _merge_blocked_reasons(
        original=list(merged.get("blocked_reasons") or []),
        candidates=merged["candidate_adjustments"],
    )
    merged["strategy_decision"] = summarize_strategy_decision(
        strategy_snapshot=strategy_snapshot,
        current_context=current_context,
    )
    return merged


def _resolve_final_tuning_action(
    *,
    meta_snapshot: dict[str, Any],
    strategy_snapshot: dict[str, Any],
    base_has_actionable: bool,
) -> dict[str, Any]:
    if not base_has_actionable:
        return {
            "decision_override": None,
            "action_trace": resolve_final_tuning_action(
                meta_recommended_action=str(meta_snapshot.get("recommended_action") or "block"),
                strategy_recommended_action=str(strategy_snapshot.get("recommended_action") or "block"),
            ),
        }
    action_trace = resolve_final_tuning_action(
        meta_recommended_action=str(meta_snapshot.get("recommended_action") or "observe_only"),
        strategy_recommended_action=str(strategy_snapshot.get("recommended_action") or "observe_only"),
    )
    merged = dict(meta_snapshot)
    merged["recommended_action"] = action_trace["final_resolved_action"]
    return {
        "decision_override": merged,
        "action_trace": action_trace,
    }


def _merge_blocked_reasons(*, original: list[str], candidates: list[dict[str, Any]]) -> list[str]:
    merged = list(original)
    for candidate in candidates:
        merged.extend(list(candidate.get("blocked_reasons") or []))
    return list(dict.fromkeys(merged))


def _extract_safety_checks(recommendation: dict[str, Any]) -> dict[str, Any]:
    candidates = list(recommendation.get("candidate_adjustments") or [])
    envelope_blocked = any(
        "safety_envelope_total_delta_exceeded" in (candidate.get("blocked_reasons") or [])
        for candidate in candidates
    )
    guardrail_blocked = any(
        any(reason.startswith("guardrail_") for reason in (candidate.get("blocked_reasons") or []))
        for candidate in candidates
    )
    budget_blocked = any(
        any(reason.startswith("tuning_budget_") for reason in (candidate.get("blocked_reasons") or []))
        for candidate in candidates
    )
    meta_blocked = any(
        "meta_historically_risky_parameter" in (candidate.get("blocked_reasons") or [])
        for candidate in candidates
    )
    return {
        "safety_envelope_triggered": envelope_blocked,
        "guardrail_triggered": guardrail_blocked,
        "budget_triggered": budget_blocked,
        "meta_triggered": meta_blocked,
    }


def _extract_budget_usage(recommendation: dict[str, Any]) -> dict[str, Any]:
    candidates = list(recommendation.get("candidate_adjustments") or [])
    actionable = [candidate for candidate in candidates if not candidate.get("blocked")]
    total_delta = sum(abs(float(candidate.get("delta") or 0)) for candidate in actionable)
    return {
        "actionable_count": len(actionable),
        "total_delta_this_cycle": round(total_delta, 6),
    }


def _resolve_effective_mode(*, requested_mode: str, recommended_mode: str) -> str:
    requested_rank = MODE_ORDER.get(requested_mode, MODE_ORDER[DEFAULT_SELF_TUNING_MODE])
    recommended_rank = MODE_ORDER.get(recommended_mode, MODE_ORDER[DEFAULT_SELF_TUNING_MODE])
    if recommended_rank < requested_rank:
        return recommended_mode
    return requested_mode


def _average_candidate_confidence(candidates: list[dict[str, Any]]) -> float:
    if not candidates:
        return 0.0
    return round(sum(float(candidate.get("confidence") or 0.0) for candidate in candidates) / len(candidates), 4)


def _resolve_base_recommended_action(*, recommendation: dict[str, Any], dry_run: bool) -> str:
    actionable = [candidate for candidate in recommendation.get("candidate_adjustments") or [] if not candidate.get("blocked")]
    if not actionable:
        return "block"
    return "simulate" if dry_run else "apply"


def _status_to_recommended_action(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "applied":
        return "apply"
    if normalized == "simulated":
        return "simulate"
    if normalized == "observe_only":
        return "observe_only"
    return "block"


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback
