from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services.chat_logger import sanitize_for_logging


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_selected_model_fields(model_match: dict[str, Any] | None) -> dict[str, str | None]:
    payload = dict(model_match or {})
    selected_model = payload.get("selected_model") or {}
    if not isinstance(selected_model, dict):
        selected_model = {}
    model_id = str(selected_model.get("model_id") or "").strip() or None
    template_name = str(selected_model.get("name") or "").strip() or model_id
    return {
        "selected_model": model_id,
        "selected_template": template_name,
    }


def extract_citation_validation_status(citation_validation: dict[str, Any] | None) -> str | None:
    payload = dict(citation_validation or {})
    if not payload:
        return None
    invalid_count = _safe_int(payload.get("invalid_count"))
    doubtful_count = _safe_int(payload.get("doubtful_count"))
    valid_count = _safe_int(payload.get("valid_count"))
    is_safe = payload.get("is_safe")
    if invalid_count > 0 or is_safe is False:
        return "invalid"
    if doubtful_count > 0:
        return "doubtful"
    if valid_count > 0 or is_safe is True:
        return "valid"
    return "unknown"


def extract_hallucination_guard_status(hallucination_guard: dict[str, Any] | None) -> tuple[str | None, list[str]]:
    payload = dict(hallucination_guard or {})
    if not payload:
        return None, []
    flags = payload.get("flags") or []
    normalized_flags: list[str] = []
    high_risk = False
    for item in flags:
        if not isinstance(item, dict):
            continue
        flag_type = str(item.get("flag_type") or "").strip()
        severity = str(item.get("severity") or "").strip().lower()
        if flag_type:
            normalized_flags.append(flag_type)
        if severity == "high":
            high_risk = True
    is_safe = payload.get("is_safe")
    if high_risk or is_safe is False:
        return "flagged", _dedupe(normalized_flags)
    if normalized_flags:
        return "warning", _dedupe(normalized_flags)
    if is_safe is True:
        return "safe", []
    return "unknown", []


def extract_secondary_domains(case_domains: list[Any] | None, final_case_domain: str | None) -> list[str]:
    primary = str(final_case_domain or "").strip().casefold()
    secondary: list[str] = []
    for item in case_domains or []:
        value = str(item or "").strip()
        if not value:
            continue
        if primary and value.casefold() == primary:
            continue
        secondary.append(value)
    return _dedupe(secondary)


def detect_interdomain_conflict(*payloads: dict[str, Any] | None) -> bool | None:
    explicit_values: list[bool] = []
    for payload in payloads:
        data = dict(payload or {})
        for key in (
            "had_interdomain_conflict",
            "interdomain_conflict",
            "has_interdomain_conflict",
            "domain_conflict",
        ):
            value = data.get(key)
            if isinstance(value, bool):
                explicit_values.append(value)
    if explicit_values:
        return any(explicit_values)
    return None


def derive_response_status(
    *,
    fallback_detected: bool | None = None,
    safety_status: str | None = None,
    hard_safety_intervention: bool | None = None,
    human_intervention: bool | None = None,
    review_queue_flag: bool | None = None,
    explicit_status: str | None = None,
) -> str:
    if explicit_status:
        return explicit_status
    if hard_safety_intervention:
        return "blocked"
    if human_intervention or review_queue_flag:
        return "review"
    if str(safety_status or "").strip().lower() == "degraded" or fallback_detected:
        return "degraded"
    return "success"


def load_recent_snapshots(
    *,
    storage_dir: Path,
    limit: int = 50,
    days: int = 1,
) -> list[dict[str, Any]]:
    if limit <= 0 or not storage_dir.exists():
        return []
    threshold = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    items: list[dict[str, Any]] = []
    for path in sorted(storage_dir.glob("*.jsonl"), reverse=True):
        try:
            day = datetime.strptime(path.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if day < threshold:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                items.append(payload)
                if len(items) >= limit:
                    return items
    return items


def summarize_recent_snapshots(
    *,
    storage_dir: Path,
    limit: int = 50,
    days: int = 1,
) -> dict[str, Any]:
    snapshots = load_recent_snapshots(storage_dir=storage_dir, limit=limit, days=days)
    status_counter = Counter(str(item.get("response_status") or "unknown") for item in snapshots)
    domain_counter = Counter(str(item.get("final_case_domain") or "unknown") for item in snapshots)
    fallback_count = sum(1 for item in snapshots if item.get("fallback_detected"))
    review_count = sum(1 for item in snapshots if item.get("response_status") == "review")
    degraded_count = sum(1 for item in snapshots if item.get("response_status") == "degraded")
    return sanitize_for_logging({
        "total_snapshots": len(snapshots),
        "fallback_count": fallback_count,
        "review_count": review_count,
        "degraded_count": degraded_count,
        "status_breakdown": dict(status_counter),
        "top_domains": domain_counter.most_common(5),
        "recent_items": [
            {
                "timestamp": item.get("timestamp"),
                "request_id": item.get("request_id"),
                "final_case_domain": item.get("final_case_domain"),
                "final_action_slug": item.get("final_action_slug"),
                "response_status": item.get("response_status"),
                "fallback_detected": item.get("fallback_detected"),
                "total_duration_ms": item.get("total_duration_ms"),
            }
            for item in snapshots[:10]
        ],
    })


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.casefold()
        if not value or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
