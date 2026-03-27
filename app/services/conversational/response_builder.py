from __future__ import annotations

import re
from typing import Any

from app.services.conversational.domain_playbooks import build_alimentos_playbook
from app.services.conversational.memory_service import build_conversation_memory


def build_conversational_response(result: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = dict(result or {})
    domain = _extract_domain(payload)
    if domain != "alimentos":
        return None

    context = {
        "domain": domain,
        "query_text": _extract_query_text(payload),
        "known_facts": _collect_known_facts(payload),
        "missing_facts": _collect_missing_facts(payload),
        "clarification_context": _extract_clarification_context(payload),
        "conversation_memory": build_conversation_memory(payload),
    }
    return build_alimentos_playbook(context)


def _extract_domain(payload: dict[str, Any]) -> str:
    case_profile = payload.get("case_profile") or {}
    return str(case_profile.get("case_domain") or payload.get("case_domain") or "").strip().lower()


def _extract_query_text(payload: dict[str, Any]) -> str:
    clarification_context = _extract_clarification_context(payload)
    return str(
        payload.get("query")
        or clarification_context.get("base_query")
        or ""
    ).strip()


def _extract_clarification_context(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") or {}
    return _as_dict(metadata.get("clarification_context"))


def _collect_known_facts(payload: dict[str, Any]) -> dict[str, Any]:
    clarification_context = _extract_clarification_context(payload)
    query_text = _extract_query_text(payload)

    known_facts: dict[str, Any] = {}
    known_facts.update(_infer_facts_from_query(query_text))
    known_facts.update(_as_dict(clarification_context.get("known_facts")))
    known_facts.update(_as_dict(payload.get("facts")))
    return {
        key: value
        for key, value in known_facts.items()
        if value not in (None, "", [], {})
    }


def _collect_missing_facts(payload: dict[str, Any]) -> list[str]:
    case_strategy = _as_dict(payload.get("case_strategy"))
    procedural_strategy = _as_dict(payload.get("procedural_strategy"))

    raw_items = [
        *list(case_strategy.get("critical_missing_information") or []),
        *list(case_strategy.get("ordinary_missing_information") or []),
        *list(case_strategy.get("missing_information") or []),
        *list(procedural_strategy.get("missing_information") or []),
        *list(procedural_strategy.get("missing_info") or []),
    ]
    seen: set[str] = set()
    result: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(text)
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


_QUERY_FACT_PATTERNS: tuple[tuple[str, Any, tuple[str, ...]], ...] = (
    ("hay_hijos", "inferred", (r"\bhij[oa]s?\b", r"\bmenor(?:es)?\b")),
    ("hay_hijos_edad", "inferred", (r"\b\d{1,2}\s*(años|anos|meses|dias)\b",)),
    ("tema_alimentos", "inferred", (r"\balimento", r"\bcuota alimentaria\b", r"\bmanutencion\b")),
    ("vinculo_parental", "inferred", (r"\bpadre\b", r"\bmadre\b", r"\bprogenitor\b")),
    ("aportes_actuales", False, (
        r"\bno paga\b",
        r"\bno aporta\b",
        r"\bdej[oó] de pagar\b",
        r"\bpaga poco\b",
        r"\baporta poco\b",
        r"\birregular\b",
    )),
)


def _infer_facts_from_query(query: str) -> dict[str, Any]:
    normalized = str(query or "").strip().lower()
    if not normalized:
        return {}
    facts: dict[str, Any] = {}
    for field, value, patterns in _QUERY_FACT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, normalized):
                facts[field] = value
                break
    return facts
