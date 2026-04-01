# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\intent_resolution_service.py
from __future__ import annotations

import re
import unicodedata
from typing import Any


ACTION_NOW_PATTERNS = (
    "que tengo que hacer",
    "que hago",
    "como arranco",
    "como empiezo",
    "como inicio",
    "donde tengo que ir",
    "donde voy",
    "que documentos llevo",
    "que llevo",
    "que documentos necesito",
)
PROCESS_GUIDANCE_PATTERNS = (
    "como inicio",
    "como empiezo",
    "como arranco",
    "como se inicia",
    "primer paso",
    "pasos para",
    "tramite",
    "proceso",
    "donde presento",
)
DOCUMENT_GUIDANCE_PATTERNS = (
    "que documentos",
    "que llevo",
    "que papeles",
    "documentacion",
    "documentos necesito",
    "que tengo que llevar",
)
STRATEGY_GUIDANCE_PATTERNS = (
    "que puedo pedir",
    "que me conviene pedir",
    "que estrategia",
    "como conviene plantearlo",
    "que pedir ya",
    "que reclamo",
)
CLARIFICATION_PATTERNS = (
    "no se",
    "no entiendo",
    "explicame",
    "aclarame",
    "cual seria",
)
HIGH_URGENCY_PATTERNS = (
    "manana",
    "mañana",
    "hoy",
    "ya",
    "ahora",
    "esta semana",
)
MEDIUM_URGENCY_PATTERNS = (
    "pronto",
    "cuanto antes",
    "primero",
    "arrancar",
    "empezar",
    "iniciar",
)


def resolve_intent_resolution(
    *,
    normalized_input: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None = None,
    dialogue_policy: dict[str, Any] | None = None,
    conversational_intelligence: dict[str, Any] | None = None,
    pipeline_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del conversation_state

    query = _extract_query(normalized_input=normalized_input, pipeline_payload=pipeline_payload)
    normalized_query = _normalize_text(query)
    policy = dict(dialogue_policy or {})
    intelligence = dict(conversational_intelligence or {})

    intent_type, matched_signals = _resolve_intent_type(
        normalized_query=normalized_query,
        dialogue_policy=policy,
        conversational_intelligence=intelligence,
    )
    urgency, urgency_signals = _resolve_urgency(normalized_query)
    confidence = _resolve_confidence(
        intent_type=intent_type,
        urgency=urgency,
        matched_signals=matched_signals,
        policy=policy,
    )

    return {
        "intent_type": intent_type,
        "urgency": urgency,
        "practical_intent": intent_type in {"action_now", "process_guidance", "document_guidance"},
        "matched_signals": matched_signals,
        "urgency_signals": urgency_signals,
        "confidence": confidence,
        "should_prioritize_execution_output": intent_type in {"action_now", "process_guidance", "document_guidance"} or urgency == "high",
    }


def _resolve_intent_type(
    *,
    normalized_query: str,
    dialogue_policy: dict[str, Any],
    conversational_intelligence: dict[str, Any],
) -> tuple[str, list[str]]:
    signals: list[str] = []

    if _has_any_pattern(normalized_query, ACTION_NOW_PATTERNS):
        signals.append("action_now_phrase")
        return "action_now", signals
    if _has_any_pattern(normalized_query, DOCUMENT_GUIDANCE_PATTERNS):
        signals.append("document_phrase")
        return "document_guidance", signals
    if _has_any_pattern(normalized_query, PROCESS_GUIDANCE_PATTERNS):
        signals.append("process_phrase")
        return "process_guidance", signals
    if _has_any_pattern(normalized_query, STRATEGY_GUIDANCE_PATTERNS):
        signals.append("strategy_phrase")
        return "strategy_guidance", signals
    if _has_any_pattern(normalized_query, CLARIFICATION_PATTERNS):
        signals.append("clarification_phrase")
        return "clarification_needed", signals
    if len(_tokenize(normalized_query)) <= 4 and _clean_text(dialogue_policy.get("action")).lower() == "ask":
        signals.append("short_followup_with_ask_policy")
        return "clarification_needed", signals
    if _as_dict(conversational_intelligence.get("signals")).get("ready_to_advance"):
        signals.append("ready_to_advance_context")
        return "process_guidance", signals
    return "general_information", signals


def _resolve_urgency(normalized_query: str) -> tuple[str, list[str]]:
    signals: list[str] = []
    if _has_any_pattern(normalized_query, HIGH_URGENCY_PATTERNS):
        signals.append("high_urgency_phrase")
        return "high", signals
    if _has_any_pattern(normalized_query, MEDIUM_URGENCY_PATTERNS):
        signals.append("medium_urgency_phrase")
        return "medium", signals
    return "low", signals


def _resolve_confidence(
    *,
    intent_type: str,
    urgency: str,
    matched_signals: list[str],
    policy: dict[str, Any],
) -> str:
    if intent_type == "general_information" and not matched_signals:
        return "low"
    if intent_type in {"action_now", "process_guidance", "document_guidance"} and urgency in {"medium", "high"}:
        return "high"
    if intent_type == "clarification_needed" and _clean_text(policy.get("action")).lower() == "ask":
        return "high"
    if matched_signals:
        return "medium"
    return "low"


def _extract_query(*, normalized_input: dict[str, Any] | None, pipeline_payload: dict[str, Any] | None) -> str:
    data = _as_dict(normalized_input)
    payload = _as_dict(pipeline_payload)
    metadata = _as_dict(data.get("metadata"))
    clarification_context = _as_dict(metadata.get("clarification_context"))
    return _clean_text(
        clarification_context.get("submitted_text")
        or clarification_context.get("last_user_answer")
        or data.get("query")
        or payload.get("query")
    )


def _has_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text) if token]


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean_text(value))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.casefold()


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}
