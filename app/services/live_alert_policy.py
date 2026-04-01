from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any

from app.services.live_alert_constants import (
    LIVE_ALERT_SOURCE,
    LIVE_ALERT_THRESHOLDS,
    SEVERITY_INFO,
    SEVERITY_ORDER,
)


def evaluate_live_alerts(
    context: dict[str, Any] | None,
    *,
    detected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    safe_context = dict(context or {})
    resolved_at = detected_at or datetime.now(timezone.utc)
    window = dict(safe_context.get("window") or {})

    alerts: list[dict[str, Any]] = []
    alerts.extend(_evaluate_resolution_drop(safe_context, resolved_at, window))
    alerts.extend(_evaluate_excessive_clarification(safe_context, resolved_at, window))
    alerts.extend(_evaluate_loop_risk(safe_context, resolved_at, window))
    alerts.extend(_evaluate_repeated_missing_fact_pattern(safe_context, resolved_at, window))
    alerts.extend(_evaluate_protective_mode_spike(safe_context, resolved_at, window))
    alerts.extend(_evaluate_low_confidence_cluster(safe_context, resolved_at, window))
    alerts.extend(_evaluate_family_degradation(safe_context, resolved_at, window))
    alerts.extend(_evaluate_signature_regression(safe_context, resolved_at, window))
    alerts.extend(_evaluate_review_queue_pressure(safe_context, resolved_at, window))
    alerts.extend(_evaluate_auto_healing_hardening(safe_context, resolved_at, window))
    return dedupe_and_compact_alerts(alerts)


def dedupe_and_compact_alerts(alerts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw_alert in alerts or []:
        alert = dict(raw_alert or {})
        dedupe_key = _clean_text(alert.get("dedupe_key"))
        if not dedupe_key:
            continue
        grouped.setdefault(dedupe_key, []).append(alert)

    compacted = [_merge_alert_group(items) for items in grouped.values()]
    compacted.sort(key=_alert_sort_key)
    return compacted


def build_alert(
    *,
    category: str,
    severity: str,
    title: str,
    description: str,
    detected_at: datetime,
    window: dict[str, Any],
    metric: dict[str, Any],
    threshold: dict[str, Any],
    recommended_action: str,
    should_surface_to_ui: bool,
    dedupe_key: str,
    related_family: str | None = None,
    related_signature: str | None = None,
    event_type: str | None = None,
    output_mode: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_window = {
        "mode": _clean_text(window.get("mode")) or "mixed",
        "last_hours": _safe_int(window.get("last_hours")) or None,
        "event_limit": _safe_int(window.get("event_limit")) or None,
        "recent_event_count": _safe_int(window.get("recent_event_count")) or None,
    }
    detected_at_iso = detected_at.astimezone(timezone.utc).isoformat()
    normalized_dedupe_key = _clean_text(dedupe_key)
    alert_id = sha1(f"{category}|{normalized_dedupe_key}".encode("utf-8")).hexdigest()[:16]
    return {
        "alert_id": alert_id,
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "detected_at": detected_at_iso,
        "window": normalized_window,
        "metric": dict(metric or {}),
        "threshold": dict(threshold or {}),
        "related_family": related_family,
        "related_signature": related_signature,
        "event_type": event_type,
        "output_mode": output_mode,
        "recommended_action": recommended_action,
        "should_surface_to_ui": bool(should_surface_to_ui),
        "dedupe_key": normalized_dedupe_key,
        "evidence": dict(evidence or {}),
        "source": LIVE_ALERT_SOURCE,
    }


def _merge_alert_group(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=_alert_sort_key)
    primary = dict(sorted_items[0])
    if len(sorted_items) == 1:
        return primary

    primary["severity"] = _max_severity(*(item.get("severity") for item in sorted_items))
    primary["evidence"] = {
        **_as_dict(primary.get("evidence")),
        "deduped_alert_count": len(sorted_items),
        "related_families": sorted({_clean_text(item.get("related_family")) for item in sorted_items if _clean_text(item.get("related_family"))}),
        "related_signatures": sorted({_clean_text(item.get("related_signature")) for item in sorted_items if _clean_text(item.get("related_signature"))}),
        "event_types": sorted({_clean_text(item.get("event_type")) for item in sorted_items if _clean_text(item.get("event_type"))}),
    }
    return primary


def _alert_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    return (
        SEVERITY_ORDER.get(_clean_text(item.get("severity")), 99),
        _clean_text(item.get("category")),
        _clean_text(item.get("dedupe_key")),
    )


def _max_severity(*values: Any) -> str:
    best = SEVERITY_INFO
    best_rank = SEVERITY_ORDER[best]
    for value in values:
        normalized = _clean_text(value) or SEVERITY_INFO
        rank = SEVERITY_ORDER.get(normalized, SEVERITY_ORDER[SEVERITY_INFO])
        if rank < best_rank:
            best = normalized
            best_rank = rank
    return best


def _summarize_metric_group(items: list[dict[str, Any]]) -> dict[str, Any]:
    safe_items = [_as_dict(item) for item in items if isinstance(item, dict)]
    observation_count = sum(_safe_int(item.get("observation_count")) for item in safe_items)
    negative_count = sum(_safe_int(item.get("negative_count")) for item in safe_items)
    weighted_sum = sum(_safe_float(item.get("avg_score")) * _safe_int(item.get("observation_count")) for item in safe_items)
    return {
        "observation_count": observation_count,
        "negative_count": negative_count,
        "avg_score": round(weighted_sum / max(observation_count, 1), 4),
        "regressed_ratio": round(_safe_div(negative_count, observation_count), 4),
    }


def _count_protective_events(snapshot: dict[str, Any]) -> int:
    safe_snapshot = _as_dict(snapshot)
    if not safe_snapshot:
        return 0
    recent_events = list(safe_snapshot.get("recent_safety_events") or [])
    count = 0
    for raw_event in recent_events:
        event = _as_dict(raw_event)
        if bool(event.get("protective_mode_active")):
            count += 1
            continue
        event_type = _clean_text(event.get("event_type"))
        fallback_type = _clean_text(event.get("fallback_type"))
        if event_type == "fallback_triggered" or fallback_type in {"internal_error", "timeout", "degraded_mode"}:
            count += 1
    return count


def _find_domain_for_missing_item(context: dict[str, Any], item_label: str) -> str:
    missing_by_domain = _as_dict(_as_dict(_as_dict(context.get("recent_conversation_metrics")).get("facts_and_missing")).get("missing_by_domain"))
    best_domain = ""
    best_count = 0
    normalized_item = _normalize_key(item_label)
    for domain, items in missing_by_domain.items():
        for item in items or []:
            safe_item = _as_dict(item)
            if _normalize_key(safe_item.get("item")) != normalized_item:
                continue
            count = _safe_int(safe_item.get("count"))
            if count > best_count:
                best_count = count
                best_domain = _clean_text(domain)
    return best_domain


def _normalize_key(value: Any) -> str:
    return _clean_text(value).casefold()


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


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


def _safe_div(numerator: float | int, denominator: float | int) -> float:
    try:
        denominator_value = float(denominator)
        if denominator_value <= 0:
            return 0.0
        return round(float(numerator) / denominator_value, 4)
    except (TypeError, ValueError):
        return 0.0


def _evaluate_resolution_drop(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["resolution_drop"]
    recent = _as_dict(context.get("recent_conversation_metrics"))
    previous = _as_dict(context.get("previous_conversation_metrics"))
    volume = _as_dict(recent.get("volume"))
    progress = _as_dict(recent.get("progress"))
    previous_progress = _as_dict(previous.get("progress"))

    recent_conversations = _safe_int(volume.get("total_conversations"))
    if recent_conversations < _safe_int(thresholds.get("min_recent_conversations")):
        return []

    current_rate = _safe_div(
        _safe_int(progress.get("conversations_with_progress")),
        recent_conversations,
    )
    previous_total = _safe_int(_as_dict(previous.get("volume")).get("total_conversations"))
    previous_rate = _safe_div(
        _safe_int(previous_progress.get("conversations_with_progress")),
        previous_total,
    ) if previous_total else None
    drop_delta = round((previous_rate or 0.0) - current_rate, 4) if previous_rate is not None else None

    severity = None
    reasons: list[str] = []
    if current_rate <= _safe_float(thresholds.get("critical_resolution_rate")):
        severity = "critical"
        reasons.append("absolute_resolution_rate_is_critical")
    elif current_rate <= _safe_float(thresholds.get("warning_resolution_rate")):
        severity = "warning"
        reasons.append("absolute_resolution_rate_is_low")

    if previous_rate is not None:
        if drop_delta is not None and drop_delta >= _safe_float(thresholds.get("critical_drop_delta")):
            severity = _max_severity(severity, "critical")
            reasons.append("relative_drop_is_critical")
        elif drop_delta is not None and drop_delta >= _safe_float(thresholds.get("warning_drop_delta")):
            severity = _max_severity(severity, "warning")
            reasons.append("relative_drop_is_material")

    if not severity:
        return []

    return [
        build_alert(
            category="resolution_drop",
            severity=severity,
            title="Caida reciente de resolucion",
            description=(
                f"La tasa reciente de conversaciones con progreso bajo a {current_rate:.2f}"
                + (f" desde {previous_rate:.2f}." if previous_rate is not None else ".")
            ),
            detected_at=detected_at,
            window=window,
            metric={
                "name": "resolution_rate",
                "value": round(current_rate, 4),
                "previous_value": round(previous_rate, 4) if previous_rate is not None else None,
                "delta": drop_delta,
                "sample_size": recent_conversations,
            },
            threshold={
                "warning_resolution_rate": _safe_float(thresholds.get("warning_resolution_rate")),
                "critical_resolution_rate": _safe_float(thresholds.get("critical_resolution_rate")),
                "warning_drop_delta": _safe_float(thresholds.get("warning_drop_delta")),
                "critical_drop_delta": _safe_float(thresholds.get("critical_drop_delta")),
            },
            recommended_action="revisar por que las conversaciones recientes no estan agregando facts ni llegando a advice util",
            should_surface_to_ui=True,
            dedupe_key="resolution_drop",
            evidence={
                "recent_conversations": recent_conversations,
                "conversations_with_progress": _safe_int(progress.get("conversations_with_progress")),
                "conversations_without_progress": _safe_int(progress.get("conversations_without_progress")),
                "reasons": reasons,
            },
        )
    ]


def _evaluate_excessive_clarification(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["excessive_clarification"]
    recent = _as_dict(context.get("recent_conversation_metrics"))
    output_modes = _as_dict(recent.get("output_modes"))
    stability = _as_dict(recent.get("stability"))
    total_turns = _safe_int(_as_dict(recent.get("volume")).get("total_turns"))
    if total_turns < _safe_int(thresholds.get("min_turns")):
        return []

    clarification_ratio = _safe_float(output_modes.get("clarification_ratio"))
    unnecessary_count = _safe_int(stability.get("unnecessary_clarification_count"))
    severity = None
    if clarification_ratio >= _safe_float(thresholds.get("critical_ratio")) or unnecessary_count >= _safe_int(thresholds.get("critical_unnecessary_count")):
        severity = "critical"
    elif clarification_ratio >= _safe_float(thresholds.get("warning_ratio")) or unnecessary_count >= _safe_int(thresholds.get("warning_unnecessary_count")):
        severity = "warning"
    if not severity:
        return []

    return [
        build_alert(
            category="excessive_clarification",
            severity=severity,
            title="Clarification reciente por encima de lo prudente",
            description=(
                f"El modo clarification representa {clarification_ratio:.2f} de los turnos recientes"
                f" y hubo {unnecessary_count} aclaraciones innecesarias."
            ),
            detected_at=detected_at,
            window=window,
            metric={
                "name": "clarification_ratio",
                "value": round(clarification_ratio, 4),
                "unnecessary_clarification_count": unnecessary_count,
                "sample_size": total_turns,
            },
            threshold={
                "warning_ratio": _safe_float(thresholds.get("warning_ratio")),
                "critical_ratio": _safe_float(thresholds.get("critical_ratio")),
                "warning_unnecessary_count": _safe_int(thresholds.get("warning_unnecessary_count")),
                "critical_unnecessary_count": _safe_int(thresholds.get("critical_unnecessary_count")),
            },
            output_mode="clarification",
            recommended_action="revisar si se esta repreguntando informacion ya suficiente o si falta pasar antes a advice",
            should_surface_to_ui=True,
            dedupe_key="excessive_clarification",
        )
    ]


def _evaluate_loop_risk(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["loop_risk"]
    recent = _as_dict(context.get("recent_conversation_metrics"))
    friction = _as_dict(recent.get("friction"))
    loop_conversations = list(friction.get("loop_conversations") or [])
    repeated_questions = list(friction.get("most_repeated_questions") or [])

    loop_count = len(loop_conversations)
    top_repeat_count = _safe_int(_as_dict(repeated_questions[0]).get("count")) if repeated_questions else 0
    severity = None
    if loop_count >= _safe_int(thresholds.get("critical_loop_conversations")) or top_repeat_count >= _safe_int(thresholds.get("critical_repeat_questions")):
        severity = "critical"
    elif loop_count >= _safe_int(thresholds.get("warning_loop_conversations")) or top_repeat_count >= _safe_int(thresholds.get("warning_repeat_questions")):
        severity = "warning"
    if not severity:
        return []

    top_question = _clean_text(_as_dict(repeated_questions[0]).get("question")) if repeated_questions else ""
    return [
        build_alert(
            category="loop_risk",
            severity=severity,
            title="Riesgo reciente de loop conversacional",
            description=(
                f"Se detectaron {loop_count} conversaciones con loop y la pregunta mas repetida aparecio {top_repeat_count} veces."
            ),
            detected_at=detected_at,
            window=window,
            metric={
                "name": "loop_conversations",
                "value": loop_count,
                "top_repeat_question_count": top_repeat_count,
                "top_repeat_question": top_question or None,
            },
            threshold={
                "warning_loop_conversations": _safe_int(thresholds.get("warning_loop_conversations")),
                "critical_loop_conversations": _safe_int(thresholds.get("critical_loop_conversations")),
                "warning_repeat_questions": _safe_int(thresholds.get("warning_repeat_questions")),
                "critical_repeat_questions": _safe_int(thresholds.get("critical_repeat_questions")),
            },
            recommended_action="inspeccionar la logica de repregunta y el cierre de clarification cuando no entra informacion nueva",
            should_surface_to_ui=True,
            dedupe_key="loop_risk",
            evidence={
                "loop_conversations": loop_conversations[:5],
                "most_repeated_questions": repeated_questions[:3],
            },
        )
    ]


def _evaluate_repeated_missing_fact_pattern(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["repeated_missing_fact_pattern"]
    recent = _as_dict(context.get("recent_conversation_metrics"))
    facts_and_missing = _as_dict(recent.get("facts_and_missing"))
    top_missing = list(facts_and_missing.get("top_missing_information") or [])
    if not top_missing:
        return []

    alerts: list[dict[str, Any]] = []
    for item in top_missing[:3]:
        safe_item = _as_dict(item)
        label = _clean_text(safe_item.get("item"))
        count = _safe_int(safe_item.get("count"))
        if count < _safe_int(thresholds.get("warning_count")) or not label:
            continue
        severity = "critical" if count >= _safe_int(thresholds.get("critical_count")) else "warning"
        domain = _find_domain_for_missing_item(context, label)
        alerts.append(
            build_alert(
                category="repeated_missing_fact_pattern",
                severity=severity,
                title="Patron repetido de dato faltante",
                description=(
                    f'El dato faltante "{label}" aparecio {count} veces en la ventana reciente.'
                    + (f" Se concentra en {domain}." if domain else "")
                ),
                detected_at=detected_at,
                window=window,
                metric={"name": "missing_fact_count", "value": count, "item": label},
                threshold={
                    "warning_count": _safe_int(thresholds.get("warning_count")),
                    "critical_count": _safe_int(thresholds.get("critical_count")),
                },
                related_family=domain or None,
                recommended_action="mejorar la captura temprana de ese dato o revisar si la pregunta esta demasiado tarde en el flujo",
                should_surface_to_ui=True,
                dedupe_key=f"repeated_missing_fact_pattern:{_normalize_key(domain or 'global')}:{_normalize_key(label)}",
                evidence={"missing_item": label, "count": count, "case_domain": domain or None},
            )
        )
    return alerts


def _evaluate_protective_mode_spike(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["spike_in_protective_mode"]
    recent = _as_dict(context.get("recent_safety_snapshot"))
    previous = _as_dict(context.get("previous_safety_snapshot"))
    total_events = _safe_int(recent.get("total_safety_events"))
    protective_count = _count_protective_events(recent)
    if total_events <= 0 or protective_count <= 0:
        return []

    current_ratio = _safe_div(protective_count, total_events)
    previous_ratio = _safe_div(_count_protective_events(previous), _safe_int(previous.get("total_safety_events"))) if previous else None
    spike_delta = round(current_ratio - (previous_ratio or 0.0), 4) if previous_ratio is not None else None

    severity = None
    if protective_count >= _safe_int(thresholds.get("critical_events")) or current_ratio >= _safe_float(thresholds.get("critical_ratio")) or (spike_delta is not None and spike_delta >= _safe_float(thresholds.get("critical_spike_delta"))):
        severity = "critical"
    elif protective_count >= _safe_int(thresholds.get("warning_events")) or current_ratio >= _safe_float(thresholds.get("warning_ratio")) or (spike_delta is not None and spike_delta >= _safe_float(thresholds.get("warning_spike_delta"))):
        severity = "warning"
    if not severity:
        return []

    return [
        build_alert(
            category="spike_in_protective_mode",
            severity=severity,
            title="Suba reciente de protective mode o degradacion defensiva",
            description=(
                f"Se observaron {protective_count} eventos recientes asociados a protective mode o fallback defensivo"
                + (f", con ratio {current_ratio:.2f} contra {previous_ratio:.2f}." if previous_ratio is not None else f", con ratio {current_ratio:.2f}.")
            ),
            detected_at=detected_at,
            window=window,
            metric={
                "name": "protective_mode_event_ratio",
                "value": round(current_ratio, 4),
                "count": protective_count,
                "previous_value": round(previous_ratio, 4) if previous_ratio is not None else None,
                "delta": spike_delta,
            },
            threshold={
                "warning_events": _safe_int(thresholds.get("warning_events")),
                "critical_events": _safe_int(thresholds.get("critical_events")),
                "warning_ratio": _safe_float(thresholds.get("warning_ratio")),
                "critical_ratio": _safe_float(thresholds.get("critical_ratio")),
            },
            recommended_action="revisar fallbacks, errores internos y si el sistema esta endureciendo demasiado la operacion reciente",
            should_surface_to_ui=True,
            dedupe_key="spike_in_protective_mode",
            evidence={
                "protective_mode_active": bool(recent.get("protective_mode_active")),
                "fallback_type_breakdown": recent.get("fallback_type_breakdown") or {},
                "severity_breakdown": recent.get("severity_breakdown") or {},
            },
        )
    ]


def _evaluate_low_confidence_cluster(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["low_confidence_cluster"]
    stats = _as_dict(context.get("action_confidence_stats"))
    total = _safe_int(stats.get("total_actions"))
    low_count = _safe_int(stats.get("low_confidence_count"))
    low_ratio = _safe_float(stats.get("low_confidence_ratio"))
    if total < _safe_int(thresholds.get("min_actions")):
        return []

    severity = None
    if low_count >= _safe_int(thresholds.get("critical_count")) or low_ratio >= _safe_float(thresholds.get("critical_ratio")):
        severity = "critical"
    elif low_count >= _safe_int(thresholds.get("warning_count")) or low_ratio >= _safe_float(thresholds.get("warning_ratio")):
        severity = "warning"
    if not severity:
        return []

    return [
        build_alert(
            category="low_confidence_cluster",
            severity=severity,
            title="Cluster reciente de baja confianza",
            description=f"Hay {low_count} decisiones recientes con confianza baja sobre {total} acciones ({low_ratio:.2f}).",
            detected_at=detected_at,
            window=window,
            metric={
                "name": "low_confidence_ratio",
                "value": round(low_ratio, 4),
                "count": low_count,
                "sample_size": total,
            },
            threshold={
                "low_confidence_threshold": _safe_float(thresholds.get("low_confidence_threshold")),
                "warning_ratio": _safe_float(thresholds.get("warning_ratio")),
                "critical_ratio": _safe_float(thresholds.get("critical_ratio")),
            },
            recommended_action="revisar que tipos de decision estan cayendo en incertidumbre y si se estan desviando a review o fallback correcto",
            should_surface_to_ui=True,
            dedupe_key="low_confidence_cluster",
        )
    ]


def _evaluate_family_degradation(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["family_specific_degradation"]
    recent_metrics = list(context.get("family_metrics_recent") or [])
    previous_map = {
        _clean_text(item.get("signature_family")): _as_dict(item)
        for item in list(context.get("family_metrics_previous") or [])
    }
    family_groups: dict[str, list[dict[str, Any]]] = {}
    for item in recent_metrics:
        safe_item = _as_dict(item)
        family = _clean_text(safe_item.get("signature_family"))
        if not family:
            continue
        family_groups.setdefault(family, []).append(safe_item)

    alerts: list[dict[str, Any]] = []
    for family, items in family_groups.items():
        summary = _summarize_metric_group(items)
        if summary["observation_count"] < _safe_int(thresholds.get("min_observations")):
            continue
        previous_summary = _summarize_metric_group([previous_map.get(family, {})]) if family in previous_map else {}
        avg_score = _safe_float(summary.get("avg_score"))
        regressed_ratio = _safe_float(summary.get("regressed_ratio"))
        score_delta = None
        if previous_summary:
            score_delta = round(avg_score - _safe_float(previous_summary.get("avg_score")), 4)

        severity = None
        if avg_score <= _safe_float(thresholds.get("critical_avg_score")) or regressed_ratio >= _safe_float(thresholds.get("critical_regressed_ratio")):
            severity = "critical"
        elif avg_score <= _safe_float(thresholds.get("warning_avg_score")) or regressed_ratio >= _safe_float(thresholds.get("warning_regressed_ratio")):
            severity = "warning"
        if not severity:
            continue

        alerts.append(
            build_alert(
                category="family_specific_degradation",
                severity=severity,
                title="Degradacion reciente por family",
                description=f"La family {family} muestra avg_score {avg_score:.2f} y regressed_ratio {regressed_ratio:.2f}.",
                detected_at=detected_at,
                window=window,
                metric={
                    "name": "family_avg_score",
                    "value": round(avg_score, 4),
                    "regressed_ratio": round(regressed_ratio, 4),
                    "observation_count": summary["observation_count"],
                    "delta_vs_previous": score_delta,
                },
                threshold={
                    "warning_avg_score": _safe_float(thresholds.get("warning_avg_score")),
                    "critical_avg_score": _safe_float(thresholds.get("critical_avg_score")),
                    "warning_regressed_ratio": _safe_float(thresholds.get("warning_regressed_ratio")),
                    "critical_regressed_ratio": _safe_float(thresholds.get("critical_regressed_ratio")),
                },
                related_family=family,
                recommended_action="revisar esa family y las signatures asociadas para ver si hay una regresion puntual o una degradacion mas amplia",
                should_surface_to_ui=True,
                dedupe_key=f"family_specific_degradation:{_normalize_key(family)}",
                evidence={
                    "event_types": sorted({_clean_text(item.get("event_type")) for item in items if _clean_text(item.get("event_type"))}),
                    "previous_avg_score": _safe_float(previous_summary.get("avg_score")) if previous_summary else None,
                },
            )
        )
    return alerts


def _evaluate_signature_regression(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["signature_specific_regression"]
    recent_metrics = list(context.get("signature_metrics_recent") or [])
    alerts: list[dict[str, Any]] = []
    for item in recent_metrics:
        safe_item = _as_dict(item)
        signature = _clean_text(safe_item.get("signature"))
        if not signature:
            continue
        observation_count = _safe_int(safe_item.get("observation_count"))
        if observation_count < _safe_int(thresholds.get("min_observations")):
            continue
        avg_score = _safe_float(safe_item.get("avg_score"))
        regressed_ratio = _safe_div(_safe_int(safe_item.get("negative_count")), observation_count)
        severity = None
        if avg_score <= _safe_float(thresholds.get("critical_avg_score")) or regressed_ratio >= _safe_float(thresholds.get("critical_regressed_ratio")):
            severity = "critical"
        elif avg_score <= _safe_float(thresholds.get("warning_avg_score")) or regressed_ratio >= _safe_float(thresholds.get("warning_regressed_ratio")):
            severity = "warning"
        if not severity:
            continue
        alerts.append(
            build_alert(
                category="signature_specific_regression",
                severity=severity,
                title="Regresion reciente por signature",
                description=f"La signature {signature} muestra avg_score {avg_score:.2f} en {observation_count} observaciones recientes.",
                detected_at=detected_at,
                window=window,
                metric={
                    "name": "signature_avg_score",
                    "value": round(avg_score, 4),
                    "regressed_ratio": round(regressed_ratio, 4),
                    "observation_count": observation_count,
                },
                threshold={
                    "warning_avg_score": _safe_float(thresholds.get("warning_avg_score")),
                    "critical_avg_score": _safe_float(thresholds.get("critical_avg_score")),
                    "warning_regressed_ratio": _safe_float(thresholds.get("warning_regressed_ratio")),
                    "critical_regressed_ratio": _safe_float(thresholds.get("critical_regressed_ratio")),
                },
                related_signature=signature,
                related_family=_clean_text(safe_item.get("signature_family")) or None,
                event_type=_clean_text(safe_item.get("event_type")) or None,
                recommended_action="inspeccionar esa signature y su decision trace para validar si hay una regresion real o una muestra demasiado homogena",
                should_surface_to_ui=True,
                dedupe_key=f"signature_specific_regression:{_normalize_key(signature)}",
            )
        )
    return alerts


def _evaluate_review_queue_pressure(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    thresholds = LIVE_ALERT_THRESHOLDS["high_review_queue_pressure"]
    snapshot = _as_dict(context.get("review_snapshot"))
    pending_reviews = _safe_int(snapshot.get("pending_reviews"))
    stale_reviews = _safe_int(snapshot.get("stale_reviews_count"))
    oldest_hours = _safe_float(snapshot.get("oldest_pending_review_hours"))
    by_priority = _as_dict(snapshot.get("pending_reviews_by_priority"))
    high_priority = _safe_int(by_priority.get("high"))

    severity = None
    if pending_reviews >= _safe_int(thresholds.get("critical_pending_reviews")) or stale_reviews >= _safe_int(thresholds.get("critical_stale_reviews")) or oldest_hours >= _safe_float(thresholds.get("critical_oldest_hours")) or high_priority >= _safe_int(thresholds.get("critical_high_priority")):
        severity = "critical"
    elif pending_reviews >= _safe_int(thresholds.get("warning_pending_reviews")) or stale_reviews >= _safe_int(thresholds.get("warning_stale_reviews")) or oldest_hours >= _safe_float(thresholds.get("warning_oldest_hours")) or high_priority >= _safe_int(thresholds.get("warning_high_priority")):
        severity = "warning"
    if not severity:
        return []

    return [
        build_alert(
            category="high_review_queue_pressure",
            severity=severity,
            title="Presion alta en review queue",
            description=f"Hay {pending_reviews} reviews pendientes, {stale_reviews} stale y {high_priority} de prioridad alta.",
            detected_at=detected_at,
            window=window,
            metric={
                "name": "pending_reviews",
                "value": pending_reviews,
                "stale_reviews": stale_reviews,
                "oldest_pending_review_hours": round(oldest_hours, 2),
                "high_priority_pending": high_priority,
            },
            threshold={
                "warning_pending_reviews": _safe_int(thresholds.get("warning_pending_reviews")),
                "critical_pending_reviews": _safe_int(thresholds.get("critical_pending_reviews")),
            },
            recommended_action="revisar backlog, priorizacion y si hay demasiadas decisiones cayendo a revision por baja confianza o conflicto",
            should_surface_to_ui=True,
            dedupe_key="high_review_queue_pressure",
            evidence={"pending_reviews_by_priority": by_priority},
        )
    ]


def _evaluate_auto_healing_hardening(
    context: dict[str, Any],
    detected_at: datetime,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    hardening_thresholds = LIVE_ALERT_THRESHOLDS["auto_healing_hardening_event"]
    repeated_thresholds = LIVE_ALERT_THRESHOLDS["repeated_hardening"]
    snapshot = _as_dict(context.get("auto_healing_snapshot"))
    action_breakdown = _as_dict(snapshot.get("action_breakdown"))
    hardening_count = _safe_int(action_breakdown.get("harden_protective_mode"))
    activate_count = _safe_int(action_breakdown.get("activate_protective_mode"))

    alerts: list[dict[str, Any]] = []
    if hardening_count >= _safe_int(hardening_thresholds.get("warning_count")):
        severity = "critical" if hardening_count >= _safe_int(hardening_thresholds.get("critical_count")) else "warning"
        alerts.append(
            build_alert(
                category="auto_healing_hardening_event",
                severity=severity,
                title="Evento reciente de hardening automatico",
                description=f"Auto-healing registró {hardening_count} endurecimientos recientes del protective mode.",
                detected_at=detected_at,
                window=window,
                metric={"name": "harden_protective_mode_count", "value": hardening_count},
                threshold={
                    "warning_count": _safe_int(hardening_thresholds.get("warning_count")),
                    "critical_count": _safe_int(hardening_thresholds.get("critical_count")),
                },
                recommended_action="auditar por que el sistema tuvo que endurecer protective mode y si la causa sigue activa",
                should_surface_to_ui=True,
                dedupe_key="auto_healing_hardening_event",
            )
        )

    repeated_count = hardening_count + activate_count
    if repeated_count >= _safe_int(repeated_thresholds.get("warning_count")):
        severity = "critical" if repeated_count >= _safe_int(repeated_thresholds.get("critical_count")) else "warning"
        alerts.append(
            build_alert(
                category="repeated_hardening",
                severity=severity,
                title="Secuencia repetida de endurecimiento operativo",
                description=f"Auto-healing acumuló {repeated_count} eventos recientes entre activacion y hardening de protective mode.",
                detected_at=detected_at,
                window=window,
                metric={"name": "protective_hardening_sequence_count", "value": repeated_count},
                threshold={
                    "warning_count": _safe_int(repeated_thresholds.get("warning_count")),
                    "critical_count": _safe_int(repeated_thresholds.get("critical_count")),
                },
                recommended_action="correlacionar safety, review queue y errores internos para encontrar la fuente comun de inestabilidad",
                should_surface_to_ui=True,
                dedupe_key="repeated_hardening",
                evidence={"action_breakdown": action_breakdown},
            )
        )
    return alerts
