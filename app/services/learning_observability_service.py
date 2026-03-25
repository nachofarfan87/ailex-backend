"""
AILEX - Servicio de observabilidad del aprendizaje adaptativo.

Capa analitica read-only sobre LearningActionLog, LearningImpactLog
y las memorias por signature/family/event_type.
No altera la logica de decision; solo consolida metricas de inspeccion.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from math import exp, log
from typing import Any

from sqlalchemy.orm import Session

from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.services.impact_memory_service import (
    TEMPORAL_DECAY_HALF_LIFE_DAYS,
    _normalize_token,
    extract_persisted_impact_metadata,
)
from app.services.utc import utc_now


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

TRACKED_STATUSES = {"improved", "regressed", "neutral"}

DRIFT_DEFAULT_RECENT_DAYS = 14
DRIFT_DEFAULT_PREVIOUS_DAYS = 14
DRIFT_SCORE_DELTA_THRESHOLD = 0.25
DRIFT_BLOCK_RATE_THRESHOLD = 0.15
DRIFT_NEGATIVE_APPEARANCE_MIN = 3

# Tamaño de lote para iteracion interna de queries.
# Evita cargar toda la tabla de golpe y elimina truncamiento silencioso.
QUERY_BATCH_SIZE = 500

# ---------------------------------------------------------------------------
# Pesos de capa centralizados
# ---------------------------------------------------------------------------

LAYER_WEIGHTS: dict[str, float] = {
    "signature": 1.0,
    "signature_family": 0.8,
    "event_type": 0.6,
}

LAYER_EVIDENCE_KEYS: list[tuple[str, str]] = [
    ("signature", "signature_evidence"),
    ("signature_family", "signature_family_evidence"),
    ("event_type", "event_type_evidence"),
]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _safe_isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _compute_decay_weight(
    created_at: datetime | None,
    *,
    reference_time: datetime,
    half_life_days: float = TEMPORAL_DECAY_HALF_LIFE_DAYS,
) -> float:
    if created_at is None:
        return 1.0
    age_seconds = max((reference_time - created_at).total_seconds(), 0.0)
    half_life_seconds = max(float(half_life_days), 1.0) * 86400.0
    return round(exp(-log(2.0) * age_seconds / half_life_seconds), 6)


def _interpret_status(
    score: float,
    raw_total: int,
    regressed: int,
    improved: int,
) -> str:
    if raw_total == 0:
        return "neutral"
    if score <= -0.35 and regressed >= 2:
        return "blocked"
    if score >= 0.5 and improved >= 2:
        return "reinforced"
    if raw_total >= 3 and abs(score) < 0.2:
        return "neutral"
    return "watch"


# ---------------------------------------------------------------------------
# Iteracion por lotes (elimina truncamiento silencioso)
# ---------------------------------------------------------------------------


def _iter_enriched_impact_rows(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict[str, Any]]:
    """Carga todos los impact rows en el rango de fechas, iterando por lotes."""
    base_query = (
        db.query(LearningImpactLog, LearningActionLog)
        .outerjoin(LearningActionLog, LearningActionLog.id == LearningImpactLog.learning_action_log_id)
        .filter(LearningImpactLog.status.in_(tuple(TRACKED_STATUSES)))
    )
    if date_from:
        base_query = base_query.filter(LearningImpactLog.created_at >= date_from)
    if date_to:
        base_query = base_query.filter(LearningImpactLog.created_at <= date_to)
    base_query = base_query.order_by(LearningImpactLog.created_at.desc())

    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch = base_query.offset(offset).limit(QUERY_BATCH_SIZE).all()
        if not batch:
            break
        for impact_log, action_log in batch:
            metadata = extract_persisted_impact_metadata(
                action_log,
                fallback_event_type=str(impact_log.event_type or ""),
            )
            rows.append({
                "impact_log": impact_log,
                "action_log": action_log,
                "signature": str(metadata["impact_signature"]),
                "signature_family": str(metadata["impact_signature_family"]),
                "event_type": _normalize_token(impact_log.event_type),
                "status": str(impact_log.status or "").strip(),
                "created_at": impact_log.created_at,
                "impact_score": _safe_float(impact_log.impact_score),
            })
        if len(batch) < QUERY_BATCH_SIZE:
            break
        offset += QUERY_BATCH_SIZE

    return rows


# ---------------------------------------------------------------------------
# Overview global
# ---------------------------------------------------------------------------


def get_overview(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    now = date_to or utc_now()
    action_query = db.query(LearningActionLog)
    impact_query = db.query(LearningImpactLog).filter(
        LearningImpactLog.status.in_(tuple(TRACKED_STATUSES))
    )
    if date_from:
        action_query = action_query.filter(LearningActionLog.created_at >= date_from)
        impact_query = impact_query.filter(LearningImpactLog.created_at >= date_from)
    if date_to:
        action_query = action_query.filter(LearningActionLog.created_at <= date_to)
        impact_query = impact_query.filter(LearningImpactLog.created_at <= date_to)

    total_observations = impact_query.count()
    total_adaptive_decisions = action_query.count()

    impact_logs = impact_query.all()
    action_logs = action_query.all()

    signatures: set[str] = set()
    families: set[str] = set()
    event_types: set[str] = set()

    reinforced = 0
    blocked = 0
    neutral_count = 0

    for action_log in action_logs:
        payload = _safe_json_loads(action_log.changes_applied_json)
        sig = str(payload.get("impact_signature") or "").strip()
        fam = str(payload.get("impact_signature_family") or "").strip()
        et = _normalize_token(action_log.event_type)
        if sig:
            signatures.add(sig)
        if fam:
            families.add(fam)
        event_types.add(et)

        reason = str(action_log.reason or "").lower()
        if "blocked" in reason:
            blocked += 1
        elif "boosted" in reason or (action_log.applied and "applied" in reason):
            reinforced += 1
        elif action_log.applied:
            reinforced += 1
        else:
            neutral_count += 1

    total_score = 0.0
    total_weighted_score = 0.0
    total_weight = 0.0
    for impact_log in impact_logs:
        score = _safe_float(impact_log.impact_score)
        total_score += score
        weight = _compute_decay_weight(impact_log.created_at, reference_time=now)
        total_weighted_score += score * weight
        total_weight += weight

    avg_impact_score = round(total_score / max(total_observations, 1), 4)
    recency_weighted_avg_score = round(
        total_weighted_score / max(total_weight, 1e-9), 4
    ) if total_weight > 0 else 0.0

    return {
        "total_observations": total_observations,
        "total_adaptive_decisions": total_adaptive_decisions,
        "unique_signatures": len(signatures),
        "unique_signature_families": len(families),
        "unique_event_types": len(event_types),
        "reinforced_decisions": reinforced,
        "blocked_decisions": blocked,
        "neutral_decisions": neutral_count,
        "avg_impact_score": avg_impact_score,
        "recency_weighted_avg_score": recency_weighted_avg_score,
    }


# ---------------------------------------------------------------------------
# Metricas por signature
# ---------------------------------------------------------------------------


def get_metrics_by_signature(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    signature_filter: str | None = None,
    event_type_filter: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    now = date_to or utc_now()
    rows = _iter_enriched_impact_rows(db, date_from=date_from, date_to=date_to)
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "signature": "",
        "signature_family": "",
        "event_type": "",
        "improved": 0,
        "regressed": 0,
        "neutral": 0,
        "weighted_score_sum": 0.0,
        "weighted_total": 0.0,
        "last_seen_at": None,
    })

    for row in rows:
        sig = row["signature"]
        if signature_filter and sig != signature_filter:
            continue
        if event_type_filter and row["event_type"] != event_type_filter:
            continue
        bucket = buckets[sig]
        bucket["signature"] = sig
        bucket["signature_family"] = row["signature_family"]
        bucket["event_type"] = row["event_type"]
        status = row["status"]
        if status in TRACKED_STATUSES:
            bucket[status] += 1
        weight = _compute_decay_weight(row["created_at"], reference_time=now)
        score_val = 1.0 if status == "improved" else (-1.0 if status == "regressed" else 0.0)
        bucket["weighted_score_sum"] += score_val * weight
        bucket["weighted_total"] += weight
        created = row["created_at"]
        if created and (bucket["last_seen_at"] is None or created > bucket["last_seen_at"]):
            bucket["last_seen_at"] = created

    results: list[dict[str, Any]] = []
    for sig, bucket in buckets.items():
        obs = bucket["improved"] + bucket["regressed"] + bucket["neutral"]
        wt = bucket["weighted_total"]
        avg_score = round(
            (bucket["improved"] - bucket["regressed"]) / max(obs, 1), 4
        )
        recency_score = round(
            bucket["weighted_score_sum"] / max(wt, 1e-9), 4
        ) if wt > 0 else 0.0
        results.append({
            "signature": sig,
            "signature_family": bucket["signature_family"],
            "event_type": bucket["event_type"],
            "observation_count": obs,
            "positive_count": bucket["improved"],
            "negative_count": bucket["regressed"],
            "neutral_count": bucket["neutral"],
            "avg_score": avg_score,
            "recency_weighted_score": recency_score,
            "last_seen_at": _safe_isoformat(bucket["last_seen_at"]),
            "status": _interpret_status(avg_score, obs, bucket["regressed"], bucket["improved"]),
        })

    results.sort(key=lambda x: (-x["observation_count"], x["signature"]))
    return results[:limit]


# ---------------------------------------------------------------------------
# Metricas por signature_family
# ---------------------------------------------------------------------------


def get_metrics_by_family(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    family_filter: str | None = None,
    event_type_filter: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    now = date_to or utc_now()
    rows = _iter_enriched_impact_rows(db, date_from=date_from, date_to=date_to)
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "signature_family": "",
        "event_type": "",
        "improved": 0,
        "regressed": 0,
        "neutral": 0,
        "weighted_score_sum": 0.0,
        "weighted_total": 0.0,
        "last_seen_at": None,
        "unique_signatures": set(),
    })

    for row in rows:
        fam = row["signature_family"]
        if family_filter and fam != family_filter:
            continue
        if event_type_filter and row["event_type"] != event_type_filter:
            continue
        bucket = buckets[fam]
        bucket["signature_family"] = fam
        bucket["event_type"] = row["event_type"]
        status = row["status"]
        if status in TRACKED_STATUSES:
            bucket[status] += 1
        weight = _compute_decay_weight(row["created_at"], reference_time=now)
        score_val = 1.0 if status == "improved" else (-1.0 if status == "regressed" else 0.0)
        bucket["weighted_score_sum"] += score_val * weight
        bucket["weighted_total"] += weight
        bucket["unique_signatures"].add(row["signature"])
        created = row["created_at"]
        if created and (bucket["last_seen_at"] is None or created > bucket["last_seen_at"]):
            bucket["last_seen_at"] = created

    results: list[dict[str, Any]] = []
    for fam, bucket in buckets.items():
        obs = bucket["improved"] + bucket["regressed"] + bucket["neutral"]
        wt = bucket["weighted_total"]
        avg_score = round(
            (bucket["improved"] - bucket["regressed"]) / max(obs, 1), 4
        )
        recency_score = round(
            bucket["weighted_score_sum"] / max(wt, 1e-9), 4
        ) if wt > 0 else 0.0
        results.append({
            "signature_family": fam,
            "event_type": bucket["event_type"],
            "observation_count": obs,
            "unique_signatures": len(bucket["unique_signatures"]),
            "positive_count": bucket["improved"],
            "negative_count": bucket["regressed"],
            "neutral_count": bucket["neutral"],
            "avg_score": avg_score,
            "recency_weighted_score": recency_score,
            "last_seen_at": _safe_isoformat(bucket["last_seen_at"]),
            "status": _interpret_status(avg_score, obs, bucket["regressed"], bucket["improved"]),
        })

    results.sort(key=lambda x: (-x["observation_count"], x["signature_family"]))
    return results[:limit]


# ---------------------------------------------------------------------------
# Metricas por event_type
# ---------------------------------------------------------------------------


def get_metrics_by_event_type(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    event_type_filter: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    now = date_to or utc_now()
    rows = _iter_enriched_impact_rows(db, date_from=date_from, date_to=date_to)
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "event_type": "",
        "improved": 0,
        "regressed": 0,
        "neutral": 0,
        "weighted_score_sum": 0.0,
        "weighted_total": 0.0,
        "last_seen_at": None,
        "unique_signatures": set(),
        "unique_families": set(),
    })

    for row in rows:
        et = row["event_type"]
        if event_type_filter and et != event_type_filter:
            continue
        bucket = buckets[et]
        bucket["event_type"] = et
        status = row["status"]
        if status in TRACKED_STATUSES:
            bucket[status] += 1
        weight = _compute_decay_weight(row["created_at"], reference_time=now)
        score_val = 1.0 if status == "improved" else (-1.0 if status == "regressed" else 0.0)
        bucket["weighted_score_sum"] += score_val * weight
        bucket["weighted_total"] += weight
        bucket["unique_signatures"].add(row["signature"])
        bucket["unique_families"].add(row["signature_family"])
        created = row["created_at"]
        if created and (bucket["last_seen_at"] is None or created > bucket["last_seen_at"]):
            bucket["last_seen_at"] = created

    results: list[dict[str, Any]] = []
    for et, bucket in buckets.items():
        obs = bucket["improved"] + bucket["regressed"] + bucket["neutral"]
        wt = bucket["weighted_total"]
        avg_score = round(
            (bucket["improved"] - bucket["regressed"]) / max(obs, 1), 4
        )
        recency_score = round(
            bucket["weighted_score_sum"] / max(wt, 1e-9), 4
        ) if wt > 0 else 0.0
        results.append({
            "event_type": et,
            "observation_count": obs,
            "unique_signatures": len(bucket["unique_signatures"]),
            "unique_families": len(bucket["unique_families"]),
            "positive_count": bucket["improved"],
            "negative_count": bucket["regressed"],
            "neutral_count": bucket["neutral"],
            "avg_score": avg_score,
            "recency_weighted_score": recency_score,
            "last_seen_at": _safe_isoformat(bucket["last_seen_at"]),
            "status": _interpret_status(avg_score, obs, bucket["regressed"], bucket["improved"]),
        })

    results.sort(key=lambda x: (-x["observation_count"], x["event_type"]))
    return results[:limit]


# ---------------------------------------------------------------------------
# Evolucion temporal
# ---------------------------------------------------------------------------


def get_timeline(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    bucket_days: int = 1,
    signature_filter: str | None = None,
    family_filter: str | None = None,
    event_type_filter: str | None = None,
) -> list[dict[str, Any]]:
    now = date_to or utc_now()
    default_from = now - timedelta(days=90)
    start = date_from or default_from
    rows = _iter_enriched_impact_rows(db, date_from=start, date_to=now)

    day_buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "improved": 0,
        "regressed": 0,
        "neutral": 0,
    })

    for row in rows:
        if signature_filter and row["signature"] != signature_filter:
            continue
        if family_filter and row["signature_family"] != family_filter:
            continue
        if event_type_filter and row["event_type"] != event_type_filter:
            continue
        created = row["created_at"]
        if created is None:
            continue
        bucket_key = _bucket_date(created, bucket_days)
        status = row["status"]
        if status in TRACKED_STATUSES:
            day_buckets[bucket_key][status] += 1

    results: list[dict[str, Any]] = []
    for date_key in sorted(day_buckets.keys()):
        bucket = day_buckets[date_key]
        obs = bucket["improved"] + bucket["regressed"] + bucket["neutral"]
        net_score = bucket["improved"] - bucket["regressed"]
        results.append({
            "date": date_key,
            "observations": obs,
            "net_score": net_score,
            "reinforced_count": bucket["improved"],
            "blocked_count": bucket["regressed"],
            "neutral_count": bucket["neutral"],
        })

    return results


def _bucket_date(dt: datetime, bucket_days: int) -> str:
    if bucket_days <= 1:
        return dt.strftime("%Y-%m-%d")
    epoch = datetime(2020, 1, 1)
    days_since = (dt - epoch).days
    bucket_start = epoch + timedelta(days=(days_since // bucket_days) * bucket_days)
    return bucket_start.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Top patrones
# ---------------------------------------------------------------------------


def get_top_patterns(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    sig_metrics = get_metrics_by_signature(db, date_from=date_from, date_to=date_to, limit=10000)
    fam_metrics = get_metrics_by_family(db, date_from=date_from, date_to=date_to, limit=10000)

    positive_sigs = sorted(
        [s for s in sig_metrics if s["avg_score"] > 0],
        key=lambda x: (-x["avg_score"], -x["observation_count"]),
    )[:top_n]

    negative_sigs = sorted(
        [s for s in sig_metrics if s["avg_score"] < 0],
        key=lambda x: (x["avg_score"], -x["observation_count"]),
    )[:top_n]

    positive_fams = sorted(
        [f for f in fam_metrics if f["avg_score"] > 0],
        key=lambda x: (-x["avg_score"], -x["observation_count"]),
    )[:top_n]

    negative_fams = sorted(
        [f for f in fam_metrics if f["avg_score"] < 0],
        key=lambda x: (x["avg_score"], -x["observation_count"]),
    )[:top_n]

    return {
        "top_positive_signatures": positive_sigs,
        "top_negative_signatures": negative_sigs,
        "top_positive_families": positive_fams,
        "top_negative_families": negative_fams,
    }


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def detect_drift(
    db: Session,
    *,
    recent_days: int = DRIFT_DEFAULT_RECENT_DAYS,
    previous_days: int = DRIFT_DEFAULT_PREVIOUS_DAYS,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    now = reference_time or utc_now()
    recent_start = now - timedelta(days=recent_days)
    previous_start = recent_start - timedelta(days=previous_days)

    recent_rows = _iter_enriched_impact_rows(db, date_from=recent_start, date_to=now)
    previous_rows = _iter_enriched_impact_rows(db, date_from=previous_start, date_to=recent_start)

    recent_stats = _compute_window_stats(recent_rows)
    previous_stats = _compute_window_stats(previous_rows)

    drift_signals: list[dict[str, Any]] = []

    # Signal 1: score delta significativo
    score_delta = recent_stats["avg_score"] - previous_stats["avg_score"]
    if abs(score_delta) >= DRIFT_SCORE_DELTA_THRESHOLD:
        direction = "declining" if score_delta < 0 else "improving"
        drift_signals.append({
            "type": "score_delta",
            "description": f"Average score shifted {direction} by {abs(score_delta):.3f}",
            "severity": "high" if abs(score_delta) >= 0.4 else "medium",
            "delta": round(score_delta, 4),
            "recent_value": recent_stats["avg_score"],
            "previous_value": previous_stats["avg_score"],
        })

    # Signal 2: suba fuerte de block_rate
    block_rate_delta = recent_stats["block_rate"] - previous_stats["block_rate"]
    if block_rate_delta >= DRIFT_BLOCK_RATE_THRESHOLD:
        drift_signals.append({
            "type": "block_rate_increase",
            "description": f"Block rate increased by {block_rate_delta:.3f}",
            "severity": "high" if block_rate_delta >= 0.3 else "medium",
            "delta": round(block_rate_delta, 4),
            "recent_value": recent_stats["block_rate"],
            "previous_value": previous_stats["block_rate"],
        })

    # Signal 3: inversion de tendencia positivo -> negativo
    if previous_stats["avg_score"] > 0.1 and recent_stats["avg_score"] < -0.1:
        drift_signals.append({
            "type": "trend_inversion",
            "description": "Trend inverted from positive to negative",
            "severity": "high",
            "recent_value": recent_stats["avg_score"],
            "previous_value": previous_stats["avg_score"],
        })

    # Signal 4: aparicion reciente de patrones negativos
    recent_negatives = _get_negative_signatures(recent_rows)
    previous_negatives = _get_negative_signatures(previous_rows)
    new_negatives = set(recent_negatives.keys()) - set(previous_negatives.keys())
    significant_new = [
        sig for sig in new_negatives
        if recent_negatives[sig] >= DRIFT_NEGATIVE_APPEARANCE_MIN
    ]
    if significant_new:
        drift_signals.append({
            "type": "new_negative_patterns",
            "description": f"{len(significant_new)} new negative signature(s) appeared",
            "severity": "medium",
            "signatures": sorted(significant_new),
        })

    # Determinar nivel de drift
    if not drift_signals:
        drift_level = "none"
    elif any(s["severity"] == "high" for s in drift_signals):
        drift_level = "high" if len(drift_signals) >= 2 else "medium"
    elif len(drift_signals) >= 2:
        drift_level = "medium"
    else:
        drift_level = "low"

    return {
        "drift_detected": bool(drift_signals),
        "drift_level": drift_level,
        "drift_signals": drift_signals,
        "compared_windows": {
            "recent": {
                "start": _safe_isoformat(recent_start),
                "end": _safe_isoformat(now),
                "days": recent_days,
                "total_observations": recent_stats["total"],
                "avg_score": recent_stats["avg_score"],
                "block_rate": recent_stats["block_rate"],
                "improved": recent_stats["improved"],
                "regressed": recent_stats["regressed"],
                "neutral": recent_stats["neutral"],
            },
            "previous": {
                "start": _safe_isoformat(previous_start),
                "end": _safe_isoformat(recent_start),
                "days": previous_days,
                "total_observations": previous_stats["total"],
                "avg_score": previous_stats["avg_score"],
                "block_rate": previous_stats["block_rate"],
                "improved": previous_stats["improved"],
                "regressed": previous_stats["regressed"],
                "neutral": previous_stats["neutral"],
            },
        },
    }


def _compute_window_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    improved = sum(1 for r in rows if r["status"] == "improved")
    regressed = sum(1 for r in rows if r["status"] == "regressed")
    neutral = sum(1 for r in rows if r["status"] == "neutral")
    total = improved + regressed + neutral
    avg_score = round((improved - regressed) / max(total, 1), 4)
    block_rate = round(regressed / max(total, 1), 4)
    return {
        "total": total,
        "improved": improved,
        "regressed": regressed,
        "neutral": neutral,
        "avg_score": avg_score,
        "block_rate": block_rate,
    }


def _get_negative_signatures(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row["status"] == "regressed":
            counts[row["signature"]] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# Decisiones adaptativas - trazabilidad
# ---------------------------------------------------------------------------


def get_recent_decisions(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    signature_filter: str | None = None,
    family_filter: str | None = None,
    event_type_filter: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = db.query(LearningActionLog).order_by(LearningActionLog.created_at.desc())
    if date_from:
        query = query.filter(LearningActionLog.created_at >= date_from)
    if date_to:
        query = query.filter(LearningActionLog.created_at <= date_to)
    if event_type_filter:
        query = query.filter(LearningActionLog.event_type == event_type_filter)

    results: list[dict[str, Any]] = []
    offset = 0
    while len(results) < limit:
        batch = query.offset(offset).limit(QUERY_BATCH_SIZE).all()
        if not batch:
            break
        for action_log in batch:
            if len(results) >= limit:
                break
            payload = _safe_json_loads(action_log.changes_applied_json)
            sig = str(payload.get("impact_signature") or "").strip()
            fam = str(payload.get("impact_signature_family") or "").strip()

            if signature_filter and sig != signature_filter:
                continue
            if family_filter and fam != family_filter:
                continue

            score_ref = payload.get("impact_score_reference") or {}
            if isinstance(score_ref, str):
                try:
                    score_ref = json.loads(score_ref)
                except (TypeError, ValueError):
                    score_ref = {}

            base_decision = "apply" if action_log.applied else "skip"
            final_decision = "applied" if action_log.applied else "skipped"
            decision_mode = str(payload.get("impact_decision_level") or "unknown")
            reason = str(action_log.reason or "")

            if "blocked" in reason:
                decision_mode = "blocked"
            elif "boosted" in reason:
                decision_mode = "boosted"
            elif "allowed" in reason:
                decision_mode = "allowed"
            elif "observed" in reason:
                decision_mode = "observed"

            dominant_signal = _determine_dominant_signal(score_ref)
            explanation_layers = _build_explanation_layers(score_ref)

            adaptive_raw = payload.get("adaptive_decision") or {}
            adaptive_decision = {
                "should_apply": adaptive_raw.get("should_apply", True),
                "confidence_adjustment": round(_safe_float(adaptive_raw.get("confidence_adjustment")), 4),
                "risk_level": str(adaptive_raw.get("risk_level") or "low"),
                "reasoning": str(adaptive_raw.get("reasoning") or ""),
                "applied_rules": list(adaptive_raw.get("applied_rules") or []),
            } if adaptive_raw else None

            results.append({
                "id": action_log.id,
                "created_at": _safe_isoformat(action_log.created_at),
                "event_type": action_log.event_type,
                "recommendation_type": action_log.recommendation_type,
                "base_decision": base_decision,
                "final_decision": final_decision,
                "decision_mode": decision_mode,
                "dominant_signal": dominant_signal,
                "explanation_layers": explanation_layers,
                "thresholds_used": _extract_thresholds(),
                "impact_decision_reason": str(payload.get("impact_decision_reason") or ""),
                "impact_score_reference": {
                    "signature": sig,
                    "signature_family": fam,
                    "decision_level": str(payload.get("impact_decision_level") or ""),
                    "decision_source": str(payload.get("impact_decision_source") or ""),
                },
                "adaptive_decision": adaptive_decision,
                "confidence_score": action_log.confidence_score,
                "priority": action_log.priority,
                "impact_status": action_log.impact_status,
            })

        if len(batch) < QUERY_BATCH_SIZE:
            break
        offset += QUERY_BATCH_SIZE

    return results


def _determine_dominant_signal(score_ref: dict[str, Any]) -> dict[str, Any]:
    """Devuelve un dict enriquecido con capa, direccion, score y referencia."""
    for layer_name, evidence_key in LAYER_EVIDENCE_KEYS:
        evidence = score_ref.get(evidence_key) or {}
        if not evidence.get("available") or not evidence.get("strong_enough"):
            continue
        score = _safe_float(evidence.get("score"))
        signal = str(evidence.get("dominant_signal") or "none")
        if signal in ("improved", "regressed"):
            direction = "positive" if signal == "improved" else "negative"
            return {
                "layer": layer_name,
                "direction": direction,
                "score": round(score, 4),
                "reference": str(evidence.get("key") or ""),
            }
    return {
        "layer": "none",
        "direction": "neutral",
        "score": 0.0,
        "reference": "",
    }


def _build_explanation_layers(score_ref: dict[str, Any]) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    for layer_name, evidence_key in LAYER_EVIDENCE_KEYS:
        evidence = score_ref.get(evidence_key) or {}
        if not evidence:
            continue
        score = _safe_float(evidence.get("score"))
        available = bool(evidence.get("available"))
        strong = bool(evidence.get("strong_enough"))

        if score > 0:
            effect = "reinforce"
        elif score < 0:
            effect = "block"
        else:
            effect = "neutral"

        weight = LAYER_WEIGHTS.get(layer_name, 0.5)

        layers.append({
            "layer": layer_name,
            "reference": str(evidence.get("key") or ""),
            "score": score,
            "effect": effect,
            "weight": weight,
            "available": available,
            "strong_enough": strong,
            "raw_total": _safe_int(evidence.get("raw_total")),
            "weighted_total": round(_safe_float(evidence.get("weighted_total")), 4),
            "memory_confidence": round(_safe_float(evidence.get("memory_confidence")), 4),
        })

    return layers


def _extract_thresholds() -> dict[str, Any]:
    from app.services.learning_adaptation_policy import LEVEL_RULES
    result: dict[str, Any] = {}
    for level, rules in LEVEL_RULES.items():
        result[level] = {
            "negative_threshold": rules["negative_threshold"],
            "positive_threshold": rules["positive_threshold"],
            "min_raw_total": rules["min_raw_total"],
            "min_weighted_total": rules["min_weighted_total"],
        }
    return result
