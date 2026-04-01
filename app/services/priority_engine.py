from __future__ import annotations

from typing import Any


SEVERITY_BASE_SCORE = {
    "critical": 30,
    "warning": 18,
    "info": 8,
}

SCOPE_SCORE = {
    "global": 8,
    "family": 5,
    "signature": 4,
}

CATEGORY_IMPACT_SCORE = {
    "resolution_drop": 8,
    "high_review_queue_pressure": 8,
    "spike_in_protective_mode": 7,
    "low_confidence_cluster": 6,
    "loop_risk": 6,
    "excessive_clarification": 5,
    "family_specific_degradation": 5,
    "signature_specific_regression": 5,
    "repeated_missing_fact_pattern": 4,
    "repeated_hardening": 4,
    "auto_healing_hardening_event": 3,
}

LEVEL_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}

EVIDENCE_RANK = {
    "strong": 0,
    "moderate": 1,
    "limited": 2,
}

SCOPE_RANK = {
    "global": 0,
    "family": 1,
    "signature": 2,
}

PROBLEM_LABELS = {
    "resolution_drop": "caida de resolucion",
    "high_review_queue_pressure": "presion de revision",
    "spike_in_protective_mode": "aumento defensivo del sistema",
    "low_confidence_cluster": "cluster de baja confianza",
    "loop_risk": "riesgo de loop conversacional",
    "excessive_clarification": "exceso de clarification",
    "family_specific_degradation": "degradacion en familia especifica",
    "signature_specific_regression": "regresion en signature especifica",
    "repeated_missing_fact_pattern": "patron repetido de dato faltante",
    "repeated_hardening": "secuencia repetida de hardening",
    "auto_healing_hardening_event": "hardening automatico reciente",
}


def enrich_alert_priorities(alerts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    safe_alerts = [dict(alert or {}) for alert in alerts or []]
    context = _build_alert_context(safe_alerts)
    enriched = [compute_alert_priority(alert, context=context) for alert in safe_alerts]
    enriched.sort(key=_priority_sort_key)
    return enriched


def compute_alert_priority(
    alert: dict[str, Any] | None,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_alert = dict(alert or {})
    safe_context = dict(context or {})
    severity = _clean_text(safe_alert.get("severity")) or "info"
    scope = _resolve_scope(safe_alert)
    category = _clean_text(safe_alert.get("category"))
    drift = _as_dict(safe_alert.get("drift"))
    baseline_context = _as_dict(safe_alert.get("baseline_context"))
    metric = _as_dict(safe_alert.get("metric"))
    evidence = _as_dict(safe_alert.get("evidence"))

    severity_score = SEVERITY_BASE_SCORE.get(severity, 6)
    scope_score = SCOPE_SCORE.get(scope, 3)
    category_score = CATEGORY_IMPACT_SCORE.get(category, 3)
    drift_score = _resolve_drift_score(drift)
    recurrence_score = _resolve_recurrence_score(metric, evidence)
    evidence_score = _resolve_evidence_score(metric)
    action_score = 1 if _clean_text(safe_alert.get("recommended_action")) else 0

    low_sample = bool(baseline_context.get("low_sample")) or _clean_text(drift.get("confidence")) == "low"
    evidence_level = _resolve_evidence_level(
        drift=drift,
        evidence_score=evidence_score,
        recurrence_score=recurrence_score,
        low_sample=low_sample,
    )
    level, level_reason = _resolve_priority_level(
        severity=severity,
        scope=scope,
        category=category,
        drift=drift,
        low_sample=low_sample,
        evidence_level=evidence_level,
    )
    intensity = _resolve_intensity_phrase(drift)
    related_context = _resolve_related_context(scope=scope, drift=drift, context=safe_context)
    dominance_rank = _resolve_dominance_rank(
        severity=severity,
        scope=scope,
        evidence_level=evidence_level,
        low_sample=low_sample,
    )

    raw_score = severity_score + scope_score + category_score + drift_score + recurrence_score + evidence_score + action_score
    priority_score = _fit_score_to_level(raw_score, level)
    if low_sample:
        priority_score = min(priority_score, 69.0)
    if dominance_rank == 0:
        priority_score = min(max(priority_score, 82.0), 100.0)

    safe_alert["priority_score"] = round(priority_score, 2)
    safe_alert["priority_level"] = level
    safe_alert["priority_reason"] = _build_priority_reason(
        level=level,
        category=category,
        scope=scope,
        intensity=intensity,
        evidence_level=evidence_level,
        low_sample=low_sample,
        related_context=related_context,
    )
    safe_alert["priority_factors"] = {
        "severity_score": severity_score,
        "scope_score": scope_score,
        "category_score": category_score,
        "drift_score": drift_score,
        "recurrence_score": recurrence_score,
        "evidence_score": evidence_score,
        "action_score": action_score,
        "low_sample": low_sample,
        "level_reason": level_reason,
        "scope": scope,
        "evidence_level": evidence_level,
        "dominance_rank": dominance_rank,
        "intensity": intensity,
        "reasons": _build_reason_tags(
            severity=severity,
            scope=scope,
            category=category,
            drift=drift,
            low_sample=low_sample,
            has_action=bool(action_score),
            evidence_level=evidence_level,
            related_context=related_context,
        ),
    }
    return safe_alert


def _build_alert_context(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    global_alerts_with_drift = [
        alert for alert in alerts
        if _resolve_scope(alert) == "global" and bool(_as_dict(alert.get("drift")))
    ]
    return {
        "has_global_drift": bool(global_alerts_with_drift),
        "global_alert_count": len(global_alerts_with_drift),
    }


def _resolve_priority_level(
    *,
    severity: str,
    scope: str,
    category: str,
    drift: dict[str, Any],
    low_sample: bool,
    evidence_level: str,
) -> tuple[str, str]:
    drift_severity = _clean_text(drift.get("severity")) or "none"
    drift_confidence = _clean_text(drift.get("confidence")) or "low"
    has_drift = bool(drift)
    strong_evidence = evidence_level == "strong"
    moderate_or_better = evidence_level in {"strong", "moderate"}
    broad_scope = scope == "global"
    localized_scope = scope in {"family", "signature"}
    high_impact = CATEGORY_IMPACT_SCORE.get(category, 0) >= 6

    if severity == "critical" and localized_scope and strong_evidence and not low_sample:
        return "high", "localized_critical_with_strong_evidence"
    if severity == "critical" and not low_sample:
        return "high", "critical_confirmed"
    if (
        severity == "warning"
        and drift_severity == "critical"
        and drift_confidence in {"high", "medium"}
        and broad_scope
        and strong_evidence
        and not low_sample
    ):
        return "high", "warning_with_confirmed_global_drift"

    if severity == "critical":
        return "medium", "critical_but_limited_evidence"
    if severity == "warning" and has_drift and moderate_or_better and not low_sample:
        return "medium", "warning_with_supported_drift"
    if severity == "warning" and broad_scope and high_impact and strong_evidence and not low_sample:
        return "medium", "warning_with_broad_operational_impact"
    return "low", "informational_or_limited_evidence"


def _fit_score_to_level(raw_score: float, level: str) -> float:
    normalized = max(min(float(raw_score), 60.0), 0.0)
    if level == "high":
        return 75.0 + (normalized / 60.0) * 25.0
    if level == "medium":
        return 45.0 + (normalized / 60.0) * 29.0
    return 15.0 + (normalized / 60.0) * 29.0


def _resolve_drift_score(drift: dict[str, Any]) -> int:
    if not drift:
        return 0
    drift_severity = _clean_text(drift.get("severity")) or "warning"
    drift_confidence = _clean_text(drift.get("confidence")) or "low"
    score = {"critical": 10, "warning": 6, "info": 2}.get(drift_severity, 0)
    score += {"high": 4, "medium": 2, "low": 0}.get(drift_confidence, 0)
    if bool(drift.get("persistent")):
        score += 2
    return score


def _resolve_recurrence_score(metric: dict[str, Any], evidence: dict[str, Any]) -> int:
    deduped_count = _safe_int(evidence.get("deduped_alert_count"))
    if deduped_count > 0:
        return min(deduped_count * 2, 6)
    metric_name = _clean_text(metric.get("name"))
    metric_value = _safe_float(metric.get("value"))
    if metric_name in {"pending_reviews", "missing_fact_count", "loop_conversations"}:
        return min(int(metric_value), 6)
    return 0


def _resolve_evidence_score(metric: dict[str, Any]) -> int:
    sample_size = max(
        _safe_int(metric.get("sample_size")),
        _safe_int(metric.get("observation_count")),
        _safe_int(metric.get("count")),
    )
    if sample_size >= 12:
        return 6
    if sample_size >= 6:
        return 4
    if sample_size >= 3:
        return 2
    return 0


def _resolve_evidence_level(
    *,
    drift: dict[str, Any],
    evidence_score: int,
    recurrence_score: int,
    low_sample: bool,
) -> str:
    if low_sample:
        return "limited"
    drift_confidence = _clean_text(drift.get("confidence")) or "low"
    persistent = bool(drift.get("persistent"))
    combined = evidence_score + recurrence_score
    if combined >= 8 and drift_confidence in {"high", "medium"} and persistent:
        return "strong"
    if combined >= 4 or drift_confidence in {"high", "medium"} or persistent:
        return "moderate"
    return "limited"


def _resolve_intensity_phrase(drift: dict[str, Any]) -> str:
    if not drift:
        return "sin drift confirmado"
    severity = _clean_text(drift.get("severity")) or "info"
    persistent = bool(drift.get("persistent"))
    if severity == "critical" and persistent:
        return "degradacion significativa"
    if severity == "critical":
        return "desviacion marcada"
    if severity == "warning" and persistent:
        return "degradacion sostenida"
    if severity == "warning":
        return "desviacion relevante respecto al baseline"
    return "leve variacion respecto al baseline"


def _resolve_related_context(
    *,
    scope: str,
    drift: dict[str, Any],
    context: dict[str, Any],
) -> str:
    if scope == "global" or not drift:
        return ""
    if bool(context.get("has_global_drift")):
        return "dentro de una tendencia global"
    return "problema localizado"


def _resolve_dominance_rank(
    *,
    severity: str,
    scope: str,
    evidence_level: str,
    low_sample: bool,
) -> int:
    if severity == "critical" and scope == "family" and evidence_level in {"strong", "moderate"} and not low_sample:
        return 0
    if severity == "critical" and scope == "signature" and evidence_level == "strong" and not low_sample:
        return 0
    return 1


def _build_priority_reason(
    *,
    level: str,
    category: str,
    scope: str,
    intensity: str,
    evidence_level: str,
    low_sample: bool,
    related_context: str,
) -> str:
    problem_label = PROBLEM_LABELS.get(category, "problema operativo")
    level_label = {
        "high": "Alta prioridad",
        "medium": "Media prioridad",
        "low": "Baja prioridad",
    }.get(level, "Prioridad")
    scope_label = {
        "global": "global",
        "family": "en familia especifica",
        "signature": "en signature especifica",
    }.get(scope, "localizada")

    evidence_label = {
        "strong": "fuerte",
        "moderate": "moderada",
        "limited": "limitada",
    }.get(evidence_level, evidence_level)
    reason = f"{level_label}: {problem_label} {scope_label} {intensity} con evidencia {evidence_label}"
    if low_sample:
        reason += " (baja muestra, low sample)"
    elif related_context:
        reason += f", {related_context}"
    return reason


def _build_reason_tags(
    *,
    severity: str,
    scope: str,
    category: str,
    drift: dict[str, Any],
    low_sample: bool,
    has_action: bool,
    evidence_level: str,
    related_context: str,
) -> list[str]:
    reasons = [
        f"severidad_{severity}",
        f"alcance_{scope}",
        f"impacto_{category or 'general'}",
        f"evidencia_{evidence_level}",
    ]
    if drift:
        reasons.append(f"drift_{_clean_text(drift.get('severity')) or 'warning'}")
        reasons.append(f"drift_confianza_{_clean_text(drift.get('confidence')) or 'low'}")
        if bool(drift.get("persistent")):
            reasons.append("drift_persistente")
    else:
        reasons.append("sin_drift_confirmado")
    if has_action:
        reasons.append("accion_sugerida_disponible")
    if low_sample:
        reasons.append("low_sample_guard")
    if related_context:
        reasons.append("contexto_global_relacionado")
    return reasons


def _resolve_scope(alert: dict[str, Any]) -> str:
    if _clean_text(alert.get("related_signature")):
        return "signature"
    if _clean_text(alert.get("related_family")):
        return "family"
    return "global"


def _priority_sort_key(item: dict[str, Any]) -> tuple[int, int, int, int, int, int, str]:
    drift = _as_dict(item.get("drift"))
    factors = _as_dict(item.get("priority_factors"))
    return (
        LEVEL_RANK.get(_clean_text(item.get("priority_level")), 9),
        1 if _is_low_sample(item) else 0,
        _safe_int(factors.get("dominance_rank")),
        0 if bool(drift) else 1,
        EVIDENCE_RANK.get(_clean_text(factors.get("evidence_level")), 9),
        SCOPE_RANK.get(_resolve_scope(item), 9),
        _clean_text(item.get("dedupe_key")) or _clean_text(item.get("alert_id")),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_low_sample(alert: dict[str, Any]) -> bool:
    baseline_context = _as_dict(alert.get("baseline_context"))
    drift = _as_dict(alert.get("drift"))
    return bool(baseline_context.get("low_sample")) or _clean_text(drift.get("confidence")) == "low"
