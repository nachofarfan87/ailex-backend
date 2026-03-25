from __future__ import annotations

from typing import Any

from app.services.impact_memory_service import (
    build_impact_signature,
    build_impact_signature_family,
)
from app.services.learning_policy import should_apply_recommendation


CONFIDENCE_BOOST_DELTA = 0.1
LEVEL_RULES = {
    "signature": {
        "min_raw_total": 3,
        "min_weighted_total": 1.5,
        "negative_threshold": -0.4,
        "positive_threshold": 0.6,
        "block_reason": "blocked_by_negative_signature_impact",
        "boost_reason": "boosted_by_positive_signature_impact",
        "neutral_reason": "allowed_by_neutral_signature_impact",
    },
    "signature_family": {
        "min_raw_total": 3,
        "min_weighted_total": 1.5,
        "negative_threshold": -0.35,
        "positive_threshold": 0.55,
        "block_reason": "blocked_by_negative_signature_family_impact",
        "boost_reason": "boosted_by_positive_signature_family_impact",
        "neutral_reason": "allowed_by_neutral_signature_family_impact",
    },
    "event_type": {
        "min_raw_total": 1,
        "min_weighted_total": 0.75,
        "negative_threshold": -0.3,
        "positive_threshold": 0.5,
        "block_reason": "blocked_by_negative_impact",
        "boost_reason": "boosted_by_positive_impact",
        "neutral_reason": "allowed_by_neutral_event_type_impact",
    },
}
LEVEL_ORDER = ("signature", "signature_family", "event_type")


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


def _build_evidence_snapshot(
    memory: dict,
    *,
    key: str,
    scope: str,
    rules: dict[str, Any],
) -> dict[str, Any]:
    raw = dict(memory.get(key) or {})
    raw_total = _safe_int(raw.get("raw_total"))
    weighted_total = round(_safe_float(raw.get("weighted_total")), 6)
    score = round(_safe_float(raw.get("score")), 4)
    min_raw_total = _safe_int(rules["min_raw_total"])
    min_weighted_total = round(_safe_float(rules["min_weighted_total"]), 4)
    strong_enough = bool(
        key in memory
        and raw_total >= min_raw_total
        and weighted_total >= min_weighted_total
    )
    confidence = 0.0
    if key in memory and min_weighted_total > 0:
        confidence = min(weighted_total / min_weighted_total, 1.5)
    confidence = round(confidence * (0.5 + min(abs(score), 1.0) / 2.0), 4)

    return {
        "key": key,
        "scope": scope,
        "family": str(raw.get("family") or key),
        "improved": _safe_int(raw.get("improved")),
        "regressed": _safe_int(raw.get("regressed")),
        "neutral": _safe_int(raw.get("neutral")),
        "raw_total": raw_total,
        "weighted_improved": round(_safe_float(raw.get("weighted_improved")), 6),
        "weighted_regressed": round(_safe_float(raw.get("weighted_regressed")), 6),
        "weighted_neutral": round(_safe_float(raw.get("weighted_neutral")), 6),
        "weighted_total": weighted_total,
        "score": score,
        "available": key in memory,
        "min_raw_total": min_raw_total,
        "min_weighted_total": min_weighted_total,
        "strong_enough": strong_enough,
        "latest_seen_at": raw.get("latest_seen_at"),
        "oldest_seen_at": raw.get("oldest_seen_at"),
        "dominant_signal": str(raw.get("dominant_signal") or "none"),
        "temporal_decay": dict(raw.get("temporal_decay") or {}),
        "memory_confidence": confidence,
    }


def _classify_signal(evidence: dict[str, Any], rules: dict[str, Any]) -> str:
    if not evidence["available"]:
        return "none"
    if not evidence["strong_enough"]:
        return "insufficient"
    if evidence["score"] <= _safe_float(rules["negative_threshold"]):
        return "negative"
    if evidence["score"] >= _safe_float(rules["positive_threshold"]):
        return "positive"
    return "neutral"


def _boosted_policy_check(recommendation: dict) -> tuple[bool, str]:
    boosted_recommendation = dict(recommendation)
    boosted_recommendation["confidence_score"] = min(
        _safe_float(recommendation.get("confidence_score")) + CONFIDENCE_BOOST_DELTA,
        1.0,
    )
    return should_apply_recommendation(boosted_recommendation)


def _build_level_snapshot(
    *,
    level: str,
    evidence: dict[str, Any],
    signal: str,
) -> dict[str, Any]:
    snapshot = dict(evidence)
    snapshot["level"] = level
    snapshot["signal"] = signal
    return snapshot


def _build_conflict_summary(
    decision_level: str,
    decision_signal: str,
    level_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    if decision_signal not in {"positive", "negative"}:
        return {"has_conflict": False, "conflicts": []}

    conflicts: list[dict[str, Any]] = []
    for snapshot in level_snapshots:
        if snapshot["level"] == decision_level:
            continue
        if snapshot["signal"] not in {"positive", "negative"}:
            continue
        if snapshot["signal"] == decision_signal:
            continue
        conflicts.append(
            {
                "level": snapshot["level"],
                "signal": snapshot["signal"],
                "score": snapshot["score"],
                "raw_total": snapshot["raw_total"],
                "weighted_total": snapshot["weighted_total"],
            }
        )

    return {
        "has_conflict": bool(conflicts),
        "conflicts": conflicts,
    }


def evaluate_impact_adaptation(
    recommendation: dict,
    impact_memory: dict,
    signature_memory: dict | None = None,
    family_memory: dict | None = None,
) -> dict[str, Any]:
    event_type = str(recommendation.get("event_type") or "").strip().lower()
    impact_signature = build_impact_signature(recommendation)
    impact_signature_family = build_impact_signature_family(recommendation)
    signature_memory = signature_memory or {}
    family_memory = family_memory or {}

    base_apply, base_reason = should_apply_recommendation(recommendation)
    signature_evidence = _build_evidence_snapshot(
        signature_memory,
        key=impact_signature,
        scope="signature",
        rules=LEVEL_RULES["signature"],
    )
    family_evidence = _build_evidence_snapshot(
        family_memory,
        key=impact_signature_family,
        scope="signature_family",
        rules=LEVEL_RULES["signature_family"],
    )
    event_type_evidence = _build_evidence_snapshot(
        impact_memory,
        key=event_type,
        scope="event_type",
        rules=LEVEL_RULES["event_type"],
    )

    level_snapshots = [
        _build_level_snapshot(
            level="signature",
            evidence=signature_evidence,
            signal=_classify_signal(signature_evidence, LEVEL_RULES["signature"]),
        ),
        _build_level_snapshot(
            level="signature_family",
            evidence=family_evidence,
            signal=_classify_signal(family_evidence, LEVEL_RULES["signature_family"]),
        ),
        _build_level_snapshot(
            level="event_type",
            evidence=event_type_evidence,
            signal=_classify_signal(event_type_evidence, LEVEL_RULES["event_type"]),
        ),
    ]

    decision: dict[str, Any] = {
        "should_apply": bool(base_apply),
        "reason": base_reason if not base_apply else "no_impact_history",
        "decision_source": "base_policy" if not base_apply else "no_history",
        "decision_level": "base_policy" if not base_apply else "none",
        "decision_mode": "blocked" if not base_apply else "allow",
        "impact_signature": impact_signature,
        "impact_signature_family": impact_signature_family,
        "signature_evidence": signature_evidence,
        "signature_family_evidence": family_evidence,
        "event_type_evidence": event_type_evidence,
        "decision_path": level_snapshots,
        "boost_applied": False,
        "observation_only": False,
        "conflict_summary": {"has_conflict": False, "conflicts": []},
    }
    if not base_apply:
        return decision

    for level in LEVEL_ORDER:
        snapshot = next(item for item in level_snapshots if item["level"] == level)
        rules = LEVEL_RULES[level]
        signal = snapshot["signal"]

        if signal == "none" or signal == "insufficient":
            continue

        if signal == "negative":
            decision.update(
                {
                    "should_apply": False,
                    "reason": str(rules["block_reason"]),
                    "decision_source": level,
                    "decision_level": level,
                    "decision_mode": "blocked",
                    "conflict_summary": _build_conflict_summary(level, signal, level_snapshots),
                }
            )
            return decision

        if signal == "positive":
            boosted_apply, boosted_reason = _boosted_policy_check(recommendation)
            decision.update(
                {
                    "should_apply": bool(boosted_apply),
                    "reason": str(rules["boost_reason"]) if boosted_apply else boosted_reason,
                    "decision_source": level,
                    "decision_level": level,
                    "decision_mode": "boosted" if boosted_apply else "blocked",
                    "boost_applied": bool(boosted_apply),
                    "conflict_summary": _build_conflict_summary(level, signal, level_snapshots),
                }
            )
            return decision

        decision.update(
            {
                "should_apply": True,
                "reason": str(rules["neutral_reason"]),
                "decision_source": level,
                "decision_level": level,
                "decision_mode": "allowed",
                "conflict_summary": _build_conflict_summary(level, signal, level_snapshots),
            }
        )
        return decision

    observed_levels = [snapshot for snapshot in level_snapshots if snapshot["signal"] == "insufficient"]
    if observed_levels:
        top_observed = observed_levels[0]
        decision.update(
            {
                "should_apply": True,
                "reason": "observed_insufficient_hierarchical_evidence",
                "decision_source": top_observed["level"],
                "decision_level": top_observed["level"],
                "decision_mode": "observed",
                "observation_only": True,
            }
        )
        return decision

    return decision


def should_apply_with_impact(
    recommendation: dict,
    impact_memory: dict,
    signature_memory: dict | None = None,
    family_memory: dict | None = None,
) -> tuple[bool, str]:
    decision = evaluate_impact_adaptation(
        recommendation,
        impact_memory,
        signature_memory,
        family_memory,
    )
    return bool(decision["should_apply"]), str(decision["reason"])
