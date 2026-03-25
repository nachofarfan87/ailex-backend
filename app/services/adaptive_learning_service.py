from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.models.orchestrator_config_snapshot import OrchestratorConfigSnapshot
from app.models.orchestrator_tuning_event import OrchestratorTuningEvent
from app.services import learning_metrics_service, orchestrator_config_service
from legal_engine.adaptive_learning_engine import AdaptiveLearningEngine
from app.services.utc import utc_now
from legal_engine.orchestrator_config import OrchestratorAdaptiveConfig


DEFAULT_EVALUATION_WINDOW_HOURS = 24
MIN_EVALUATION_LAG_HOURS = 6
MIN_BASELINE_SAMPLE_SIZE = 3
MIN_POST_APPLY_SAMPLE_SIZE = 8
ACTIVE_EVENT_STATUSES = {"proposed", "approved", "applied"}
PRIORITY_DECAY_HALF_LIFE_HOURS = 48.0


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(raw: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(raw or "{}")
        return loaded if isinstance(loaded, dict) else {}
    except (TypeError, ValueError):
        return {}


def _normalize_version(value: Any, default: str = "v1") -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_domain(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_domains_from_payload(payload: dict[str, Any]) -> set[str]:
    domains: set[str] = set()
    for key in ("prefer_hybrid_domains_add", "force_full_pipeline_domains_add"):
        for item in payload.get(key, []) or []:
            normalized = _normalize_domain(item)
            if normalized:
                domains.add(normalized)
    for key in ("domain", "case_domain"):
        normalized = _normalize_domain(payload.get(key))
        if normalized:
            domains.add(normalized)
    return domains


def _event_semantic_signature(event_type: str, evidence: dict[str, Any], proposed_changes: dict[str, Any]) -> str:
    normalized_type = str(event_type or "").strip().lower()
    domains = sorted(_extract_domains_from_payload(evidence) | _extract_domains_from_payload(proposed_changes))
    normalized_changes = json.dumps(proposed_changes or {}, ensure_ascii=False, sort_keys=True, default=str)
    return f"{normalized_type}|{'/'.join(domains)}|{normalized_changes}"


def _merge_config_changes(config: OrchestratorAdaptiveConfig, changes: dict[str, Any]) -> OrchestratorAdaptiveConfig:
    merged = OrchestratorAdaptiveConfig.from_dict(config.to_dict())

    for domain in changes.get("prefer_hybrid_domains_add", []) or []:
        normalized = _normalize_domain(domain)
        if normalized and normalized not in merged.prefer_hybrid_domains:
            merged.prefer_hybrid_domains.append(normalized)

    for domain in changes.get("force_full_pipeline_domains_add", []) or []:
        normalized = _normalize_domain(domain)
        if normalized and normalized not in merged.force_full_pipeline_domains:
            merged.force_full_pipeline_domains.append(normalized)

    threshold_review = dict(changes.get("threshold_review") or {})
    if "low_confidence_threshold" in threshold_review:
        merged.low_confidence_threshold = float(threshold_review["low_confidence_threshold"])
    if "low_decision_confidence_threshold" in threshold_review:
        merged.low_decision_confidence_threshold = float(threshold_review["low_decision_confidence_threshold"])
    if "ambiguity_threshold" in threshold_review:
        merged.ambiguity_threshold = float(threshold_review["ambiguity_threshold"])
    if "manual_review_threshold" in threshold_review:
        merged.manual_review_threshold = float(threshold_review["manual_review_threshold"])

    for field_name in (
        "ambiguity_threshold",
        "manual_review_threshold",
        "low_confidence_threshold",
        "low_decision_confidence_threshold",
    ):
        if field_name in changes:
            setattr(merged, field_name, float(changes[field_name]))

    if "strategy_weights" in changes and isinstance(changes["strategy_weights"], dict):
        merged.strategy_weights.update(
            {
                str(key): float(value)
                for key, value in changes["strategy_weights"].items()
            }
        )

    merged.version = _normalize_version(changes.get("target_version"), default=merged.version)
    return merged


def _persist_snapshot(
    db: Session,
    *,
    event_id: str,
    snapshot_type: str,
    version: str,
    config: OrchestratorAdaptiveConfig,
) -> OrchestratorConfigSnapshot:
    snapshot = OrchestratorConfigSnapshot(
        event_id=event_id,
        snapshot_type=snapshot_type,
        version=_normalize_version(version, default=config.version),
        config_json=_json_dumps(config.to_dict()),
    )
    db.add(snapshot)
    return snapshot


def _get_event_or_raise(db: Session, event_id: str) -> OrchestratorTuningEvent:
    event = db.get(OrchestratorTuningEvent, event_id)
    if event is None:
        raise ValueError("Tuning event no encontrado.")
    return event


def _ensure_status(event: OrchestratorTuningEvent, allowed_statuses: set[str], message: str) -> None:
    if event.status not in allowed_statuses:
        raise ValueError(message)


def _find_duplicate_event(
    db: Session,
    *,
    event_type: str,
    evidence: dict[str, Any],
    proposed_changes: dict[str, Any],
) -> OrchestratorTuningEvent | None:
    normalized_type = str(event_type or "").strip()
    candidate_signature = _event_semantic_signature(normalized_type, evidence, proposed_changes)
    candidates = (
        db.query(OrchestratorTuningEvent)
        .filter(OrchestratorTuningEvent.event_type == normalized_type)
        .filter(OrchestratorTuningEvent.status.in_(["proposed", "approved", "applied"]))
        .all()
    )
    for candidate in candidates:
        candidate_evidence = _json_loads(candidate.evidence_json)
        candidate_changes = _json_loads(candidate.proposed_changes_json)
        if _event_semantic_signature(candidate.event_type, candidate_evidence, candidate_changes) == candidate_signature:
            return candidate
    return None


def _find_regressed_lock(
    db: Session,
    *,
    event_type: str,
    evidence: dict[str, Any],
    proposed_changes: dict[str, Any],
) -> OrchestratorTuningEvent | None:
    normalized_type = str(event_type or "").strip()
    candidate_signature = _event_semantic_signature(normalized_type, evidence, proposed_changes)
    candidates = (
        db.query(OrchestratorTuningEvent)
        .filter(OrchestratorTuningEvent.event_type == normalized_type)
        .filter(OrchestratorTuningEvent.status == "applied")
        .filter(OrchestratorTuningEvent.evaluation_status == "regressed")
        .all()
    )
    for candidate in candidates:
        candidate_evidence = _json_loads(candidate.evidence_json)
        candidate_changes = _json_loads(candidate.proposed_changes_json)
        if _event_semantic_signature(candidate.event_type, candidate_evidence, candidate_changes) == candidate_signature:
            return candidate
    return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(tz=None).replace(tzinfo=None)
    return parsed


def _hours_since(value: datetime | None, *, now: datetime | None = None) -> float:
    if value is None:
        return 0.0
    reference = now or utc_now()
    return max((reference - value).total_seconds() / 3600.0, 0.0)


def _decayed_priority(priority: float, created_at: datetime | None, *, now: datetime | None = None) -> float:
    if created_at is None:
        return round(max(priority, 0.0), 4)
    age_hours = _hours_since(created_at, now=now)
    decay_factor = 0.5 ** (age_hours / PRIORITY_DECAY_HALF_LIFE_HOURS)
    return round(max(priority, 0.0) * decay_factor, 4)


def _build_baseline_seed(
    db: Session,
    *,
    applied_at: datetime,
    window_hours: int = DEFAULT_EVALUATION_WINDOW_HOURS,
) -> dict[str, Any]:
    since = applied_at - timedelta(hours=window_hours)
    return {
        "applied_at": applied_at.isoformat(),
        "evaluation_window_hours": int(window_hours),
        "pre_apply_summary": learning_metrics_service.get_learning_summary_snapshot(
            db,
            since=since,
            until=applied_at,
        ),
        "pre_apply_time_series_excerpt": learning_metrics_service.get_compact_time_series_excerpt(
            db,
            since=since,
            until=applied_at,
            limit=6,
        ),
    }


def _evaluation_payload(
    *,
    pre_apply_summary: dict[str, Any],
    post_apply_summary: dict[str, Any],
    window_hours: int,
    post_apply_time_series_excerpt: list[dict[str, Any]],
) -> dict[str, Any]:
    severity_delta = round(
        float(post_apply_summary.get("average_severity") or 0.0)
        - float(pre_apply_summary.get("average_severity") or 0.0),
        4,
    )
    fallback_delta = round(
        float(post_apply_summary.get("fallback_rate") or 0.0)
        - float(pre_apply_summary.get("fallback_rate") or 0.0),
        4,
    )
    low_confidence_delta = round(
        float(post_apply_summary.get("low_confidence_rate") or 0.0)
        - float(pre_apply_summary.get("low_confidence_rate") or 0.0),
        4,
    )
    return {
        "evaluation_window_hours": int(window_hours),
        "post_apply_summary": post_apply_summary,
        "post_apply_time_series_excerpt": post_apply_time_series_excerpt,
        "metric_deltas": {
            "average_severity_delta": severity_delta,
            "fallback_rate_delta": fallback_delta,
            "low_confidence_rate_delta": low_confidence_delta,
        },
    }


def _with_effective_priority(event_dict: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(event_dict)
    created_at = _parse_iso_datetime(event_dict.get("created_at"))
    enriched["effective_priority"] = _decayed_priority(float(event_dict.get("priority") or 0.0), created_at)
    return enriched


def _created_at_sort_value(event_dict: dict[str, Any]) -> float:
    created_at = _parse_iso_datetime(event_dict.get("created_at"))
    if created_at is None:
        return float("inf")
    epoch = datetime(1970, 1, 1)
    return -((created_at - epoch).total_seconds())


def get_adaptive_drift_summary(db: Session) -> dict[str, Any]:
    applied_events = (
        db.query(OrchestratorTuningEvent)
        .filter(OrchestratorTuningEvent.status.in_(["applied", "rolled_back"]))
        .all()
    )
    evaluation_counts = {
        "pending": 0,
        "improved": 0,
        "regressed": 0,
        "neutral": 0,
        "insufficient_data": 0,
    }
    for event in applied_events:
        key = str(event.evaluation_status or "pending")
        evaluation_counts[key] = evaluation_counts.get(key, 0) + 1

    evaluated_total = (
        evaluation_counts["improved"]
        + evaluation_counts["regressed"]
        + evaluation_counts["neutral"]
    )
    improvement_rate = 0.0
    regression_rate = 0.0
    if evaluated_total > 0:
        improvement_rate = round(evaluation_counts["improved"] / evaluated_total, 4)
        regression_rate = round(evaluation_counts["regressed"] / evaluated_total, 4)

    return {
        "applied_events": len(applied_events),
        "evaluation_counts": evaluation_counts,
        "improvement_rate": improvement_rate,
        "regression_rate": regression_rate,
    }


def analyze_learning_system(db: Session) -> list[OrchestratorTuningEvent]:
    summary = learning_metrics_service.get_learning_summary(db, last_hours=168)
    recent_logs = learning_metrics_service.get_recent_learning_logs(db, limit=200)
    engine = AdaptiveLearningEngine()
    recommendations = engine.analyze(summary=summary, recent_logs=recent_logs)

    current_config = orchestrator_config_service.load_orchestrator_config()
    events: list[OrchestratorTuningEvent] = []
    for recommendation in recommendations:
        evidence = dict(recommendation.get("evidence") or {})
        proposed_changes = dict(recommendation.get("proposed_changes") or {})
        regressed_lock = _find_regressed_lock(
            db,
            event_type=str(recommendation.get("event_type") or ""),
            evidence=evidence,
            proposed_changes=proposed_changes,
        )
        if regressed_lock is not None:
            continue
        duplicate = _find_duplicate_event(
            db,
            event_type=str(recommendation.get("event_type") or ""),
            evidence=evidence,
            proposed_changes=proposed_changes,
        )
        if duplicate is not None:
            events.append(duplicate)
            continue

        target_version = _normalize_version(
            proposed_changes.get("target_version"),
            default=f"{current_config.version}-proposal",
        )
        event = OrchestratorTuningEvent(
            event_type=str(recommendation.get("event_type") or "threshold_adjustment"),
            status="proposed",
            title=str(recommendation.get("title") or "Adaptive recommendation"),
            description=str(recommendation.get("description") or ""),
            evidence_json=_json_dumps(evidence),
            proposed_changes_json=_json_dumps(proposed_changes),
            confidence_score=float(recommendation.get("confidence_score") or 0.0),
            priority=float(recommendation.get("priority") or 0.0),
            evaluation_status="pending",
            observed_effect_json=_json_dumps({}),
            source_version=current_config.version,
            target_version=target_version,
        )
        db.add(event)
        events.append(event)

    db.commit()
    for event in events:
        db.refresh(event)
    return events


def list_tuning_events(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    items = db.query(OrchestratorTuningEvent).all()
    serialized = [_with_effective_priority(item.to_dict()) for item in items]
    ordered = sorted(
        serialized,
        key=lambda item: (
            0 if item.get("status") in ACTIVE_EVENT_STATUSES else 1,
            -float(item.get("effective_priority") or 0.0),
            -float(item.get("confidence_score") or 0.0),
            _created_at_sort_value(item),
        ),
        reverse=False,
    )
    return ordered[: max(1, min(int(limit or 50), 200))]


def approve_tuning_event(db: Session, event_id: str) -> dict[str, Any]:
    event = _get_event_or_raise(db, event_id)
    _ensure_status(event, {"proposed"}, "Solo se pueden aprobar eventos en estado proposed.")
    event.status = "approved"
    db.commit()
    db.refresh(event)
    return event.to_dict()


def reject_tuning_event(db: Session, event_id: str) -> dict[str, Any]:
    event = _get_event_or_raise(db, event_id)
    _ensure_status(event, {"proposed", "approved"}, "Solo se pueden rechazar eventos proposed o approved.")
    event.status = "rejected"
    db.commit()
    db.refresh(event)
    return event.to_dict()


def apply_tuning_event(db: Session, event_id: str) -> dict[str, Any]:
    event = _get_event_or_raise(db, event_id)
    _ensure_status(event, {"approved"}, "Solo se pueden aplicar eventos aprobados.")

    current_config = orchestrator_config_service.load_orchestrator_config()
    proposed_changes = _json_loads(event.proposed_changes_json)
    merged_config = _merge_config_changes(current_config, proposed_changes)
    merged_config.version = _normalize_version(event.target_version, default=merged_config.version)
    try:
        orchestrator_config_service.validate_orchestrator_config_change(current_config, merged_config)
    except ValueError:
        event.status = "invalidated"
        db.commit()
        db.refresh(event)
        raise

    applied_at = utc_now()
    observed_effect = _build_baseline_seed(
        db,
        applied_at=applied_at,
        window_hours=DEFAULT_EVALUATION_WINDOW_HOURS,
    )

    _persist_snapshot(
        db,
        event_id=event.id,
        snapshot_type="before_apply",
        version=current_config.version,
        config=current_config,
    )
    saved_config = orchestrator_config_service.save_orchestrator_config(merged_config)
    _persist_snapshot(
        db,
        event_id=event.id,
        snapshot_type="after_apply",
        version=saved_config.version,
        config=saved_config,
    )

    event.status = "applied"
    event.evaluation_status = "pending"
    event.observed_effect_json = _json_dumps(observed_effect)
    db.commit()
    db.refresh(event)
    return {
        "event": event.to_dict(),
        "config": saved_config.to_dict(),
    }


def rollback_tuning_event(db: Session, event_id: str) -> dict[str, Any]:
    event = _get_event_or_raise(db, event_id)
    _ensure_status(event, {"applied"}, "Solo se pueden revertir eventos aplicados.")

    snapshot = (
        db.query(OrchestratorConfigSnapshot)
        .filter(OrchestratorConfigSnapshot.event_id == event.id)
        .filter(OrchestratorConfigSnapshot.snapshot_type == "before_apply")
        .order_by(OrchestratorConfigSnapshot.created_at.desc())
        .first()
    )
    if snapshot is None:
        raise ValueError("No existe snapshot previo para revertir este evento.")

    restored_config = orchestrator_config_service.save_orchestrator_config(_json_loads(snapshot.config_json))
    event.status = "rolled_back"
    db.commit()
    db.refresh(event)
    return {
        "event": event.to_dict(),
        "config": restored_config.to_dict(),
    }


def evaluate_tuning_event_effect(
    db: Session,
    event_id: str,
    window_hours: int = DEFAULT_EVALUATION_WINDOW_HOURS,
) -> dict[str, Any]:
    event = _get_event_or_raise(db, event_id)
    _ensure_status(event, {"applied"}, "Solo se pueden evaluar eventos aplicados.")

    observed_effect = _json_loads(event.observed_effect_json)
    applied_at = _parse_iso_datetime(observed_effect.get("applied_at")) or event.updated_at or event.created_at
    if applied_at is None:
        raise ValueError("No se pudo determinar el momento de aplicacion del evento.")

    evaluation_now = utc_now()
    elapsed_hours = _hours_since(applied_at, now=evaluation_now)
    if elapsed_hours < MIN_EVALUATION_LAG_HOURS:
        event.evaluation_status = "insufficient_data"
        observed_effect.update(
            {
                "evaluation_window_hours": int(window_hours),
                "elapsed_hours_since_apply": round(elapsed_hours, 4),
                "minimum_evaluation_lag_hours": MIN_EVALUATION_LAG_HOURS,
                "minimum_post_apply_samples": MIN_POST_APPLY_SAMPLE_SIZE,
                "evaluation_block_reason": "minimum_time_lag_not_reached",
            }
        )
        event.observed_effect_json = _json_dumps(observed_effect)
        db.commit()
        db.refresh(event)
        return event.to_dict()

    pre_apply_summary = dict(observed_effect.get("pre_apply_summary") or {})
    if not pre_apply_summary:
        pre_apply_summary = learning_metrics_service.get_learning_summary_snapshot(
            db,
            since=applied_at - timedelta(hours=window_hours),
            until=applied_at,
        )

    post_apply_summary = learning_metrics_service.get_learning_summary_snapshot(
        db,
        since=applied_at,
        until=applied_at + timedelta(hours=window_hours),
    )
    post_apply_time_series_excerpt = learning_metrics_service.get_compact_time_series_excerpt(
        db,
        since=applied_at,
        until=applied_at + timedelta(hours=window_hours),
        limit=6,
    )
    evaluation_data = _evaluation_payload(
        pre_apply_summary=pre_apply_summary,
        post_apply_summary=post_apply_summary,
        window_hours=window_hours,
        post_apply_time_series_excerpt=post_apply_time_series_excerpt,
    )
    evaluation_data["elapsed_hours_since_apply"] = round(elapsed_hours, 4)
    evaluation_data["minimum_evaluation_lag_hours"] = MIN_EVALUATION_LAG_HOURS
    evaluation_data["minimum_post_apply_samples"] = MIN_POST_APPLY_SAMPLE_SIZE

    if int(pre_apply_summary.get("total_queries") or 0) < MIN_BASELINE_SAMPLE_SIZE:
        event.evaluation_status = "insufficient_data"
        evaluation_data["evaluation_block_reason"] = "insufficient_pre_apply_samples"
    elif int(post_apply_summary.get("total_queries") or 0) < MIN_POST_APPLY_SAMPLE_SIZE:
        event.evaluation_status = "insufficient_data"
        evaluation_data["evaluation_block_reason"] = "insufficient_post_apply_samples"
    else:
        metric_deltas = evaluation_data["metric_deltas"]
        severity_delta = float(metric_deltas["average_severity_delta"])
        fallback_delta = float(metric_deltas["fallback_rate_delta"])
        low_confidence_delta = float(metric_deltas["low_confidence_rate_delta"])

        if severity_delta <= -0.05 and (fallback_delta <= -0.05 or low_confidence_delta <= -0.05):
            event.evaluation_status = "improved"
        elif severity_delta >= 0.05 or fallback_delta >= 0.05 or low_confidence_delta >= 0.05:
            event.evaluation_status = "regressed"
        else:
            event.evaluation_status = "neutral"
        evaluation_data["evaluation_block_reason"] = ""

    observed_effect.update(evaluation_data)
    event.observed_effect_json = _json_dumps(observed_effect)
    db.commit()
    db.refresh(event)
    return event.to_dict()
