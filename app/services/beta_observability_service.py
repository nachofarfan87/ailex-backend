from __future__ import annotations

import json
import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.services.beta_observability_helpers import (
    derive_response_status,
    summarize_recent_snapshots,
    utc_now_iso,
)
from app.services.beta_observability_schema import BetaObservabilitySnapshot
from app.services.chat_logger import sanitize_for_logging


logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
BETA_OBSERVABILITY_LOG_DIR = BACKEND_DIR / "data" / "observability" / "beta"


class BetaObservabilityContext:
    def __init__(
        self,
        snapshot: BetaObservabilitySnapshot,
        *,
        storage_dir: Path | None = None,
        sink_logger: logging.Logger | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.storage_dir = storage_dir or BETA_OBSERVABILITY_LOG_DIR
        self.sink_logger = sink_logger or logger
        self.started_at = time.perf_counter()

    def update(self, **fields: Any) -> None:
        normalized = _normalize_update_fields(fields)
        snapshot_data = self.snapshot.to_dict()
        for key, value in normalized.items():
            if key == "stage_durations_ms":
                stage_durations = dict(snapshot_data.get("stage_durations_ms") or {})
                stage_durations.update(value)
                snapshot_data["stage_durations_ms"] = stage_durations
                continue
            if key == "internal_warnings":
                snapshot_data["internal_warnings"] = _merge_lists(snapshot_data.get("internal_warnings"), value)
                continue
            if key == "secondary_domains":
                snapshot_data["secondary_domains"] = _merge_lists(snapshot_data.get("secondary_domains"), value)
                continue
            if key == "top_level_domains_detected":
                snapshot_data["top_level_domains_detected"] = _merge_lists(snapshot_data.get("top_level_domains_detected"), value)
                continue
            if key == "hallucination_flags":
                snapshot_data["hallucination_flags"] = _merge_lists(snapshot_data.get("hallucination_flags"), value)
                continue
            if key == "metadata":
                merged_metadata = dict(snapshot_data.get("metadata") or {})
                merged_metadata.update(dict(value or {}))
                snapshot_data["metadata"] = merged_metadata
                continue
            snapshot_data[key] = value
        self.snapshot = replace(self.snapshot, **snapshot_data)

    def record_stage_duration(self, stage_name: str, started_at: float) -> None:
        if not stage_name:
            return
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        self.update(stage_durations_ms={stage_name: elapsed_ms})

    def finalize(
        self,
        *,
        response_status: str | None = None,
        total_duration_ms: int | None = None,
        emit: bool = True,
    ) -> dict[str, Any]:
        if total_duration_ms is None:
            total_duration_ms = int((time.perf_counter() - self.started_at) * 1000)
        self.update(
            timestamp=self.snapshot.timestamp or utc_now_iso(),
            total_duration_ms=total_duration_ms,
            response_status=derive_response_status(
                fallback_detected=self.snapshot.fallback_detected,
                safety_status=self.snapshot.safety_status,
                hard_safety_intervention=self.snapshot.hard_safety_intervention,
                human_intervention=self.snapshot.human_intervention,
                review_queue_flag=self.snapshot.review_queue_flag,
                explicit_status=response_status,
            ),
        )
        payload = self.snapshot.to_dict()
        if emit:
            emit_beta_observability_snapshot(payload, storage_dir=self.storage_dir, sink_logger=self.sink_logger)
        return payload

    def fail(
        self,
        *,
        error_message: str,
        response_status: str = "blocked",
        total_duration_ms: int | None = None,
        emit: bool = True,
    ) -> dict[str, Any]:
        self.update(
            error_message=error_message,
            hard_safety_intervention=response_status == "blocked",
        )
        return self.finalize(
            response_status=response_status,
            total_duration_ms=total_duration_ms,
            emit=emit,
        )


def start_beta_observability_context(
    *,
    request_id: str,
    trace_id: str | None = None,
    query: str | None = None,
    normalized_query: str | None = None,
    jurisdiction: str | None = None,
    forum: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    protective_mode_active: bool | None = None,
    safety_status: str | None = None,
    metadata: dict[str, Any] | None = None,
    storage_dir: Path | None = None,
    sink_logger: logging.Logger | None = None,
) -> BetaObservabilityContext:
    snapshot = BetaObservabilitySnapshot(
        timestamp=utc_now_iso(),
        request_id=request_id,
        trace_id=trace_id or request_id,
        query=query,
        normalized_query=normalized_query,
        jurisdiction=jurisdiction,
        forum=forum,
        user_id=user_id,
        session_id=session_id,
        protective_mode_active=protective_mode_active,
        safety_status=safety_status,
        metadata=sanitize_for_logging(metadata or {}),
    )
    return BetaObservabilityContext(snapshot, storage_dir=storage_dir, sink_logger=sink_logger)


def update_beta_observability_context(
    context: BetaObservabilityContext | None,
    **fields: Any,
) -> None:
    if context is None:
        return
    context.update(**fields)


def finalize_beta_observability_context(
    context: BetaObservabilityContext | None,
    *,
    response_status: str | None = None,
    total_duration_ms: int | None = None,
    emit: bool = True,
) -> dict[str, Any] | None:
    if context is None:
        return None
    return context.finalize(
        response_status=response_status,
        total_duration_ms=total_duration_ms,
        emit=emit,
    )


def fail_beta_observability_context(
    context: BetaObservabilityContext | None,
    *,
    error_message: str,
    response_status: str = "blocked",
    total_duration_ms: int | None = None,
    emit: bool = True,
) -> dict[str, Any] | None:
    if context is None:
        return None
    return context.fail(
        error_message=error_message,
        response_status=response_status,
        total_duration_ms=total_duration_ms,
        emit=emit,
    )


def emit_beta_observability_snapshot(
    payload: dict[str, Any],
    *,
    storage_dir: Path | None = None,
    sink_logger: logging.Logger | None = None,
) -> None:
    safe_payload = sanitize_for_logging(payload)
    resolved_storage_dir = storage_dir or BETA_OBSERVABILITY_LOG_DIR
    resolved_logger = sink_logger or logger
    try:
        resolved_storage_dir.mkdir(parents=True, exist_ok=True)
        log_path = resolved_storage_dir / f"{utc_now_iso()[:10]}.jsonl"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_payload, ensure_ascii=False) + "\n")
        resolved_logger.info(json.dumps(safe_payload, ensure_ascii=False))
    except Exception:
        resolved_logger.exception("No se pudo emitir el snapshot de beta observability.")


def summarize_beta_observability(
    *,
    limit: int = 50,
    days: int = 1,
    storage_dir: Path | None = None,
) -> dict[str, Any]:
    return summarize_recent_snapshots(
        storage_dir=storage_dir or BETA_OBSERVABILITY_LOG_DIR,
        limit=limit,
        days=days,
    )


def _normalize_update_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if key in {"internal_warnings", "secondary_domains", "top_level_domains_detected", "hallucination_flags"}:
            normalized[key] = [str(item).strip() for item in value if str(item).strip()]
            continue
        normalized[key] = sanitize_for_logging(value)
    return normalized


def _merge_lists(current: Any, incoming: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for collection in (current or [], incoming or []):
        if isinstance(collection, list):
            values = collection
        else:
            values = [collection]
        for item in values:
            value = str(item or "").strip()
            normalized = value.casefold()
            if not value or normalized in seen:
                continue
            seen.add(normalized)
            result.append(value)
    return result
