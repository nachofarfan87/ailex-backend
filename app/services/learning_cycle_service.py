from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.services.impact_evaluator import evaluate_impact
from app.services.utc import utc_now
from app.services.impact_memory_service import (
    SIGNATURE_METADATA_VERSION,
    TEMPORAL_DECAY_HALF_LIFE_DAYS,
    TEMPORAL_DECAY_STRATEGY,
    build_impact_signature,
    build_impact_signature_family,
    get_impact_by_event_type,
    get_impact_by_signature,
    get_impact_by_signature_family,
)
from app.services.learning_actions_service import apply_recommendation
from app.services.learning_adaptation_policy import evaluate_impact_adaptation
from app.services.learning_adaptive_policy_v2 import evaluate_adaptive_decision
from app.services.learning_metrics_service import get_learning_summary, get_recent_learning_logs
from app.services.learning_change_budget import resolve_change_budget
from app.services.learning_operational_risk import evaluate_operational_risk
from app.services.learning_policy import should_apply_recommendation
from app.services import learning_runtime_config
from app.services.learning_simulation_service import simulate_recommendation_outcome
from app.services.learning_strategy_ranker import rank_recommendations
from app.services.observability_signal_extractor import extract_signals
from legal_engine.adaptive_learning_engine import AdaptiveLearningEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Observability snapshot (compacto, para persistencia)
# ---------------------------------------------------------------------------

def _fetch_observability_context(db: Session) -> dict:
    """Consulta observability + insights para el ciclo actual.

    Retorna un dict compacto con overview, drift, insights y signals.
    Defensivo: si falla algo, retorna un contexto vacio.
    """
    try:
        from app.services import learning_observability_service, learning_insights_service

        overview = learning_observability_service.get_overview(db)
        drift = learning_observability_service.detect_drift(db)
        insights = learning_insights_service.generate_insights(db)
    except Exception:
        logger.warning("No se pudo obtener contexto de observabilidad; fallback vacio", exc_info=True)
        return {
            "overview": {},
            "drift": {},
            "insights": [],
            "extracted_signals": extract_signals(),
        }

    extracted_signals = extract_signals(
        overview=overview,
        drift=drift,
        insights=insights,
    )

    return {
        "overview": overview,
        "drift": drift,
        "insights": insights,
        "extracted_signals": extracted_signals,
    }


def _compact_observability_snapshot(obs_context: dict) -> dict:
    """Version compacta del contexto de observabilidad para persistir en JSON."""
    overview = obs_context.get("overview") or {}
    drift = obs_context.get("drift") or {}
    signals = obs_context.get("extracted_signals") or {}

    return {
        "total_observations": overview.get("total_observations", 0),
        "avg_impact_score": overview.get("avg_impact_score", 0.0),
        "recency_weighted_avg_score": overview.get("recency_weighted_avg_score", 0.0),
        "blocked_decisions": overview.get("blocked_decisions", 0),
        "reinforced_decisions": overview.get("reinforced_decisions", 0),
        "drift_detected": drift.get("drift_detected", False),
        "drift_level": drift.get("drift_level", "none"),
        "signals": signals.get("signals", []),
        "has_data": signals.get("has_data", False),
    }


def _compact_insight_snapshot(insights: list[dict]) -> list[dict]:
    """Version compacta de insights para persistir."""
    return [
        {
            "type": i.get("type", ""),
            "severity": i.get("severity", ""),
            "heuristic_key": i.get("heuristic_key", ""),
        }
        for i in (insights or [])[:10]
    ]


# ---------------------------------------------------------------------------
# Impact reference builder
# ---------------------------------------------------------------------------

def _build_impact_reference(
    event_type: str,
    impact_decision: dict,
) -> dict:
    return {
        "metadata_version": SIGNATURE_METADATA_VERSION,
        "event_type": event_type,
        "signature": impact_decision["impact_signature"],
        "signature_family": impact_decision["impact_signature_family"],
        "decision_level": impact_decision["decision_level"],
        "decision_source": impact_decision["decision_source"],
        "decision_mode": impact_decision["decision_mode"],
        "temporal_weighting": {
            "strategy": TEMPORAL_DECAY_STRATEGY,
            "half_life_days": TEMPORAL_DECAY_HALF_LIFE_DAYS,
        },
        "signature_evidence": dict(impact_decision["signature_evidence"]),
        "signature_family_evidence": dict(impact_decision["signature_family_evidence"]),
        "event_type_evidence": dict(impact_decision["event_type_evidence"]),
        "decision_path": list(impact_decision["decision_path"]),
        "conflict_summary": dict(impact_decision["conflict_summary"]),
    }


# ---------------------------------------------------------------------------
# Adaptive decision snapshot (para persistir en changes_applied_json)
# ---------------------------------------------------------------------------

def _build_adaptive_snapshot(adaptive_decision: dict) -> dict:
    """Version persistible de la adaptive decision (sin blobs pesados)."""
    return {
        "should_apply": adaptive_decision.get("should_apply"),
        "confidence_adjustment": adaptive_decision.get("confidence_adjustment", 0.0),
        "risk_level": adaptive_decision.get("risk_level", "low"),
        "reasoning": adaptive_decision.get("reasoning", ""),
        "applied_rules": adaptive_decision.get("applied_rules", []),
    }


def _build_simulation_snapshot(simulation_result: dict) -> dict:
    return {
        "expected_outcome": simulation_result.get("expected_outcome", "uncertain"),
        "expected_impact_score": simulation_result.get("expected_impact_score", 0.0),
        "risk_score": simulation_result.get("risk_score", 0.0),
        "confidence_score": simulation_result.get("confidence_score", 0.0),
        "simulation_mode": simulation_result.get("simulation_mode", "historical_heuristic"),
        "reasoning": simulation_result.get("reasoning", ""),
        "drivers": list(simulation_result.get("drivers") or [])[:8],
        "warnings": list(simulation_result.get("warnings") or [])[:8],
    }


def _build_operational_risk_snapshot(operational_risk: dict) -> dict:
    return {
        "risk_level": operational_risk.get("risk_level", "medium"),
        "risk_score": operational_risk.get("risk_score", 0.0),
        "reversible": bool(operational_risk.get("reversible", False)),
        "blast_radius": operational_risk.get("blast_radius", "medium"),
        "reasoning": operational_risk.get("reasoning", ""),
        "drivers": list(operational_risk.get("drivers") or [])[:8],
    }


def _build_budget_context_snapshot(change_budget: dict) -> dict:
    return {
        "mode": change_budget.get("mode", "normal"),
        "max_changes": int(change_budget.get("max_changes", 0) or 0),
        "max_high_risk_changes": int(change_budget.get("max_high_risk_changes", 0) or 0),
        "reasoning": change_budget.get("reasoning", ""),
    }


def _build_budget_override_snapshot(
    *,
    reason: str,
    effective_decision_class: str,
    original_final_learning_decision: dict,
) -> dict:
    return {
        "override_applied": True,
        "reason": reason,
        "effective_decision_class": effective_decision_class,
        "original_final_learning_decision": dict(original_final_learning_decision or {}),
    }


def _resolve_final_learning_decision(
    *,
    base_apply: bool,
    base_reason: str,
    impact_apply: bool,
    impact_reason: str,
    adaptive_apply: bool,
    adaptive_reason: str,
    simulation_result: dict,
    operational_risk: dict,
) -> dict:
    self_tuning_controls = learning_runtime_config.get_self_tuning_controls()
    uncertain_apply_confidence_min = max(
        0.0,
        min(1.0, float(self_tuning_controls.get("uncertain_apply_confidence_min") or 0.15)),
    )
    uncertain_apply_max_simulation_risk = max(
        0.0,
        min(1.0, float(self_tuning_controls.get("uncertain_apply_max_simulation_risk") or 0.45)),
    )

    if not base_apply:
        return {
            "should_apply": False,
            "decision_class": "skip",
            "reasoning": f"skip_base_policy: {base_reason}",
        }
    if not impact_apply:
        return {
            "should_apply": False,
            "decision_class": "skip",
            "reasoning": f"skip_impact_policy: {impact_reason}",
        }
    if not adaptive_apply:
        return {
            "should_apply": False,
            "decision_class": "skip",
            "reasoning": f"skip_adaptive_policy: {adaptive_reason}",
        }

    expected_outcome = str(simulation_result.get("expected_outcome") or "uncertain")
    expected_score = float(simulation_result.get("expected_impact_score") or 0.0)
    simulation_confidence = float(simulation_result.get("confidence_score") or 0.0)
    simulation_risk = float(simulation_result.get("risk_score") or 0.0)
    operational_risk_level = str(operational_risk.get("risk_level") or "medium")

    if expected_outcome == "negative":
        if expected_score <= -0.45 or operational_risk_level == "high":
            return {
                "should_apply": False,
                "decision_class": "skip",
                "reasoning": "skip_negative_simulation_with_material_risk",
            }
        return {
            "should_apply": False,
            "decision_class": "defer",
            "reasoning": "defer_negative_simulation_pending_manual_review",
        }

    if operational_risk_level == "high":
        if simulation_confidence < 0.55 or simulation_risk >= 0.65:
            return {
                "should_apply": False,
                "decision_class": "defer",
                "reasoning": "defer_high_operational_risk_with_limited_simulation_confidence",
            }
        return {
            "should_apply": False,
            "decision_class": "defer",
            "reasoning": "defer_high_operational_risk",
        }

    if expected_outcome == "uncertain":
        # Red flags from simulation indicate active degradation — don't apply.
        red_flag_warnings = {
            "recent_regression", "high_failure_rate",
            "unstable_pattern", "adaptive_high_risk",
        }
        sim_warnings = set(simulation_result.get("warnings") or [])
        has_red_flags = bool(red_flag_warnings & sim_warnings)

        if (
            operational_risk_level == "low"
            and simulation_risk < uncertain_apply_max_simulation_risk
            and simulation_confidence >= uncertain_apply_confidence_min
            and not has_red_flags
        ):
            return {
                "should_apply": True,
                "decision_class": "apply",
                "reasoning": "apply_prudent_under_low_operational_risk_despite_uncertain_simulation",
            }
        return {
            "should_apply": False,
            "decision_class": "defer",
            "reasoning": "defer_uncertain_simulation",
        }

    return {
        "should_apply": True,
        "decision_class": "apply",
        "reasoning": "apply_supported_by_policy_simulation_and_operational_risk",
    }


# ---------------------------------------------------------------------------
# Main learning cycle
# ---------------------------------------------------------------------------

def run_learning_cycle(db: Session) -> dict:
    before_metrics = get_learning_summary(db, last_hours=24)
    summary = get_learning_summary(db, last_hours=24)
    recent_logs = get_recent_learning_logs(db, limit=200)

    engine = AdaptiveLearningEngine()
    recommendations = engine.analyze(summary=summary, recent_logs=recent_logs)
    impact_memory = get_impact_by_event_type(db)
    signature_memory = get_impact_by_signature(db)
    family_memory = get_impact_by_signature_family(db)

    # Fetch observability context once for the entire cycle
    obs_context = _fetch_observability_context(db)
    obs_snapshot = _compact_observability_snapshot(obs_context)
    insight_snapshot = _compact_insight_snapshot(obs_context.get("insights", []))
    enriched_recommendations: list[dict] = []
    results: list[dict] = []
    applied_count = 0
    skipped_count = 0
    high_risk_applied_count = 0

    for recommendation in recommendations:
        event_type = str(recommendation.get("event_type") or "").strip().lower()
        impact_signature = build_impact_signature(recommendation)
        impact_signature_family = build_impact_signature_family(recommendation)
        base_apply, base_reason = should_apply_recommendation(recommendation)
        impact_decision = evaluate_impact_adaptation(
            recommendation,
            impact_memory,
            signature_memory,
            family_memory,
        )
        impact_apply = bool(impact_decision["should_apply"])
        impact_reason = str(impact_decision["reason"])
        impact_reference = _build_impact_reference(event_type, impact_decision)

        # --- FASE 5: Observability-guided adaptive decision ---
        adaptive_decision = evaluate_adaptive_decision(
            impact_decision=impact_decision,
            extracted_signals=obs_context.get("extracted_signals", {}),
        )
        adaptive_apply = adaptive_decision["should_apply"]
        adaptive_reason = adaptive_decision["reasoning"]
        adaptive_snapshot = _build_adaptive_snapshot(adaptive_decision)
        simulation_result = simulate_recommendation_outcome(
            recommendation=recommendation,
            impact_decision=impact_decision,
            adaptive_decision=adaptive_decision,
            observability_snapshot=obs_snapshot,
        )
        simulation_snapshot = _build_simulation_snapshot(simulation_result)
        operational_risk = evaluate_operational_risk(recommendation)
        operational_risk_snapshot = _build_operational_risk_snapshot(operational_risk)
        final_learning_decision = _resolve_final_learning_decision(
            base_apply=base_apply,
            base_reason=base_reason,
            impact_apply=impact_apply,
            impact_reason=impact_reason,
            adaptive_apply=adaptive_apply,
            adaptive_reason=adaptive_reason,
            simulation_result=simulation_result,
            operational_risk=operational_risk,
        )
        enriched_recommendations.append(
            {
                "recommendation": recommendation,
                "impact_signature": impact_signature,
                "impact_signature_family": impact_signature_family,
                "base_apply": base_apply,
                "base_reason": base_reason,
                "impact_decision": impact_decision,
                "impact_apply": impact_apply,
                "impact_reason": impact_reason,
                "impact_reference": impact_reference,
                "adaptive_decision": adaptive_decision,
                "adaptive_snapshot": adaptive_snapshot,
                "simulation_result": simulation_result,
                "simulation_snapshot": simulation_snapshot,
                "operational_risk": operational_risk,
                "operational_risk_snapshot": operational_risk_snapshot,
                "final_learning_decision": final_learning_decision,
            }
        )

    apply_candidate_count = sum(
        1
        for item in enriched_recommendations
        if str(dict(item.get("final_learning_decision") or {}).get("decision_class") or "") == "apply"
    )
    change_budget = resolve_change_budget(
        observability_snapshot=obs_snapshot,
        recommendation_count=len(recommendations),
        candidate_apply_count=apply_candidate_count,
    )
    budget_context = _build_budget_context_snapshot(change_budget)
    ranked_recommendations = rank_recommendations(enriched_recommendations)

    for item in ranked_recommendations:
        recommendation = item["recommendation"]
        impact_signature = str(item["impact_signature"])
        impact_signature_family = str(item["impact_signature_family"])
        base_apply = bool(item["base_apply"])
        base_reason = str(item["base_reason"])
        impact_decision = item["impact_decision"]
        impact_apply = bool(item["impact_apply"])
        impact_reason = str(item["impact_reason"])
        impact_reference = item["impact_reference"]
        adaptive_decision = item["adaptive_decision"]
        adaptive_reason = str(adaptive_decision.get("reasoning", ""))
        adaptive_apply = bool(adaptive_decision.get("should_apply", True))
        adaptive_snapshot = item["adaptive_snapshot"]
        simulation_snapshot = item["simulation_snapshot"]
        operational_risk = item["operational_risk"]
        operational_risk_snapshot = item["operational_risk_snapshot"]
        final_learning_decision = dict(item["final_learning_decision"] or {})
        ranking_score = float(item.get("ranking_score") or 0.0)
        rank_position = int(item.get("rank_position") or 0)
        ranking_reason = str(item.get("ranking_reason") or "")
        budget_override = None

        should_apply = bool(final_learning_decision.get("should_apply"))
        if final_learning_decision.get("decision_class") == "skip":
            if not base_apply:
                reason = base_reason
            elif not impact_apply:
                reason = impact_reason
            elif not adaptive_apply:
                reason = f"adaptive_v2_block: {adaptive_reason}"
            else:
                reason = str(final_learning_decision.get("reasoning", ""))
        elif final_learning_decision.get("decision_class") == "defer":
            reason = str(final_learning_decision.get("reasoning", ""))
        else:
            reason = "applied_with_simulation_operational_risk_and_budget"

        is_high_risk = operational_risk_snapshot.get("risk_level") == "high"
        if should_apply and applied_count >= budget_context["max_changes"]:
            should_apply = False
            budget_override = _build_budget_override_snapshot(
                reason="change_budget_max_changes_reached",
                effective_decision_class="skip",
                original_final_learning_decision=final_learning_decision,
            )
            reason = "change_budget_max_changes_reached"
        elif should_apply and is_high_risk and high_risk_applied_count >= budget_context["max_high_risk_changes"]:
            should_apply = False
            budget_override = _build_budget_override_snapshot(
                reason="change_budget_high_risk_limit_reached",
                effective_decision_class="skip",
                original_final_learning_decision=final_learning_decision,
            )
            reason = "change_budget_high_risk_limit_reached"

        if not should_apply:
            db.add(
                LearningActionLog(
                    event_type=recommendation.get("event_type"),
                    recommendation_type=recommendation.get("title"),
                    applied=False,
                    reason=reason,
                    confidence_score=recommendation.get("confidence_score"),
                    priority=recommendation.get("priority"),
                    evidence_json=json.dumps(recommendation.get("evidence", {})),
                    changes_applied_json=json.dumps(
                        {
                            "impact_metadata_version": SIGNATURE_METADATA_VERSION,
                            "impact_signature": impact_signature,
                            "impact_signature_family": impact_signature_family,
                            "impact_decision_level": impact_decision["decision_level"],
                            "impact_decision_reason": impact_reason if base_apply else base_reason,
                            "impact_decision_source": impact_decision["decision_source"],
                            "impact_score_reference": impact_reference,
                            "adaptive_decision": adaptive_snapshot,
                            "simulation_snapshot": simulation_snapshot,
                            "operational_risk": operational_risk_snapshot,
                            "final_learning_decision": final_learning_decision,
                            "budget_override": budget_override,
                            "ranking_score": ranking_score,
                            "rank_position": rank_position,
                            "ranking_reason": ranking_reason,
                            "budget_context": budget_context,
                            "observability_snapshot": obs_snapshot,
                            "insight_snapshot": insight_snapshot,
                        }
                    ),
                    impact_status=None,
                    applied_at=None,
                )
            )
            skipped_count += 1
            results.append(
                {
                    "recommendation": recommendation,
                    "applied": False,
                    "reason": reason,
                    "impact_decision_reason": impact_reason if base_apply else base_reason,
                    "adaptive_decision": adaptive_snapshot,
                    "simulation_snapshot": simulation_snapshot,
                    "operational_risk": operational_risk_snapshot,
                    "final_learning_decision": final_learning_decision,
                    "budget_override": budget_override,
                    "ranking_score": ranking_score,
                    "rank_position": rank_position,
                    "ranking_reason": ranking_reason,
                    "budget_context": budget_context,
                }
            )
            continue

        action_result = apply_recommendation(db, recommendation)
        applied_at = utc_now() if action_result.applied else None
        impact_status = "pending" if action_result.applied else None
        action_details = dict(action_result.details or {})
        action_details["impact_metadata_version"] = SIGNATURE_METADATA_VERSION
        action_details["impact_signature"] = impact_signature
        action_details["impact_signature_family"] = impact_signature_family
        action_details["impact_decision_level"] = impact_decision["decision_level"]
        action_details["impact_decision_reason"] = impact_reason
        action_details["impact_decision_source"] = impact_decision["decision_source"]
        action_details["impact_score_reference"] = impact_reference
        action_details["adaptive_decision"] = adaptive_snapshot
        action_details["simulation_snapshot"] = simulation_snapshot
        action_details["operational_risk"] = operational_risk_snapshot
        action_details["final_learning_decision"] = final_learning_decision
        action_details["budget_override"] = budget_override
        action_details["ranking_score"] = ranking_score
        action_details["rank_position"] = rank_position
        action_details["ranking_reason"] = ranking_reason
        action_details["budget_context"] = budget_context
        action_details["observability_snapshot"] = obs_snapshot
        action_details["insight_snapshot"] = insight_snapshot
        db.add(
            LearningActionLog(
                event_type=recommendation.get("event_type"),
                recommendation_type=recommendation.get("title"),
                applied=action_result.applied,
                reason=action_result.reason,
                confidence_score=recommendation.get("confidence_score"),
                priority=recommendation.get("priority"),
                evidence_json=json.dumps(recommendation.get("evidence", {})),
                changes_applied_json=json.dumps(action_details),
                impact_status=impact_status,
                applied_at=applied_at,
            )
        )
        if action_result.applied:
            applied_count += 1
            if is_high_risk:
                high_risk_applied_count += 1
        else:
            skipped_count += 1
        results.append(
            {
                "recommendation": recommendation,
                "applied": action_result.applied,
                "reason": action_result.reason,
                "details": action_result.details,
                "impact_decision_reason": impact_reason,
                "adaptive_decision": adaptive_snapshot,
                "simulation_snapshot": simulation_snapshot,
                "operational_risk": operational_risk_snapshot,
                "final_learning_decision": final_learning_decision,
                "budget_override": budget_override,
                "ranking_score": ranking_score,
                "rank_position": rank_position,
                "ranking_reason": ranking_reason,
                "budget_context": budget_context,
            }
        )

    after_metrics_raw = get_learning_summary(db, last_hours=24)
    after_metrics = dict(after_metrics_raw)
    if "average_confidence" in after_metrics and "avg_confidence" not in after_metrics:
        after_metrics["avg_confidence"] = after_metrics["average_confidence"]
    if "feedback_summary" in after_metrics and "success_rate" not in after_metrics:
        feedback_summary = dict(after_metrics.get("feedback_summary") or {})
        after_metrics["success_rate"] = feedback_summary.get("success_rate", 0.0)

    before_metrics_for_impact = dict(before_metrics)
    if "average_confidence" in before_metrics_for_impact and "avg_confidence" not in before_metrics_for_impact:
        before_metrics_for_impact["avg_confidence"] = before_metrics_for_impact["average_confidence"]
    if "feedback_summary" in before_metrics_for_impact and "success_rate" not in before_metrics_for_impact:
        feedback_summary = dict(before_metrics_for_impact.get("feedback_summary") or {})
        before_metrics_for_impact["success_rate"] = feedback_summary.get("success_rate", 0.0)

    impact = evaluate_impact(before_metrics_for_impact, after_metrics)
    db.add(
        LearningImpactLog(
            action_log_id="batch",
            learning_action_log_id="batch",
            event_type="learning_cycle_batch",
            status=impact["impact_label"],
            before_metrics_json=json.dumps(before_metrics_for_impact),
            after_metrics_json=json.dumps(after_metrics),
            delta_metrics_json=json.dumps({}),
            evaluation_window_hours=24,
            evaluated_at=utc_now(),
            metric_before_json=json.dumps(before_metrics_for_impact),
            metric_after_json=json.dumps(after_metrics),
            impact_score=impact["impact_score"],
            impact_label=impact["impact_label"],
        )
    )
    db.commit()

    return {
        "total_recommendations": len(recommendations),
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "budget_context": budget_context,
        "results": results,
    }
