from __future__ import annotations

from typing import Any


RANKING_SCORE_MIN = -1.0
RANKING_SCORE_MAX = 1.0


def rank_recommendations(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    ranked_items: list[dict[str, Any]] = []

    for index, item in enumerate(items or []):
        recommendation = dict(item.get("recommendation") or {})
        simulation_result = dict(item.get("simulation_result") or {})
        operational_risk = dict(item.get("operational_risk") or {})
        final_learning_decision = dict(item.get("final_learning_decision") or {})

        ranking_score = _compute_ranking_score(
            recommendation=recommendation,
            simulation_result=simulation_result,
            operational_risk=operational_risk,
            final_learning_decision=final_learning_decision,
        )
        ranked_items.append(
            {
                **item,
                "ranking_score": ranking_score,
                "_sort_index": index,
                "_decision_class_rank": _decision_class_rank(final_learning_decision.get("decision_class")),
                "ranking_reason": _build_ranking_reason(
                    recommendation=recommendation,
                    simulation_result=simulation_result,
                    operational_risk=operational_risk,
                    final_learning_decision=final_learning_decision,
                    ranking_score=ranking_score,
                ),
            }
        )

    ranked_items.sort(
        key=lambda item: (
            int(item.get("_decision_class_rank") or 0),
            -float(item.get("ranking_score") or 0.0),
            -_safe_float(dict(item.get("recommendation") or {}).get("priority")),
            -_safe_float(dict(item.get("recommendation") or {}).get("confidence_score")),
            int(item.get("_sort_index") or 0),
        )
    )

    for position, item in enumerate(ranked_items, start=1):
        item["rank_position"] = position
        item.pop("_sort_index", None)
        item.pop("_decision_class_rank", None)

    return ranked_items


def _compute_ranking_score(
    *,
    recommendation: dict[str, Any],
    simulation_result: dict[str, Any],
    operational_risk: dict[str, Any],
    final_learning_decision: dict[str, Any],
) -> float:
    expected_impact_score = _safe_float(simulation_result.get("expected_impact_score"))
    simulation_confidence = _safe_float(simulation_result.get("confidence_score"))
    original_confidence = _safe_float(recommendation.get("confidence_score"))
    priority = _safe_float(recommendation.get("priority"))
    operational_risk_score = _safe_float(operational_risk.get("risk_score"))
    operational_risk_level = str(operational_risk.get("risk_level") or "medium").strip().lower()
    expected_outcome = str(simulation_result.get("expected_outcome") or "uncertain").strip().lower()
    decision_class = str(final_learning_decision.get("decision_class") or "skip").strip().lower()

    score = (
        (expected_impact_score * 0.4)
        + (simulation_confidence * 0.2)
        + (original_confidence * 0.1)
        + (priority * 0.1)
        - (operational_risk_score * 0.2)
    )

    if expected_outcome == "positive":
        score += 0.10
    elif expected_outcome == "negative":
        score -= 0.35

    if operational_risk_level == "high":
        score -= 0.08
    elif operational_risk_level == "medium":
        score -= 0.03

    if decision_class == "defer":
        score -= 0.10
    elif decision_class == "skip":
        score -= 0.20

    return _clamp(score, RANKING_SCORE_MIN, RANKING_SCORE_MAX)


def _build_ranking_reason(
    *,
    recommendation: dict[str, Any],
    simulation_result: dict[str, Any],
    operational_risk: dict[str, Any],
    final_learning_decision: dict[str, Any],
    ranking_score: float,
) -> str:
    return (
        f"ranking_score={ranking_score} "
        f"outcome={simulation_result.get('expected_outcome', 'uncertain')} "
        f"sim_confidence={round(_safe_float(simulation_result.get('confidence_score')), 4)} "
        f"priority={round(_safe_float(recommendation.get('priority')), 4)} "
        f"risk={round(_safe_float(operational_risk.get('risk_score')), 4)} "
        f"risk_level={operational_risk.get('risk_level', 'medium')} "
        f"decision_class={final_learning_decision.get('decision_class', 'skip')}"
    )


def _decision_class_rank(value: Any) -> int:
    decision_class = str(value or "skip").strip().lower()
    return {"apply": 0, "defer": 1, "skip": 2}.get(decision_class, 2)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return round(max(min_value, min(max_value, value)), 4)
