# backend/app/services/professional_judgment_rules.py
from __future__ import annotations

from typing import Any

from app.services.professional_judgment_constants import (
    ACTION_READY_SCORE_MIN,
    BASE_STRENGTH_FOR_ACTION_READY,
    BASE_STRENGTH_FOR_GUARDED_ACTION,
    BLOCKING_ISSUE_SIGNAL_WEIGHT,
    CONTRADICTION_SIGNAL_WEIGHT,
    CRITICAL_MISSING_SIGNAL_WEIGHT,
    DECISION_CONFIDENCE_HIGH_SCORE,
    DECISION_CONFIDENCE_MEDIUM_SCORE,
    DECISION_CONFLICT_HIGH_GAP,
    DECISION_CONFLICT_MEDIUM_GAP,
    DOMINANCE_HIGH_SCORE,
    DOMINANCE_MEDIUM_SCORE,
    PRACTICAL_RISK_SCORE_HIGH,
    SIGNAL_PRIORITY,
    SIGNAL_PRIORITY_BY_DOMAIN,
    SIGNAL_PRIORITY_RANK,
    URGENCY_SCORE_HIGH,
)


def calibrate_judgment(signals: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_signals = dict(signals or {})
    contradiction_count = int(safe_signals.get("contradiction_count") or 0)
    blocking_issue_count = int(safe_signals.get("blocking_issue_count") or 0)
    critical_gap_count = int(safe_signals.get("critical_gap_count") or 0)
    important_gap_count = int(safe_signals.get("important_gap_count") or 0)
    urgency_score = int(safe_signals.get("urgency_score") or 0)
    practical_risk_score = int(safe_signals.get("practical_risk_score") or 0)
    action_ready_score = int(safe_signals.get("action_ready_score") or 0)
    base_strength_score = int(safe_signals.get("base_strength_score") or 0)
    has_action_candidate = bool(safe_signals.get("has_action_candidate"))
    followup_present = bool(safe_signals.get("followup_present"))
    followup_usefulness = str(safe_signals.get("followup_usefulness") or "").strip().lower()
    next_step_type = str(safe_signals.get("next_step_type") or "").strip().lower()
    case_domain = str(safe_signals.get("case_domain") or "").strip().lower()

    contradiction_hard = contradiction_count > 0
    blocking_hard = blocking_issue_count > 0
    critical_missing_hard = critical_gap_count > 0 and (
        followup_usefulness in {"critical", "blocking"} or not has_action_candidate
    )
    urgency_override = urgency_score >= URGENCY_SCORE_HIGH and has_action_candidate and not contradiction_hard
    practical_risk_override = (
        practical_risk_score >= PRACTICAL_RISK_SCORE_HIGH and has_action_candidate and not contradiction_hard
    )
    action_ready = (
        action_ready_score >= ACTION_READY_SCORE_MIN
        and base_strength_score >= BASE_STRENGTH_FOR_ACTION_READY
        and not contradiction_hard
        and not blocking_hard
        and critical_gap_count == 0
        and next_step_type in {"execute", "decide"}
    )

    if (contradiction_hard or blocking_hard or critical_missing_hard) and not urgency_override:
        calibrated_state = "blocked"
    elif urgency_override:
        calibrated_state = (
            "guarded_action"
            if (critical_gap_count > 0 or followup_present or contradiction_hard)
            else "action_ready"
        )
    elif practical_risk_override or (
        practical_risk_score >= PRACTICAL_RISK_SCORE_HIGH and important_gap_count > 0
    ):
        calibrated_state = "guarded_action"
    elif action_ready:
        calibrated_state = "action_ready"
    elif critical_gap_count > 0 or important_gap_count > 0 or followup_present:
        calibrated_state = "prudent"
    elif has_action_candidate and base_strength_score >= BASE_STRENGTH_FOR_GUARDED_ACTION:
        calibrated_state = "guarded_action"
    else:
        calibrated_state = "prudent"

    blocking_severity = resolve_blocking_severity(
        contradiction_count=contradiction_count,
        blocking_issue_count=blocking_issue_count,
        critical_gap_count=critical_gap_count,
        important_gap_count=important_gap_count,
        followup_present=followup_present,
        calibrated_state=calibrated_state,
    )
    decision_intent = resolve_decision_intent(
        calibrated_state=calibrated_state,
        critical_gap_count=critical_gap_count,
        important_gap_count=important_gap_count,
        followup_present=followup_present,
        has_action_candidate=has_action_candidate,
    )
    prudence_level = resolve_prudence_level(
        calibrated_state=calibrated_state,
        urgency_score=urgency_score,
        contradiction_count=contradiction_count,
        blocking_issue_count=blocking_issue_count,
        critical_gap_count=critical_gap_count,
    )
    signal_scores = build_signal_scores(
        urgency_score=urgency_score,
        practical_risk_score=practical_risk_score,
        action_ready_score=action_ready_score,
        base_strength_score=base_strength_score,
        critical_gap_count=critical_gap_count,
        contradiction_count=contradiction_count,
        blocking_issue_count=blocking_issue_count,
    )
    dominant_signal = resolve_dominant_signal(
        signal_scores=signal_scores,
        calibrated_state=calibrated_state,
        blocking_severity=blocking_severity,
        case_domain=case_domain,
    )
    dominant_signal_score = resolve_dominant_signal_score(
        dominant_signal=dominant_signal,
        signal_scores=signal_scores,
    )
    dominance_level = resolve_dominance_level(dominant_signal_score)
    confidence_clarity_score = resolve_confidence_clarity_score(
        dominant_signal_score=dominant_signal_score,
        signal_scores=signal_scores,
        contradiction_count=contradiction_count,
        blocking_issue_count=blocking_issue_count,
    )
    confidence_stability_score = resolve_confidence_stability_score(
        calibrated_state=calibrated_state,
        blocking_severity=blocking_severity,
        signal_scores=signal_scores,
        urgency_score=urgency_score,
        contradiction_count=contradiction_count,
        blocking_issue_count=blocking_issue_count,
    )
    decision_confidence_score = resolve_decision_confidence_score(
        confidence_clarity_score=confidence_clarity_score,
        confidence_stability_score=confidence_stability_score,
        dominant_signal_score=dominant_signal_score,
    )
    decision_confidence_level = resolve_decision_confidence_level(decision_confidence_score)
    decision_trace = build_decision_trace(
        calibrated_state=calibrated_state,
        decision_intent=decision_intent,
        dominant_signal=dominant_signal,
        urgency_score=urgency_score,
        contradiction_count=contradiction_count,
        blocking_issue_count=blocking_issue_count,
        critical_gap_count=critical_gap_count,
        important_gap_count=important_gap_count,
        action_ready_score=action_ready_score,
        base_strength_score=base_strength_score,
    )
    recommendation_stance = map_recommendation_stance(
        decision_intent=decision_intent,
        calibrated_state=calibrated_state,
        urgency_score=urgency_score,
        prudence_level=prudence_level,
        followup_present=followup_present,
    )
    actionability = resolve_actionability(
        calibrated_state=calibrated_state,
        has_action_candidate=has_action_candidate,
        next_step_type=next_step_type,
    )

    return {
        "calibrated_state": calibrated_state,
        "decision_intent": decision_intent,
        "recommendation_stance": recommendation_stance,
        "prudence_level": prudence_level,
        "blocking_severity": blocking_severity,
        "dominant_signal": dominant_signal,
        "dominant_signal_score": dominant_signal_score,
        "dominance_level": dominance_level,
        "confidence_clarity_score": confidence_clarity_score,
        "confidence_stability_score": confidence_stability_score,
        "decision_confidence_score": decision_confidence_score,
        "decision_confidence_level": decision_confidence_level,
        "actionability": actionability,
        "signal_scores": signal_scores,
        "decision_trace": decision_trace,
        "rule_trace": build_rule_trace(
            calibrated_state=calibrated_state,
            decision_intent=decision_intent,
            dominant_signal=dominant_signal,
            dominant_signal_score=dominant_signal_score,
            decision_confidence_score=decision_confidence_score,
            urgency_score=urgency_score,
            contradiction_count=contradiction_count,
            blocking_issue_count=blocking_issue_count,
            critical_gap_count=critical_gap_count,
            action_ready_score=action_ready_score,
        ),
    }


def build_signal_scores(
    *,
    urgency_score: int,
    practical_risk_score: int,
    action_ready_score: int,
    base_strength_score: int,
    critical_gap_count: int,
    contradiction_count: int,
    blocking_issue_count: int,
) -> dict[str, int]:
    return {
        "urgency": urgency_score,
        "practical_risk": practical_risk_score,
        "action_ready": action_ready_score,
        "base_strength": base_strength_score,
        "critical_missing": min(100, critical_gap_count * CRITICAL_MISSING_SIGNAL_WEIGHT),
        "contradiction": min(100, contradiction_count * CONTRADICTION_SIGNAL_WEIGHT),
        "blocking_issue": min(100, blocking_issue_count * BLOCKING_ISSUE_SIGNAL_WEIGHT),
    }


def resolve_blocking_severity(
    *,
    contradiction_count: int,
    blocking_issue_count: int,
    critical_gap_count: int,
    important_gap_count: int,
    followup_present: bool,
    calibrated_state: str,
) -> str:
    if contradiction_count > 0 or blocking_issue_count > 0:
        return "hard"
    if critical_gap_count > 0 and calibrated_state == "blocked":
        return "hard"
    if critical_gap_count > 0:
        return "medium"
    if important_gap_count > 0 or followup_present:
        return "soft"
    return "none"


def resolve_decision_intent(
    *,
    calibrated_state: str,
    critical_gap_count: int,
    important_gap_count: int,
    followup_present: bool,
    has_action_candidate: bool,
) -> str:
    if calibrated_state == "blocked":
        return "block"
    if calibrated_state == "action_ready":
        return "act"
    if calibrated_state == "guarded_action":
        return "act_with_guardrails"
    if followup_present or critical_gap_count > 0:
        return "clarify"
    if has_action_candidate or important_gap_count > 0:
        return "prepare"
    return "prepare"


def resolve_prudence_level(
    *,
    calibrated_state: str,
    urgency_score: int,
    contradiction_count: int,
    blocking_issue_count: int,
    critical_gap_count: int,
) -> str:
    if calibrated_state == "blocked":
        return "high"
    if contradiction_count > 0 or blocking_issue_count > 0:
        return "high"
    if calibrated_state == "guarded_action":
        return "medium" if urgency_score >= URGENCY_SCORE_HIGH or critical_gap_count > 0 else "low"
    if calibrated_state == "action_ready":
        return "low"
    return "medium" if urgency_score < URGENCY_SCORE_HIGH else "high"


def resolve_dominant_signal(
    *,
    signal_scores: dict[str, int],
    calibrated_state: str,
    blocking_severity: str,
    case_domain: str = "",
) -> str:
    priority_rank = resolve_signal_priority_rank(case_domain)
    candidates: list[str] = []
    if signal_scores.get("contradiction", 0) > 0:
        candidates.append("contradiction")
    if signal_scores.get("blocking_issue", 0) > 0:
        candidates.append("blocking_issue")
    if signal_scores.get("critical_missing", 0) > 0 and blocking_severity in {"hard", "medium"}:
        candidates.append("critical_missing")
    if signal_scores.get("urgency", 0) >= URGENCY_SCORE_HIGH and calibrated_state in {
        "guarded_action",
        "action_ready",
    }:
        candidates.append("urgency")
    if signal_scores.get("practical_risk", 0) >= max(
        signal_scores.get("action_ready", 0),
        signal_scores.get("base_strength", 0),
    ):
        candidates.append("practical_risk")
    if calibrated_state == "action_ready" or signal_scores.get("action_ready", 0) >= signal_scores.get(
        "base_strength", 0
    ):
        candidates.append("actionability")
    if signal_scores.get("base_strength", 0) > 0:
        candidates.append("base_strength")

    if not candidates:
        return "base_strength"

    prioritized_candidates = sorted(
        set(candidates),
        key=lambda signal: (
            priority_rank.get(signal, len(SIGNAL_PRIORITY)),
            -signal_scores.get(_signal_key(signal), 0),
        ),
    )
    return prioritized_candidates[0]


def resolve_signal_priority_rank(case_domain: str) -> dict[str, int]:
    normalized_domain = str(case_domain or "").strip().lower()
    ordered_signals = SIGNAL_PRIORITY_BY_DOMAIN.get(normalized_domain, SIGNAL_PRIORITY)
    if ordered_signals == SIGNAL_PRIORITY:
        return SIGNAL_PRIORITY_RANK
    return {
        signal: index
        for index, signal in enumerate(ordered_signals)
    }


def _signal_key(signal: str) -> str:
    return {
        "urgency": "urgency",
        "practical_risk": "practical_risk",
        "critical_missing": "critical_missing",
        "contradiction": "contradiction",
        "blocking_issue": "blocking_issue",
        "actionability": "action_ready",
        "base_strength": "base_strength",
    }.get(signal, "")


def resolve_confidence_clarity_score(
    *,
    dominant_signal_score: int,
    signal_scores: dict[str, int],
    contradiction_count: int,
    blocking_issue_count: int,
) -> int:
    ordered_scores = sorted(
        (int(value or 0) for value in signal_scores.values()),
        reverse=True,
    )
    top_score = ordered_scores[0] if ordered_scores else 0
    second_score = ordered_scores[1] if len(ordered_scores) > 1 else 0
    gap = max(0, top_score - second_score)

    score = dominant_signal_score
    if contradiction_count > 0:
        score -= 18
    if blocking_issue_count > 0:
        score -= 10

    if gap <= DECISION_CONFLICT_HIGH_GAP:
        score -= 15
    elif gap <= DECISION_CONFLICT_MEDIUM_GAP:
        score -= 8
    else:
        score += 4

    return max(0, min(100, score))


def resolve_confidence_stability_score(
    *,
    calibrated_state: str,
    blocking_severity: str,
    signal_scores: dict[str, int],
    urgency_score: int,
    contradiction_count: int,
    blocking_issue_count: int,
) -> int:
    score = 72
    if calibrated_state == "action_ready":
        score += 8
    elif calibrated_state == "guarded_action":
        score -= 6
    elif calibrated_state == "blocked":
        score -= 12

    if contradiction_count > 0:
        score -= 18
    if blocking_issue_count > 0:
        score -= 10
    if blocking_severity == "medium":
        score -= 8
    elif blocking_severity == "hard":
        score -= 14
    if urgency_score >= URGENCY_SCORE_HIGH:
        score -= 12
    if signal_scores.get("critical_missing", 0) > 0:
        score -= 6

    return max(0, min(100, score))


def resolve_decision_confidence_score(
    *,
    confidence_clarity_score: int,
    confidence_stability_score: int,
    dominant_signal_score: int,
) -> int:
    weighted_score = (
        confidence_clarity_score * 0.45 +
        confidence_stability_score * 0.45 +
        dominant_signal_score * 0.10
    )
    return int(max(0, min(100, round(weighted_score))))


def resolve_decision_confidence_level(score: int) -> str:
    if score >= DECISION_CONFIDENCE_HIGH_SCORE:
        return "high"
    if score >= DECISION_CONFIDENCE_MEDIUM_SCORE:
        return "medium"
    return "low"


def resolve_dominant_signal_score(
    *,
    dominant_signal: str,
    signal_scores: dict[str, int],
) -> int:
    signal_key = _signal_key(dominant_signal)
    return int(signal_scores.get(signal_key, 0) or 0)


def resolve_dominance_level(score: int) -> str:
    if score >= DOMINANCE_HIGH_SCORE:
        return "high"
    if score >= DOMINANCE_MEDIUM_SCORE:
        return "medium"
    return "low"


def resolve_actionability(
    *,
    calibrated_state: str,
    has_action_candidate: bool,
    next_step_type: str,
) -> str:
    if calibrated_state == "blocked":
        return "blocked"
    if calibrated_state == "action_ready":
        return "ready_to_act"
    if calibrated_state == "guarded_action":
        return "act_with_guardrails"
    if has_action_candidate and next_step_type in {"execute", "decide"}:
        return "prepare_to_act"
    return "needs_definition"


def map_recommendation_stance(
    *,
    decision_intent: str,
    calibrated_state: str,
    urgency_score: int,
    prudence_level: str,
    followup_present: bool,
) -> str:
    if decision_intent == "block":
        return "clarify_before_action"
    if decision_intent == "clarify":
        return "clarify_before_action" if followup_present else "orient_with_prudence"
    if decision_intent == "act_with_guardrails":
        return "urgent_action" if urgency_score >= URGENCY_SCORE_HIGH and prudence_level != "high" else "guided_action"
    if decision_intent == "prepare":
        return "guided_action" if calibrated_state == "guarded_action" else "orient_with_prudence"
    if urgency_score >= URGENCY_SCORE_HIGH and prudence_level != "high":
        return "urgent_action"
    if calibrated_state == "action_ready":
        return "firm_action"
    return "guided_action"


def build_rule_trace(
    *,
    calibrated_state: str,
    decision_intent: str,
    dominant_signal: str,
    dominant_signal_score: int,
    decision_confidence_score: int,
    urgency_score: int,
    contradiction_count: int,
    blocking_issue_count: int,
    critical_gap_count: int,
    action_ready_score: int,
) -> list[str]:
    trace: list[str] = [
        f"state={calibrated_state}",
        f"intent={decision_intent}",
        f"dominant_signal={dominant_signal}",
        f"dominant_signal_score={dominant_signal_score}",
        f"decision_confidence_score={decision_confidence_score}",
    ]
    if urgency_score:
        trace.append(f"urgency_score={urgency_score}")
    if contradiction_count:
        trace.append(f"contradictions={contradiction_count}")
    if blocking_issue_count:
        trace.append(f"blocking_issues={blocking_issue_count}")
    if critical_gap_count:
        trace.append(f"critical_gaps={critical_gap_count}")
    if action_ready_score:
        trace.append(f"action_ready_score={action_ready_score}")
    return trace


def build_decision_trace(
    *,
    calibrated_state: str,
    decision_intent: str,
    dominant_signal: str,
    urgency_score: int,
    contradiction_count: int,
    blocking_issue_count: int,
    critical_gap_count: int,
    important_gap_count: int,
    action_ready_score: int,
    base_strength_score: int,
) -> list[str]:
    trace: list[str] = []
    if contradiction_count > 0 and urgency_score >= URGENCY_SCORE_HIGH:
        trace.append("contradiction overrides urgency")
    elif contradiction_count > 0:
        trace.append("contradiction forces caution before action")

    if blocking_issue_count > 0:
        trace.append("blocking issue prevents firm action")

    if critical_gap_count > 0 and calibrated_state == "blocked":
        trace.append("critical missing keeps the case blocked")
    elif critical_gap_count > 0 and decision_intent == "act_with_guardrails":
        trace.append("critical missing is tolerated because urgency supports guarded action")
    elif important_gap_count > 0 and decision_intent == "clarify":
        trace.append("important missing keeps the next move in clarification mode")

    if urgency_score >= URGENCY_SCORE_HIGH and decision_intent == "act_with_guardrails":
        trace.append("urgency enables guarded action")
    elif urgency_score >= URGENCY_SCORE_HIGH and decision_intent == "act":
        trace.append("urgency reinforces immediate action")

    if action_ready_score >= ACTION_READY_SCORE_MIN and base_strength_score >= BASE_STRENGTH_FOR_ACTION_READY:
        trace.append("readiness supports operational next step")

    if dominant_signal == "practical_risk":
        trace.append("practical risk dominates over secondary completeness")
    elif dominant_signal == "actionability":
        trace.append("actionability dominates because the base is already usable")

    if not trace:
        trace.append("default prudence applied because no stronger override was triggered")
    return trace
