from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

from app.config import settings
from app.services.safety_constants import USAGE_GUARDRAIL_LIMITS
from app.services.utc import utc_now

_RATE_LIMIT_STATE: dict[tuple[str, str, str], list] = defaultdict(list)
_RATE_LIMIT_LOCK = Lock()


def evaluate_usage_guardrail(
    *,
    user_id: str | None,
    source_ip: str | None,
    route_path: str,
    bucket: str = "heavy_query",
) -> dict[str, Any]:
    config = _resolve_usage_guardrail_config(bucket)
    limit = int(config["limit"])
    window_seconds = int(config["window_seconds"])
    burst_limit = int(config.get("burst_limit") or 0)
    burst_window_seconds = int(config.get("burst_window_seconds") or 0)
    guardrails_active = bool(settings.usage_guardrails_active)
    if not guardrails_active:
        return {
            "allowed": True,
            "enabled": False,
            "ailex_env": settings.ailex_env,
            "safety_status": "normal",
            "bucket": bucket,
            "route_path": route_path,
            "reasons": [],
            "dominant_safety_reason": None,
            "fallback_type": None,
            "retry_after_seconds": None,
            "limit": limit,
            "window_seconds": window_seconds,
            "burst_limit": burst_limit,
            "burst_window_seconds": burst_window_seconds,
        }

    now = utc_now()
    scope_keys = _build_scope_keys(user_id=user_id, source_ip=source_ip, bucket=bucket)
    retention_window_seconds = max(window_seconds, burst_window_seconds or 0)

    with _RATE_LIMIT_LOCK:
        for scope_type, scope_value, scope_bucket in scope_keys:
            key = (scope_type, scope_value, scope_bucket)
            recent_hits = [
                hit for hit in _RATE_LIMIT_STATE[key]
                if (now - hit).total_seconds() < retention_window_seconds
            ]
            _RATE_LIMIT_STATE[key] = recent_hits
            burst_hits = []
            if burst_limit > 0 and burst_window_seconds > 0:
                burst_hits = [
                    hit for hit in recent_hits
                    if (now - hit).total_seconds() < burst_window_seconds
                ]
            long_window_hits = [
                hit for hit in recent_hits
                if (now - hit).total_seconds() < window_seconds
            ]
            if burst_limit > 0 and burst_window_seconds > 0 and len(burst_hits) >= burst_limit:
                oldest_hit = burst_hits[0]
                retry_after_seconds = max(burst_window_seconds - int((now - oldest_hit).total_seconds()), 1)
                reason = f"burst_limit_exceeded_{scope_type}"
                return {
                    "allowed": False,
                    "enabled": True,
                    "ailex_env": settings.ailex_env,
                    "safety_status": "rate_limited",
                    "bucket": bucket,
                    "route_path": route_path,
                    "reasons": [reason],
                    "dominant_safety_reason": reason,
                    "fallback_type": "rate_limited",
                    "retry_after_seconds": retry_after_seconds,
                    "limit": limit,
                    "window_seconds": window_seconds,
                    "burst_limit": burst_limit,
                    "burst_window_seconds": burst_window_seconds,
                }
            if len(long_window_hits) >= limit:
                oldest_hit = long_window_hits[0]
                retry_after_seconds = max(window_seconds - int((now - oldest_hit).total_seconds()), 1)
                reason = f"rate_limit_exceeded_{scope_type}"
                return {
                    "allowed": False,
                    "enabled": True,
                    "ailex_env": settings.ailex_env,
                    "safety_status": "rate_limited",
                    "bucket": bucket,
                    "route_path": route_path,
                    "reasons": [reason],
                    "dominant_safety_reason": reason,
                    "fallback_type": "rate_limited",
                    "retry_after_seconds": retry_after_seconds,
                    "limit": limit,
                    "window_seconds": window_seconds,
                    "burst_limit": burst_limit,
                    "burst_window_seconds": burst_window_seconds,
                }

        for scope_type, scope_value, scope_bucket in scope_keys:
            _RATE_LIMIT_STATE[(scope_type, scope_value, scope_bucket)].append(now)

    return {
        "allowed": True,
        "enabled": True,
        "ailex_env": settings.ailex_env,
        "safety_status": "normal",
        "bucket": bucket,
        "route_path": route_path,
        "reasons": [],
        "dominant_safety_reason": None,
        "fallback_type": None,
        "retry_after_seconds": None,
        "limit": limit,
        "window_seconds": window_seconds,
        "burst_limit": burst_limit,
        "burst_window_seconds": burst_window_seconds,
    }


def _resolve_usage_guardrail_config(bucket: str) -> dict[str, int]:
    configured = settings.get_usage_guardrail_bucket(bucket)
    default_config = dict(USAGE_GUARDRAIL_LIMITS.get(bucket) or USAGE_GUARDRAIL_LIMITS["heavy_query"])
    return {
        "limit": int(configured.get("limit") or default_config["limit"]),
        "window_seconds": int(configured.get("window_seconds") or default_config["window_seconds"]),
        "burst_limit": int(configured.get("burst_limit") or default_config.get("burst_limit") or 0),
        "burst_window_seconds": int(
            configured.get("burst_window_seconds") or default_config.get("burst_window_seconds") or 0
        ),
    }


def reset_usage_guardrails() -> None:
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_STATE.clear()


def _build_scope_keys(
    *,
    user_id: str | None,
    source_ip: str | None,
    bucket: str,
) -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    if str(user_id or "").strip():
        keys.append(("user", str(user_id).strip(), bucket))
    if str(source_ip or "").strip():
        keys.append(("ip", str(source_ip).strip(), bucket))
    if not keys:
        keys.append(("anonymous", "global", bucket))
    return keys
