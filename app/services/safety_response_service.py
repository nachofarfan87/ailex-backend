from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def build_safety_error_response(
    *,
    status_code: int,
    request_id: str,
    safety_status: str,
    dominant_safety_reason: str | None,
    fallback_type: str | None,
    message: str,
    reasons: list[str],
    excluded_from_learning: bool,
    retry_after_seconds: int | None = None,
    details: dict[str, Any] | None = None,
    severity: str | None = None,
    protective_mode_active: bool = False,
) -> JSONResponse:
    unique_reasons = list(dict.fromkeys(reasons))
    resolved_severity = severity or "warning"
    detail = {
        "request_id": request_id,
        "message": message,
        "reasons": unique_reasons,
        "safety_status": safety_status,
        "dominant_safety_reason": dominant_safety_reason,
        "fallback_type": fallback_type,
        "excluded_from_learning": bool(excluded_from_learning),
        "retry_after_seconds": retry_after_seconds,
        "severity": resolved_severity,
        "protective_mode_active": protective_mode_active,
    }
    payload = {
        "request_id": request_id,
        "status": "error",
        "safety_status": safety_status,
        "dominant_safety_reason": dominant_safety_reason,
        "fallback_type": fallback_type,
        "severity": resolved_severity,
        "message": message,
        "reasons": unique_reasons,
        "excluded_from_learning": bool(excluded_from_learning),
        "retry_after_seconds": retry_after_seconds,
        "protective_mode_active": protective_mode_active,
        "detail": detail,
        "details": dict(details or {}),
    }
    return JSONResponse(status_code=status_code, content=payload)
