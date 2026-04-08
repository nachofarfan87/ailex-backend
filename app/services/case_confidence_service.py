# backend/app/services/case_confidence_service.py
from __future__ import annotations

import re
from typing import Any


_STRUCTURAL_FACT_PATTERNS = (
    "jurisdic",
    "vinculo",
    "relacion",
    "hijos",
    "hijo",
    "fecha",
    "conviv",
    "separa",
    "ingres",
    "document",
    "urgenc",
    "domicilio",
    "acuerdo",
    "conflicto",
)

_IMPORTANCE_PENALTY = {
    "critical": 0.28,
    "high": 0.18,
    "medium": 0.08,
    "low": 0.03,
}


def resolve_case_confidence(
    known_facts: dict,
    missing_facts: list,
    conversation_state: dict,
    case_followup: dict | None = None,
) -> dict:
    """
    Returns:
    {
        "completeness_score": float,
        "confidence_score": float,
        "confidence_level": "low" | "medium" | "high",
        "case_stage": "insufficient" | "developing" | "substantive" | "mature",
        "needs_more_questions": bool,
        "recommended_depth": "minimal" | "standard" | "extended",
        "closure_readiness": "low" | "medium" | "high",
        "reason": str,
    }
    """
    known_facts = dict(known_facts or {})
    missing_facts = [dict(item) for item in list(missing_facts or []) if isinstance(item, dict)]
    conversation_state = dict(conversation_state or {})
    case_followup = dict(case_followup or {})

    progress_state = _resolve_progress_state(conversation_state, case_followup)
    user_cannot_answer = _resolve_boolean_signal("user_cannot_answer", conversation_state, case_followup)
    detected_loop = _resolve_boolean_signal("detected_loop", conversation_state, case_followup)

    known_score = _score_known_facts(known_facts)
    missing_score = _score_missing_facts(missing_facts)
    completeness_score = _clamp((known_score * 0.6) + (missing_score * 0.4))

    confidence_score = _resolve_confidence_score(
        completeness_score=completeness_score,
        missing_facts=missing_facts,
        progress_state=progress_state,
        user_cannot_answer=user_cannot_answer,
        detected_loop=detected_loop,
    )
    confidence_level = _resolve_confidence_level(confidence_score)
    case_stage = _resolve_case_stage(
        completeness_score=completeness_score,
        known_facts=known_facts,
        missing_facts=missing_facts,
    )
    needs_more_questions = _resolve_needs_more_questions(
        missing_facts=missing_facts,
        progress_state=progress_state,
        user_cannot_answer=user_cannot_answer,
        detected_loop=detected_loop,
        case_followup=case_followup,
        completeness_score=completeness_score,
    )
    recommended_depth = _resolve_recommended_depth(
        confidence_score=confidence_score,
        case_stage=case_stage,
    )
    closure_readiness = _resolve_closure_readiness(
        completeness_score=completeness_score,
        progress_state=progress_state,
        user_cannot_answer=user_cannot_answer,
        detected_loop=detected_loop,
        needs_more_questions=needs_more_questions,
    )

    return {
        "completeness_score": round(completeness_score, 3),
        "confidence_score": round(confidence_score, 3),
        "confidence_level": confidence_level,
        "case_stage": case_stage,
        "needs_more_questions": needs_more_questions,
        "recommended_depth": recommended_depth,
        "closure_readiness": closure_readiness,
        "reason": _build_reason(
            completeness_score=completeness_score,
            confidence_level=confidence_level,
            progress_state=progress_state,
            known_facts=known_facts,
            missing_facts=missing_facts,
            user_cannot_answer=user_cannot_answer,
            detected_loop=detected_loop,
        ),
    }


def _score_known_facts(known_facts: dict[str, Any]) -> float:
    fact_count = len([key for key in known_facts if str(key).strip()])
    structural_count = _count_structural_facts(known_facts)
    fact_component = min(0.6, fact_count * 0.12)
    structural_component = min(0.4, structural_count * 0.1)
    return _clamp(fact_component + structural_component)


def _score_missing_facts(missing_facts: list[dict[str, Any]]) -> float:
    if not missing_facts:
        return 1.0

    penalty = 0.0
    for fact in missing_facts:
        importance = str(fact.get("importance") or "").strip().lower()
        penalty += _IMPORTANCE_PENALTY.get(importance, 0.03)
        if bool(fact.get("impact_on_strategy")):
            penalty += 0.05
    return _clamp(1.0 - min(0.9, penalty))


def _count_structural_facts(known_facts: dict[str, Any]) -> int:
    count = 0
    for key, value in known_facts.items():
        if value in (None, "", [], {}, False):
            continue
        normalized_key = _normalize_key(key)
        if any(pattern in normalized_key for pattern in _STRUCTURAL_FACT_PATTERNS):
            count += 1
    return count


def _resolve_confidence_score(
    *,
    completeness_score: float,
    missing_facts: list[dict[str, Any]],
    progress_state: str,
    user_cannot_answer: bool,
    detected_loop: bool,
) -> float:
    score = completeness_score
    if _has_critical_missing(missing_facts):
        score -= 0.18
    if _has_high_impact_missing(missing_facts):
        score -= 0.1
    if progress_state == "complete":
        score += 0.12
    elif progress_state == "advancing":
        score += 0.06
    elif progress_state == "stalled":
        score -= 0.06
    elif progress_state == "blocked":
        score -= 0.16
    if user_cannot_answer:
        score -= 0.08
    if detected_loop:
        score -= 0.08
    return _clamp(score)


def _resolve_confidence_level(confidence_score: float) -> str:
    if confidence_score >= 0.72:
        return "high"
    if confidence_score >= 0.4:
        return "medium"
    return "low"


def _resolve_case_stage(
    *,
    completeness_score: float,
    known_facts: dict[str, Any],
    missing_facts: list[dict[str, Any]],
) -> str:
    known_count = len([key for key in known_facts if str(key).strip()])
    if known_count <= 1 and completeness_score < 0.28:
        return "insufficient"
    if completeness_score < 0.5 or _has_critical_missing(missing_facts):
        return "developing"
    if completeness_score < 0.78:
        return "substantive"
    return "mature"


def _resolve_needs_more_questions(
    *,
    missing_facts: list[dict[str, Any]],
    progress_state: str,
    user_cannot_answer: bool,
    detected_loop: bool,
    case_followup: dict[str, Any],
    completeness_score: float,
) -> bool:
    if not missing_facts or progress_state == "complete":
        return False
    if user_cannot_answer or detected_loop:
        return False
    if completeness_score >= 0.82 and not _has_critical_missing(missing_facts):
        return False
    if bool(case_followup.get("should_ask")):
        return True
    if progress_state == "blocked":
        return False
    return _has_critical_missing(missing_facts) or _has_high_impact_missing(missing_facts)


def _resolve_recommended_depth(*, confidence_score: float, case_stage: str) -> str:
    if case_stage == "mature" and confidence_score >= 0.65:
        return "extended"
    if case_stage == "insufficient" or confidence_score < 0.4:
        return "minimal"
    return "standard"


def _resolve_closure_readiness(
    *,
    completeness_score: float,
    progress_state: str,
    user_cannot_answer: bool,
    detected_loop: bool,
    needs_more_questions: bool,
) -> str:
    if progress_state == "complete":
        return "high"
    if user_cannot_answer or detected_loop:
        return "high" if completeness_score >= 0.35 else "medium"
    if not needs_more_questions and completeness_score >= 0.55:
        return "high"
    if progress_state == "stalled" and completeness_score >= 0.4:
        return "medium"
    if completeness_score >= 0.65:
        return "medium"
    return "low"


def _resolve_progress_state(conversation_state: dict[str, Any], case_followup: dict[str, Any]) -> str:
    for candidate in (
        case_followup.get("adaptive_progress_state"),
        conversation_state.get("progress_state"),
        dict(conversation_state.get("progress_signals") or {}).get("progress_state"),
    ):
        value = str(candidate or "").strip().lower()
        if value in {"complete", "advancing", "stalled", "blocked"}:
            return value
    return "advancing"


def _resolve_boolean_signal(key: str, conversation_state: dict[str, Any], case_followup: dict[str, Any]) -> bool:
    if key in case_followup:
        return bool(case_followup.get(key))
    if key in conversation_state:
        return bool(conversation_state.get(key))
    progress_signals = dict(conversation_state.get("progress_signals") or {})
    return bool(progress_signals.get(key))


def _has_critical_missing(missing_facts: list[dict[str, Any]]) -> bool:
    return any(str(item.get("importance") or "").strip().lower() == "critical" for item in missing_facts)


def _has_high_impact_missing(missing_facts: list[dict[str, Any]]) -> bool:
    for item in missing_facts:
        importance = str(item.get("importance") or "").strip().lower()
        if importance == "critical":
            return True
        if importance == "high" and bool(item.get("impact_on_strategy")):
            return True
    return False


def _build_reason(
    *,
    completeness_score: float,
    confidence_level: str,
    progress_state: str,
    known_facts: dict[str, Any],
    missing_facts: list[dict[str, Any]],
    user_cannot_answer: bool,
    detected_loop: bool,
) -> str:
    fragments = [
        f"Base conocida: {len(known_facts)} hechos.",
        f"Pendientes relevantes: {len(missing_facts)}.",
        f"Progreso actual: {progress_state}.",
        f"Nivel estimado: {confidence_level}.",
    ]
    if _has_critical_missing(missing_facts):
        fragments.append("Todavia hay datos criticos pendientes.")
    elif completeness_score >= 0.7:
        fragments.append("La base del caso ya es sustantiva.")
    if user_cannot_answer:
        fragments.append("El usuario no puede aportar mas datos utiles por ahora.")
    if detected_loop:
        fragments.append("Se detecto redundancia reciente en el follow-up.")
    return " ".join(fragments)


def _normalize_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    return normalized[:120]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
