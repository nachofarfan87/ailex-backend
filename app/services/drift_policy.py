from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any

from app.services.baseline_constants import DRIFT_METRIC_THRESHOLDS


def build_drift_context(
    context: dict[str, Any] | None,
    baseline_context: dict[str, Any] | None,
    *,
    detected_at: datetime | None = None,
) -> dict[str, Any]:
    safe_context = dict(context or {})
    safe_baseline = dict(baseline_context or {})
    resolved_at = detected_at or datetime.now(timezone.utc)

    drifts: list[dict[str, Any]] = []
    drifts.extend(_build_global_drifts(safe_context, safe_baseline, resolved_at))
    drifts.extend(_build_family_drifts(safe_context, safe_baseline, resolved_at))
    drifts.extend(_build_signature_drifts(safe_context, safe_baseline, resolved_at))
    drifts.sort(key=_drift_sort_key)
    return {
        "generated_at": resolved_at.astimezone(timezone.utc).isoformat(),
        "drifts": drifts,
        "summary": _build_drift_summary(drifts, safe_baseline),
    }


def _build_global_drifts(
    context: dict[str, Any],
    baseline_context: dict[str, Any],
    detected_at: datetime,
) -> list[dict[str, Any]]:
    recent_conversation_metrics = _as_dict(context.get("recent_conversation_metrics"))
    previous_conversation_metrics = _as_dict(context.get("previous_conversation_metrics"))
    recent_safety = _as_dict(context.get("recent_safety_snapshot"))
    previous_safety = _as_dict(context.get("previous_safety_snapshot"))
    recent_actions = _as_dict(context.get("action_confidence_stats"))
    previous_actions = _as_dict(context.get("previous_action_confidence_stats"))
    recent_auto_healing = _as_dict(context.get("auto_healing_snapshot"))
    previous_auto_healing = _as_dict(context.get("previous_auto_healing_snapshot"))
    baseline_globals = _as_dict(baseline_context.get("global_metrics"))

    recent_conversations = _safe_int(_as_dict(recent_conversation_metrics.get("volume")).get("total_conversations"))
    recent_turns = _safe_int(_as_dict(recent_conversation_metrics.get("volume")).get("total_turns"))
    loop_conversations = len(list(_as_dict(recent_conversation_metrics.get("friction")).get("loop_conversations") or []))
    previous_conversations = _safe_int(_as_dict(previous_conversation_metrics.get("volume")).get("total_conversations"))
    previous_turns = _safe_int(_as_dict(previous_conversation_metrics.get("volume")).get("total_turns"))
    previous_loop_conversations = len(list(_as_dict(previous_conversation_metrics.get("friction")).get("loop_conversations") or []))

    candidates = [
        (
            "resolution_rate",
            _safe_div(_safe_int(_as_dict(recent_conversation_metrics.get("progress")).get("conversations_with_progress")), recent_conversations),
            _safe_div(_safe_int(_as_dict(previous_conversation_metrics.get("progress")).get("conversations_with_progress")), previous_conversations),
            recent_conversations,
        ),
        (
            "clarification_ratio",
            _safe_float(_as_dict(recent_conversation_metrics.get("output_modes")).get("clarification_ratio")),
            _safe_float(_as_dict(previous_conversation_metrics.get("output_modes")).get("clarification_ratio")),
            recent_turns,
        ),
        (
            "loop_rate",
            _safe_div(loop_conversations, recent_conversations),
            _safe_div(previous_loop_conversations, previous_conversations),
            recent_conversations,
        ),
        (
            "protective_mode_ratio",
            _safe_div(_count_protective_events(recent_safety), _safe_int(recent_safety.get("total_safety_events"))),
            _safe_div(_count_protective_events(previous_safety), _safe_int(previous_safety.get("total_safety_events"))),
            _safe_int(recent_safety.get("total_safety_events")),
        ),
        (
            "low_confidence_ratio",
            _safe_float(recent_actions.get("low_confidence_ratio")),
            _safe_float(previous_actions.get("low_confidence_ratio")),
            _safe_int(recent_actions.get("total_actions")),
        ),
        (
            "hardening_rate",
            _hardening_rate(recent_auto_healing),
            _hardening_rate(previous_auto_healing),
            _safe_int(recent_auto_healing.get("total_events_last_24h")),
        ),
    ]

    drifts: list[dict[str, Any]] = []
    for metric_name, recent_value, previous_value, recent_sample in candidates:
        baseline_entry = _as_dict(baseline_globals.get(metric_name))
        drift = _evaluate_drift(
            metric_name=metric_name,
            scope="global",
            recent_value=recent_value,
            baseline_value=_safe_float(baseline_entry.get("baseline_value")),
            previous_value=previous_value,
            recent_sample=recent_sample,
            baseline_sample=_safe_int(baseline_entry.get("sample_count")),
            baseline_confidence=_clean_text(baseline_entry.get("confidence")) or "low",
            baseline_available=bool(baseline_entry.get("available")),
            detected_at=detected_at,
        )
        if drift:
            drifts.append(drift)
    return drifts


def _build_family_drifts(
    context: dict[str, Any],
    baseline_context: dict[str, Any],
    detected_at: datetime,
) -> list[dict[str, Any]]:
    baseline_families = _as_dict(baseline_context.get("family_metrics"))
    recent_metrics = list(context.get("family_metrics_recent") or [])
    previous_map = {
        _clean_text(item.get("signature_family")): _as_dict(item)
        for item in list(context.get("family_metrics_previous") or [])
        if _clean_text(item.get("signature_family"))
    }
    drifts: list[dict[str, Any]] = []
    for item in recent_metrics:
        safe_item = _as_dict(item)
        family = _clean_text(safe_item.get("signature_family"))
        if not family:
            continue
        observation_count = _safe_int(safe_item.get("observation_count"))
        recent_regressed_ratio = _safe_div(_safe_int(safe_item.get("negative_count")), observation_count)
        baseline_entry = _as_dict(baseline_families.get(family))
        previous_entry = _as_dict(previous_map.get(family))
        previous_observation_count = _safe_int(previous_entry.get("observation_count"))

        drifts.extend(
            _build_segment_drifts(
                scope="family",
                related_family=family,
                related_signature=None,
                event_type=_clean_text(safe_item.get("event_type")) or None,
                observation_count=observation_count,
                recent_avg_score=_safe_float(safe_item.get("avg_score")),
                recent_regressed_ratio=recent_regressed_ratio,
                previous_avg_score=_safe_float(previous_entry.get("avg_score")) if previous_observation_count else None,
                previous_regressed_ratio=_safe_div(_safe_int(previous_entry.get("negative_count")), previous_observation_count) if previous_observation_count else None,
                baseline_entry=baseline_entry,
                detected_at=detected_at,
            )
        )
    return drifts


def _build_signature_drifts(
    context: dict[str, Any],
    baseline_context: dict[str, Any],
    detected_at: datetime,
) -> list[dict[str, Any]]:
    baseline_signatures = _as_dict(baseline_context.get("signature_metrics"))
    recent_metrics = list(context.get("signature_metrics_recent") or [])
    previous_map = {
        _clean_text(item.get("signature")): _as_dict(item)
        for item in list(context.get("signature_metrics_previous") or [])
        if _clean_text(item.get("signature"))
    }
    drifts: list[dict[str, Any]] = []
    for item in recent_metrics:
        safe_item = _as_dict(item)
        signature = _clean_text(safe_item.get("signature"))
        if not signature:
            continue
        observation_count = _safe_int(safe_item.get("observation_count"))
        recent_regressed_ratio = _safe_div(_safe_int(safe_item.get("negative_count")), observation_count)
        baseline_entry = _as_dict(baseline_signatures.get(signature))
        previous_entry = _as_dict(previous_map.get(signature))
        previous_observation_count = _safe_int(previous_entry.get("observation_count"))

        drifts.extend(
            _build_segment_drifts(
                scope="signature",
                related_family=_clean_text(safe_item.get("signature_family")) or None,
                related_signature=signature,
                event_type=_clean_text(safe_item.get("event_type")) or None,
                observation_count=observation_count,
                recent_avg_score=_safe_float(safe_item.get("avg_score")),
                recent_regressed_ratio=recent_regressed_ratio,
                previous_avg_score=_safe_float(previous_entry.get("avg_score")) if previous_observation_count else None,
                previous_regressed_ratio=_safe_div(_safe_int(previous_entry.get("negative_count")), previous_observation_count) if previous_observation_count else None,
                baseline_entry=baseline_entry,
                detected_at=detected_at,
            )
        )
    return drifts


def _build_segment_drifts(
    *,
    scope: str,
    related_family: str | None,
    related_signature: str | None,
    event_type: str | None,
    observation_count: int,
    recent_avg_score: float,
    recent_regressed_ratio: float,
    previous_avg_score: float | None,
    previous_regressed_ratio: float | None,
    baseline_entry: dict[str, Any],
    detected_at: datetime,
) -> list[dict[str, Any]]:
    score_metric = f"{scope}_avg_score"
    ratio_metric = f"{scope}_regressed_ratio"
    baseline_confidence = _clean_text(baseline_entry.get("confidence")) or "low"
    baseline_available = bool(baseline_entry.get("available"))
    baseline_sample = _safe_int(baseline_entry.get("observation_count"))

    drifts: list[dict[str, Any]] = []
    score_drift = _evaluate_drift(
        metric_name=score_metric,
        scope=scope,
        recent_value=recent_avg_score,
        baseline_value=_safe_float(baseline_entry.get("avg_score")),
        previous_value=previous_avg_score,
        recent_sample=observation_count,
        baseline_sample=baseline_sample,
        baseline_confidence=baseline_confidence,
        baseline_available=baseline_available,
        detected_at=detected_at,
        related_family=related_family,
        related_signature=related_signature,
        event_type=event_type,
    )
    if score_drift:
        drifts.append(score_drift)

    ratio_drift = _evaluate_drift(
        metric_name=ratio_metric,
        scope=scope,
        recent_value=recent_regressed_ratio,
        baseline_value=_safe_float(baseline_entry.get("regressed_ratio")),
        previous_value=previous_regressed_ratio,
        recent_sample=observation_count,
        baseline_sample=baseline_sample,
        baseline_confidence=baseline_confidence,
        baseline_available=baseline_available,
        detected_at=detected_at,
        related_family=related_family,
        related_signature=related_signature,
        event_type=event_type,
    )
    if ratio_drift:
        drifts.append(ratio_drift)
    return drifts


def _evaluate_drift(
    *,
    metric_name: str,
    scope: str,
    recent_value: float,
    baseline_value: float,
    previous_value: float | None,
    recent_sample: int,
    baseline_sample: int,
    baseline_confidence: str,
    baseline_available: bool,
    detected_at: datetime,
    related_family: str | None = None,
    related_signature: str | None = None,
    event_type: str | None = None,
) -> dict[str, Any] | None:
    thresholds = DRIFT_METRIC_THRESHOLDS[metric_name]
    if recent_sample < _safe_int(thresholds.get("min_recent_sample")) or not baseline_available:
        return None

    if not _is_worse(metric_name, recent_value, baseline_value):
        return None

    absolute_delta = round(_delta(metric_name, recent_value, baseline_value), 4)
    relative_delta = round(abs(absolute_delta) / max(abs(baseline_value), 0.05), 4)
    if not _should_surface_drift(
        absolute_delta=absolute_delta,
        relative_delta=relative_delta,
        thresholds=thresholds,
        previous_value=previous_value,
        baseline_value=baseline_value,
        metric_name=metric_name,
    ):
        return None

    persistent = _is_persistent(metric_name, previous_value, baseline_value)
    confidence = _resolve_drift_confidence(
        recent_sample=recent_sample,
        baseline_sample=baseline_sample,
        baseline_confidence=baseline_confidence,
        persistent=persistent,
    )
    severity = _resolve_drift_severity(
        absolute_delta=absolute_delta,
        relative_delta=relative_delta,
        thresholds=thresholds,
        confidence=confidence,
        persistent=persistent,
    )
    drift_id = sha1(
        f"{scope}|{metric_name}|{related_family or ''}|{related_signature or ''}|{detected_at.isoformat()}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "drift_id": drift_id,
        "scope": scope,
        "metric_name": metric_name,
        "severity": severity,
        "confidence": confidence,
        "direction": "negative",
        "recent_value": round(recent_value, 4),
        "baseline_value": round(baseline_value, 4),
        "previous_value": round(previous_value, 4) if previous_value is not None else None,
        "absolute_delta": absolute_delta,
        "relative_delta": relative_delta,
        "recent_sample": recent_sample,
        "baseline_sample": baseline_sample,
        "persistent": persistent,
        "baseline_status": "ok" if baseline_available else "low_sample",
        "related_family": related_family,
        "related_signature": related_signature,
        "event_type": event_type,
        "description": (
            f"{metric_name} empeoro a {recent_value:.2f} frente a baseline {baseline_value:.2f}"
            f" (delta {absolute_delta:.2f}, muestra reciente {recent_sample}, baseline {baseline_sample})."
        ),
        "evidence": {},
        "detected_at": detected_at.astimezone(timezone.utc).isoformat(),
    }


def _build_drift_summary(drifts: list[dict[str, Any]], baseline_context: dict[str, Any]) -> dict[str, Any]:
    by_scope: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for drift in drifts:
        scope = _clean_text(drift.get("scope")) or "global"
        severity = _clean_text(drift.get("severity")) or "warning"
        by_scope[scope] = by_scope.get(scope, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1

    baseline_summary = _as_dict(baseline_context.get("summary"))
    return {
        "total_active_drifts": len(drifts),
        "by_scope": by_scope,
        "by_severity": by_severity,
        "global_low_sample_metrics": _safe_int(baseline_summary.get("global_metrics_low_sample")),
        "family_low_sample_baselines": _safe_int(baseline_summary.get("family_baselines_low_sample")),
        "signature_low_sample_baselines": _safe_int(baseline_summary.get("signature_baselines_low_sample")),
    }


def _resolve_drift_confidence(
    *,
    recent_sample: int,
    baseline_sample: int,
    baseline_confidence: str,
    persistent: bool,
) -> str:
    if recent_sample >= 10 and baseline_sample >= 10 and baseline_confidence == "high" and persistent:
        return "high"
    if recent_sample >= 5 and baseline_sample >= 5 and baseline_confidence in {"medium", "high"}:
        return "medium"
    return "low"


def _resolve_drift_severity(
    *,
    absolute_delta: float,
    relative_delta: float,
    thresholds: dict[str, Any],
    confidence: str,
    persistent: bool,
) -> str:
    info = (
        absolute_delta >= _safe_float(thresholds.get("warning_abs_delta")) * 0.6
        or relative_delta >= _safe_float(thresholds.get("warning_rel_delta")) * 0.6
    )
    critical = (
        absolute_delta >= _safe_float(thresholds.get("critical_abs_delta"))
        or relative_delta >= _safe_float(thresholds.get("critical_rel_delta"))
    )
    warning = (
        absolute_delta >= _safe_float(thresholds.get("warning_abs_delta"))
        or relative_delta >= _safe_float(thresholds.get("warning_rel_delta"))
    )
    if critical and confidence in {"medium", "high"}:
        return "critical"
    if critical and persistent:
        return "warning"
    if warning:
        return "warning"
    if info and persistent:
        return "info"
    return "info"


def _is_worse(metric_name: str, recent_value: float, baseline_value: float) -> bool:
    if metric_name in {"resolution_rate", "family_avg_score", "signature_avg_score"}:
        return recent_value < baseline_value
    return recent_value > baseline_value


def _delta(metric_name: str, recent_value: float, baseline_value: float) -> float:
    if metric_name in {"resolution_rate", "family_avg_score", "signature_avg_score"}:
        return baseline_value - recent_value
    return recent_value - baseline_value


def _is_persistent(metric_name: str, previous_value: float | None, baseline_value: float) -> bool:
    if previous_value is None:
        return False
    return _is_worse(metric_name, previous_value, baseline_value)


def _should_surface_drift(
    *,
    absolute_delta: float,
    relative_delta: float,
    thresholds: dict[str, Any],
    previous_value: float | None,
    baseline_value: float,
    metric_name: str,
) -> bool:
    if (
        absolute_delta >= _safe_float(thresholds.get("warning_abs_delta"))
        or relative_delta >= _safe_float(thresholds.get("warning_rel_delta"))
    ):
        return True
    if previous_value is None:
        return False
    if not _is_persistent(metric_name, previous_value, baseline_value):
        return False
    return (
        absolute_delta >= _safe_float(thresholds.get("warning_abs_delta")) * 0.6
        or relative_delta >= _safe_float(thresholds.get("warning_rel_delta")) * 0.6
    )


def _hardening_rate(snapshot: dict[str, Any]) -> float:
    action_breakdown = _as_dict(snapshot.get("action_breakdown"))
    total_events = _safe_int(snapshot.get("total_events_last_24h"))
    if total_events <= 0:
        return 0.0
    hardening_related = _safe_int(action_breakdown.get("harden_protective_mode")) + _safe_int(action_breakdown.get("activate_protective_mode"))
    return _safe_div(hardening_related, total_events)


def _count_protective_events(snapshot: dict[str, Any]) -> int:
    recent_events = list(snapshot.get("recent_safety_events") or [])
    if recent_events:
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
    return 1 if bool(snapshot.get("protective_mode_active")) else 0


def _drift_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    return (
        severity_order.get(_clean_text(item.get("severity")), 9),
        confidence_order.get(_clean_text(item.get("confidence")), 9),
        _clean_text(item.get("metric_name")),
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


def _safe_div(numerator: float | int, denominator: float | int) -> float:
    try:
        denominator_value = float(denominator)
        if denominator_value <= 0:
            return 0.0
        return round(float(numerator) / denominator_value, 4)
    except (TypeError, ValueError):
        return 0.0
