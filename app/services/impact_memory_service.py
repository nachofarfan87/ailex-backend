from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from math import exp, log
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.services.utc import utc_now


TRACKED_STATUSES = {"improved", "regressed", "neutral"}
UNKNOWN_TOKEN = "unknown"
SIGNATURE_METADATA_VERSION = "v3"
TEMPORAL_DECAY_STRATEGY = "exponential_half_life"
TEMPORAL_DECAY_HALF_LIFE_DAYS = 30.0


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _normalize_token(value: Any, default: str = UNKNOWN_TOKEN) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or default


def _normalize_domains(values: Any) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        token = _normalize_token(value, default="")
        if token:
            normalized.append(token)
    return sorted(set(normalized))


def _normalize_threshold_review(proposed_changes: dict[str, Any]) -> dict[str, Any]:
    threshold_review = _as_dict(proposed_changes.get("threshold_review"))
    normalized: dict[str, Any] = {}
    for key in ("low_confidence_threshold", "low_decision_confidence_threshold"):
        if key not in threshold_review:
            continue
        value = threshold_review.get(key)
        try:
            normalized[key] = round(float(value), 2)
        except (TypeError, ValueError):
            normalized[key] = None
    return normalized


def _bucket_threshold_value(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return UNKNOWN_TOKEN
    if number < 0.4:
        return "very_low"
    if number < 0.55:
        return "low"
    if number < 0.7:
        return "balanced"
    return "strict"


def normalize_recommendation_context(recommendation: dict) -> dict[str, Any]:
    event_type = _normalize_token(recommendation.get("event_type"))
    proposed_changes = _as_dict(recommendation.get("proposed_changes"))
    normalized_context: dict[str, Any] = {
        "metadata_version": SIGNATURE_METADATA_VERSION,
        "event_type": event_type,
        "signature": event_type,
        "signature_family": event_type,
        "components": [],
        "normalized_fields": {},
    }

    if event_type == "domain_override":
        prefer_hybrid_domains = _normalize_domains(proposed_changes.get("prefer_hybrid_domains_add"))
        force_full_domains = _normalize_domains(proposed_changes.get("force_full_pipeline_domains_add"))

        if prefer_hybrid_domains and not force_full_domains:
            domain_token = prefer_hybrid_domains[0] if len(prefer_hybrid_domains) == 1 else "multi"
            normalized_context["components"] = ["prefer_hybrid", domain_token]
            normalized_context["signature"] = f"{event_type}:prefer_hybrid:{domain_token}"
            normalized_context["signature_family"] = f"{event_type}:prefer_hybrid"
            normalized_context["normalized_fields"] = {
                "prefer_hybrid_domains": prefer_hybrid_domains,
                "domain_count_bucket": "single" if len(prefer_hybrid_domains) == 1 else "multi",
            }
            return normalized_context

        if force_full_domains and not prefer_hybrid_domains:
            domain_token = force_full_domains[0] if len(force_full_domains) == 1 else "multi"
            normalized_context["components"] = ["force_full", domain_token]
            normalized_context["signature"] = f"{event_type}:force_full:{domain_token}"
            normalized_context["signature_family"] = f"{event_type}:force_full"
            normalized_context["normalized_fields"] = {
                "force_full_domains": force_full_domains,
                "domain_count_bucket": "single" if len(force_full_domains) == 1 else "multi",
            }
            return normalized_context

        if prefer_hybrid_domains or force_full_domains:
            normalized_context["components"] = ["mixed", "multi"]
            normalized_context["signature"] = f"{event_type}:mixed:multi"
            normalized_context["signature_family"] = f"{event_type}:mixed"
            normalized_context["normalized_fields"] = {
                "prefer_hybrid_domains": prefer_hybrid_domains,
                "force_full_domains": force_full_domains,
            }
            return normalized_context

        return normalized_context

    if event_type == "threshold_adjustment":
        threshold_review = _normalize_threshold_review(proposed_changes)
        dimensions: list[str] = []
        magnitude_buckets: dict[str, str] = {}
        if "low_confidence_threshold" in threshold_review:
            dimensions.append("low_confidence")
            magnitude_buckets["low_confidence"] = _bucket_threshold_value(
                threshold_review.get("low_confidence_threshold")
            )
        if "low_decision_confidence_threshold" in threshold_review:
            dimensions.append("low_decision_confidence")
            magnitude_buckets["low_decision_confidence"] = _bucket_threshold_value(
                threshold_review.get("low_decision_confidence_threshold")
            )

        if dimensions:
            dimensions = sorted(set(dimensions))
            dimension_token = "+".join(dimensions)
            normalized_context["components"] = dimensions
            normalized_context["signature"] = f"{event_type}:{dimension_token}"
            normalized_context["signature_family"] = f"{event_type}:thresholds"
            normalized_context["normalized_fields"] = {
                "threshold_review": threshold_review,
                "magnitude_buckets": magnitude_buckets,
            }
            return normalized_context

    return normalized_context


def build_impact_signature(recommendation: dict) -> str:
    return str(normalize_recommendation_context(recommendation)["signature"])


def build_impact_signature_family(recommendation: dict) -> str:
    return str(normalize_recommendation_context(recommendation)["signature_family"])


def _infer_signature_family(signature: str, event_type: str) -> str:
    normalized_signature = str(signature or "").strip()
    normalized_event_type = _normalize_token(event_type)

    if normalized_signature.startswith("domain_override:prefer_hybrid:"):
        return "domain_override:prefer_hybrid"
    if normalized_signature.startswith("domain_override:force_full:"):
        return "domain_override:force_full"
    if normalized_signature.startswith("domain_override:mixed:"):
        return "domain_override:mixed"
    if normalized_signature.startswith("threshold_adjustment:"):
        return "threshold_adjustment:thresholds"
    return normalized_event_type


def extract_persisted_impact_metadata(
    action_log: LearningActionLog | None,
    *,
    fallback_event_type: str,
) -> dict[str, Any]:
    if action_log is None:
        normalized_event_type = _normalize_token(fallback_event_type)
        return {
            "impact_signature": normalized_event_type,
            "impact_signature_family": normalized_event_type,
            "metadata_version": "legacy",
            "metadata_source": "impact_log_fallback",
        }

    payload = _safe_json_loads(action_log.changes_applied_json)
    score_reference = _as_dict(payload.get("impact_score_reference"))
    signature = str(payload.get("impact_signature") or score_reference.get("signature") or "").strip()
    signature_family = str(
        payload.get("impact_signature_family")
        or score_reference.get("signature_family")
        or ""
    ).strip()
    normalized_event_type = _normalize_token(fallback_event_type)

    if not signature:
        signature = normalized_event_type
    if not signature_family:
        signature_family = _infer_signature_family(signature, normalized_event_type)

    metadata_version = str(
        payload.get("impact_metadata_version")
        or score_reference.get("metadata_version")
        or "legacy"
    ).strip() or "legacy"

    return {
        "impact_signature": signature,
        "impact_signature_family": signature_family,
        "metadata_version": metadata_version,
        "metadata_source": "action_log",
    }


def _compute_decay_weight(
    created_at: datetime | None,
    *,
    reference_time: datetime,
    half_life_days: float,
) -> float:
    if created_at is None:
        return 1.0
    age_seconds = max((reference_time - created_at).total_seconds(), 0.0)
    half_life_seconds = max(float(half_life_days), 1.0) * 86400.0
    return round(exp(-log(2.0) * age_seconds / half_life_seconds), 6)


def _safe_isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dominant_signal(weighted_counts: dict[str, float]) -> str:
    ranking = sorted(
        ((status, float(weighted_counts.get(status, 0.0))) for status in ("improved", "regressed", "neutral")),
        key=lambda item: (-item[1], item[0]),
    )
    top_status, top_value = ranking[0]
    if top_value <= 0.0:
        return "none"
    if len(ranking) > 1 and abs(top_value - ranking[1][1]) < 1e-9:
        return "mixed"
    return top_status


def _build_memory(
    rows: list[dict[str, Any]],
    *,
    scope: str,
    reference_time: datetime,
    half_life_days: float,
) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "raw_counts": {"improved": 0, "regressed": 0, "neutral": 0},
            "weighted_counts": {"improved": 0.0, "regressed": 0.0, "neutral": 0.0},
            "family": "",
            "latest_seen_at": None,
            "oldest_seen_at": None,
        }
    )

    for row in rows:
        key = str(row.get("key") or "").strip()
        status = str(row.get("status") or "").strip()
        family = str(row.get("family") or "").strip()
        created_at = row.get("created_at")
        if not key or status not in TRACKED_STATUSES:
            continue
        weight = _compute_decay_weight(
            created_at,
            reference_time=reference_time,
            half_life_days=half_life_days,
        )
        bucket = counts[key]
        bucket["raw_counts"][status] += 1
        bucket["weighted_counts"][status] += weight
        if family and not bucket["family"]:
            bucket["family"] = family
        if created_at is not None:
            latest_seen_at = bucket["latest_seen_at"]
            oldest_seen_at = bucket["oldest_seen_at"]
            bucket["latest_seen_at"] = created_at if latest_seen_at is None else max(latest_seen_at, created_at)
            bucket["oldest_seen_at"] = created_at if oldest_seen_at is None else min(oldest_seen_at, created_at)

    impact_memory: dict[str, dict[str, Any]] = {}
    for key, event_counts in counts.items():
        raw_counts = dict(event_counts["raw_counts"])
        weighted_counts = {
            status: round(float(value), 6) for status, value in dict(event_counts["weighted_counts"]).items()
        }
        raw_total = int(sum(raw_counts.values()))
        weighted_total = round(float(sum(weighted_counts.values())), 6)
        score = (
            (float(weighted_counts["improved"]) - float(weighted_counts["regressed"])) / weighted_total
            if weighted_total
            else 0.0
        )
        impact_memory[key] = {
            "improved": int(raw_counts["improved"]),
            "regressed": int(raw_counts["regressed"]),
            "neutral": int(raw_counts["neutral"]),
            "raw_total": raw_total,
            "weighted_improved": weighted_counts["improved"],
            "weighted_regressed": weighted_counts["regressed"],
            "weighted_neutral": weighted_counts["neutral"],
            "weighted_total": weighted_total,
            "score": round(float(score), 4),
            "scope": scope,
            "family": str(event_counts.get("family") or key),
            "dominant_signal": _dominant_signal(weighted_counts),
            "latest_seen_at": _safe_isoformat(event_counts.get("latest_seen_at")),
            "oldest_seen_at": _safe_isoformat(event_counts.get("oldest_seen_at")),
            "temporal_decay": {
                "strategy": TEMPORAL_DECAY_STRATEGY,
                "half_life_days": float(half_life_days),
                "reference_time": _safe_isoformat(reference_time),
            },
        }

    return impact_memory


def get_impact_by_event_type(
    db: Session,
    limit: int = 50,
    *,
    reference_time: datetime | None = None,
    half_life_days: float = TEMPORAL_DECAY_HALF_LIFE_DAYS,
) -> dict:
    reference_time = reference_time or utc_now()
    logs = (
        db.query(LearningImpactLog)
        .filter(LearningImpactLog.status.in_(tuple(TRACKED_STATUSES)))
        .order_by(LearningImpactLog.created_at.desc())
        .limit(max(1, int(limit or 50)))
        .all()
    )

    rows = [
        {
            "key": _normalize_token(log.event_type),
            "status": str(log.status or "").strip(),
            "family": _normalize_token(log.event_type),
            "created_at": log.created_at,
        }
        for log in logs
    ]
    return _build_memory(
        rows,
        scope="event_type",
        reference_time=reference_time,
        half_life_days=half_life_days,
    )


def get_impact_by_signature(
    db: Session,
    limit: int = 100,
    *,
    reference_time: datetime | None = None,
    half_life_days: float = TEMPORAL_DECAY_HALF_LIFE_DAYS,
) -> dict:
    reference_time = reference_time or utc_now()
    logs = (
        db.query(LearningImpactLog, LearningActionLog)
        .outerjoin(LearningActionLog, LearningActionLog.id == LearningImpactLog.learning_action_log_id)
        .filter(LearningImpactLog.status.in_(tuple(TRACKED_STATUSES)))
        .order_by(LearningImpactLog.created_at.desc())
        .limit(max(1, int(limit or 100)))
        .all()
    )

    rows: list[dict[str, Any]] = []
    for impact_log, action_log in logs:
        metadata = extract_persisted_impact_metadata(
            action_log,
            fallback_event_type=str(impact_log.event_type or ""),
        )
        rows.append(
            {
                "key": str(metadata["impact_signature"]),
                "status": str(impact_log.status or "").strip(),
                "family": str(metadata["impact_signature_family"]),
                "created_at": impact_log.created_at,
            }
        )

    return _build_memory(
        rows,
        scope="signature",
        reference_time=reference_time,
        half_life_days=half_life_days,
    )


def get_impact_by_signature_family(
    db: Session,
    limit: int = 100,
    *,
    reference_time: datetime | None = None,
    half_life_days: float = TEMPORAL_DECAY_HALF_LIFE_DAYS,
) -> dict:
    reference_time = reference_time or utc_now()
    logs = (
        db.query(LearningImpactLog, LearningActionLog)
        .outerjoin(LearningActionLog, LearningActionLog.id == LearningImpactLog.learning_action_log_id)
        .filter(LearningImpactLog.status.in_(tuple(TRACKED_STATUSES)))
        .order_by(LearningImpactLog.created_at.desc())
        .limit(max(1, int(limit or 100)))
        .all()
    )

    rows: list[dict[str, Any]] = []
    for impact_log, action_log in logs:
        metadata = extract_persisted_impact_metadata(
            action_log,
            fallback_event_type=str(impact_log.event_type or ""),
        )
        rows.append(
            {
                "key": str(metadata["impact_signature_family"]),
                "status": str(impact_log.status or "").strip(),
                "family": str(metadata["impact_signature_family"]),
                "created_at": impact_log.created_at,
            }
        )

    return _build_memory(
        rows,
        scope="signature_family",
        reference_time=reference_time,
        half_life_days=half_life_days,
    )
