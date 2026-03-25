from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
BASE_LOG_DIR = BACKEND_DIR / "data" / "chat_logs"


def _ensure_log_dir() -> Path:
    BASE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return BASE_LOG_DIR


def _get_log_file_path() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_dir = _ensure_log_dir()
    return log_dir / f"{today}.jsonl"


def _to_json_safe(data: Any) -> Any:
    if data is None or isinstance(data, (str, int, float, bool)):
        return data

    if isinstance(data, dict):
        return {str(key): _to_json_safe(value) for key, value in data.items()}

    if isinstance(data, (list, tuple, set)):
        return [_to_json_safe(item) for item in data]

    if isinstance(data, Path):
        return str(data)

    if isinstance(data, datetime):
        if data.tzinfo is None:
            return data.replace(tzinfo=timezone.utc).isoformat()
        return data.isoformat()

    try:
        json.dumps(data)
        return data
    except Exception:
        return str(data)


def sanitize_for_logging(data: Any) -> Any:
    """
    Punto central de saneamiento para logs.

    Hoy normaliza datos a un formato JSON-serializable sin perder contenido.
    En futuras iteraciones puede incorporar redaccion/anonimizacion de campos
    sensibles sin cambiar a los llamadores.
    """
    return _to_json_safe(data)


def _normalize_user_fields(user: Any) -> dict[str, Any]:
    if user is None:
        return {
            "user_id": None,
            "username": None,
            "email": None,
        }

    username = getattr(user, "username", None) or getattr(user, "nombre", None)
    email = getattr(user, "email", None)
    user_id = getattr(user, "id", None)

    return {
        "user_id": sanitize_for_logging(user_id),
        "username": sanitize_for_logging(username),
        "email": sanitize_for_logging(email),
    }


def build_chat_log_entry(
    *,
    user: Any = None,
    session_id: Optional[str] = None,
    query: str,
    response_payload: Optional[Dict[str, Any]] = None,
    response_summary: Optional[str] = None,
    facts: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    document_mode: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    forum: Optional[str] = None,
    case_domain: Optional[str] = None,
    case_domains: Any = None,
    confidence: Optional[float] = None,
    warnings: Any = None,
    response_time_ms: Optional[int] = None,
    has_generated_document: bool = False,
    saved_consulta_id: Optional[str] = None,
    saved_for_user: bool = False,
    saved_at: Optional[str] = None,
    persistence_warning: Optional[str] = None,
    db_persisted: bool = False,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    user_fields = _normalize_user_fields(user)
    safe_response_payload = sanitize_for_logging(response_payload or {})

    if response_summary is None and isinstance(safe_response_payload, dict):
        reasoning = safe_response_payload.get("reasoning") or {}
        if isinstance(reasoning, dict):
            response_summary = (
                reasoning.get("short_answer")
                or reasoning.get("case_analysis")
                or safe_response_payload.get("query")
            )

    return {
        "timestamp": now,
        **user_fields,
        "session_id": sanitize_for_logging(session_id),
        "query": sanitize_for_logging(query),
        "response_payload": safe_response_payload,
        "response_summary": sanitize_for_logging(response_summary),
        "facts": sanitize_for_logging(facts or {}),
        "metadata": sanitize_for_logging(metadata or {}),
        "document_mode": sanitize_for_logging(document_mode),
        "jurisdiction": sanitize_for_logging(jurisdiction),
        "forum": sanitize_for_logging(forum),
        "case_domain": sanitize_for_logging(case_domain),
        "case_domains": sanitize_for_logging(case_domains or []),
        "confidence": sanitize_for_logging(confidence),
        "warnings": sanitize_for_logging(warnings or []),
        "response_time_ms": sanitize_for_logging(response_time_ms),
        "has_generated_document": bool(has_generated_document),
        "saved_consulta_id": sanitize_for_logging(saved_consulta_id),
        "saved_for_user": bool(saved_for_user),
        "saved_at": sanitize_for_logging(saved_at),
        "persistence_warning": sanitize_for_logging(persistence_warning),
        "db_persisted": bool(db_persisted),
    }


def log_chat_interaction(entry: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
    try:
        raw_entry = dict(entry or {})
        if kwargs:
            raw_entry.update(kwargs)

        if "timestamp" not in raw_entry:
            raw_entry["timestamp"] = datetime.now(timezone.utc).isoformat()

        safe_entry = sanitize_for_logging(raw_entry)
        file_path = _get_log_file_path()

        with file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
