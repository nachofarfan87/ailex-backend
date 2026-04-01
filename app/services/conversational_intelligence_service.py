# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\conversational_intelligence_service.py
from __future__ import annotations

import re
import unicodedata
from typing import Any


SHORT_MESSAGE_MAX_TOKENS = 2
SHORT_MESSAGE_MAX_CHARS = 12
STALL_TURN_THRESHOLD = 4
CLARIFICATION_LOAD_TURN_THRESHOLD = 3
READY_TO_ADVANCE_TURN_THRESHOLD = 3
PRESSURE_STALLED_WEIGHT = 2
PRESSURE_CLARIFICATION_WEIGHT = 2
PRESSURE_LOW_COOPERATION_WEIGHT = 1
VAGUE_RESPONSES = {
    "si",
    "sí",
    "no",
    "no se",
    "nose",
    "no se bien",
    "no sabria",
    "ok",
    "dale",
    "aja",
    "ajá",
}


def resolve_conversational_intelligence(
    *,
    conversation_state: dict[str, Any] | None,
    dialogue_policy: dict[str, Any] | None,
    conversation_memory: dict[str, Any] | None = None,
    normalized_input: dict[str, Any] | None = None,
    pipeline_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del pipeline_payload

    state = _as_dict(conversation_state)
    policy = dict(dialogue_policy or {})
    memory = _normalize_memory(conversation_memory or _as_dict(state.get("conversation_memory")))
    progress = _as_dict(state.get("progress_signals"))
    user_message = _extract_user_message(normalized_input)
    turn_count = int(state.get("turn_count") or 0)
    case_completeness = _clean_text(progress.get("case_completeness")).lower() or "low"
    dominant_missing_key = _canonical_key(policy.get("dominant_missing_key"))
    dominant_missing_purpose = _clean_text(policy.get("dominant_missing_purpose")).lower()
    asked_missing_history = _as_str_list(memory.get("asked_missing_keys_history"))

    same_missing_repetition = _count_same_missing_repetitions(
        asked_missing_keys=asked_missing_history,
        dominant_missing_key=dominant_missing_key,
    )
    low_user_cooperation = _detect_low_user_cooperation(
        user_message=user_message,
        turn_count=turn_count,
        dialogue_policy=policy,
        conversation_memory=memory,
    )
    high_clarification_load = _detect_high_clarification_load(
        state=state,
        dialogue_policy=policy,
        conversation_memory=memory,
    )
    stalled_conversation = _detect_stalled_conversation(
        state=state,
        dialogue_policy=policy,
        conversation_memory=memory,
        same_missing_repetition=same_missing_repetition,
    )
    ready_to_advance = _detect_ready_to_advance(
        state=state,
        dialogue_policy=policy,
        high_clarification_load=high_clarification_load,
        low_user_cooperation=low_user_cooperation,
        stalled_conversation=stalled_conversation,
    )
    conversational_pressure_score = _resolve_conversational_pressure_score(
        stalled_conversation=stalled_conversation,
        high_clarification_load=high_clarification_load,
        low_user_cooperation=low_user_cooperation,
    )

    conversation_status = _resolve_conversation_status(
        stalled_conversation=stalled_conversation,
        high_clarification_load=high_clarification_load,
        low_user_cooperation=low_user_cooperation,
        ready_to_advance=ready_to_advance,
    )
    recommended_adjustment = _resolve_recommended_adjustment(
        stalled_conversation=stalled_conversation,
        high_clarification_load=high_clarification_load,
        low_user_cooperation=low_user_cooperation,
        ready_to_advance=ready_to_advance,
    )
    confidence = _resolve_intelligence_confidence(
        stalled_conversation=stalled_conversation,
        high_clarification_load=high_clarification_load,
        low_user_cooperation=low_user_cooperation,
        ready_to_advance=ready_to_advance,
        same_missing_repetition=same_missing_repetition,
        turn_count=turn_count,
        case_completeness=case_completeness,
        dominant_missing_key=dominant_missing_key,
        dominant_missing_purpose=dominant_missing_purpose,
    )

    return {
        "conversation_status": conversation_status,
        "signals": {
            "stalled_conversation": stalled_conversation,
            "high_clarification_load": high_clarification_load,
            "low_user_cooperation": low_user_cooperation,
            "ready_to_advance": ready_to_advance,
        },
        "conversational_pressure_score": conversational_pressure_score,
        "recommended_adjustment": recommended_adjustment,
        "confidence": confidence,
    }


def apply_conversational_intelligence_to_policy(
    *,
    dialogue_policy: dict[str, Any] | None,
    conversational_intelligence: dict[str, Any] | None,
) -> dict[str, Any]:
    policy = dict(dialogue_policy or {})
    intelligence = dict(conversational_intelligence or {})
    if not policy:
        return policy

    adjusted = dict(policy)
    adjustment = _clean_text(intelligence.get("recommended_adjustment")).lower()
    signals = _as_dict(intelligence.get("signals"))
    legally_blocked = _is_legally_blocked(policy)
    can_relax = _can_relax_policy(policy)

    if adjustment == "reduce_questions":
        adjusted["max_questions"] = min(_safe_int(adjusted.get("max_questions"), default=1), 1)
        if adjusted.get("action") == "ask" and can_relax:
            adjusted["action"] = "hybrid"
        adjusted["should_ask_first"] = adjusted.get("action") == "ask"
        adjusted["should_offer_partial_guidance"] = adjusted.get("action") in {"hybrid", "advise"}
        if _clean_text(adjusted.get("guidance_strength")).lower() == "low" and can_relax:
            adjusted["guidance_strength"] = "medium"

    elif adjustment == "advance_with_guidance":
        if adjusted.get("action") == "ask" and can_relax:
            adjusted["action"] = "hybrid"
        adjusted["should_ask_first"] = adjusted.get("action") == "ask"
        adjusted["should_offer_partial_guidance"] = True
        current_strength = _clean_text(adjusted.get("guidance_strength")).lower()
        if current_strength in {"", "low", "medium"} and not legally_blocked:
            adjusted["guidance_strength"] = "high"
        adjusted["max_questions"] = min(_safe_int(adjusted.get("max_questions"), default=1), 1)

    elif adjustment == "simplify_response":
        adjusted["max_questions"] = 1
        adjusted["should_ask_first"] = adjusted.get("action") == "ask"
        current_strength = _clean_text(adjusted.get("guidance_strength")).lower()
        if current_strength == "high":
            adjusted["guidance_strength"] = "medium"
        adjusted["should_offer_partial_guidance"] = adjusted.get("action") in {"hybrid", "advise"}

    if _clean_text(adjusted.get("guidance_strength")).lower() == "low":
        adjusted["should_ask_first"] = True
    if _clean_text(adjusted.get("guidance_strength")).lower() == "high":
        adjusted["should_offer_partial_guidance"] = True

    if signals.get("ready_to_advance") and adjusted.get("action") == "ask" and can_relax:
        adjusted["action"] = "hybrid"
        adjusted["should_ask_first"] = False
        adjusted["should_offer_partial_guidance"] = True

    if legally_blocked:
        adjusted["action"] = "ask"
        adjusted["should_ask_first"] = True
        adjusted["max_questions"] = max(_safe_int(adjusted.get("max_questions"), default=1), 1)
        adjusted["should_offer_partial_guidance"] = adjusted.get("action") in {"hybrid", "advise"}

    return adjusted


def _detect_stalled_conversation(
    *,
    state: dict[str, Any],
    dialogue_policy: dict[str, Any],
    conversation_memory: dict[str, Any],
    same_missing_repetition: int,
) -> bool:
    progress = _as_dict(state.get("progress_signals"))
    turn_count = int(state.get("turn_count") or 0)
    case_completeness = _clean_text(progress.get("case_completeness")).lower() or "low"
    loop_risk = _clean_text(dialogue_policy.get("loop_risk")).lower()
    last_missing = _canonical_key(conversation_memory.get("last_dominant_missing_key"))
    current_missing = _canonical_key(dialogue_policy.get("dominant_missing_key"))

    if same_missing_repetition >= 2:
        return True
    if turn_count < STALL_TURN_THRESHOLD:
        return False
    if loop_risk == "high" and case_completeness in {"low", "medium"}:
        return True
    if current_missing and current_missing == last_missing and case_completeness in {"low", "medium"}:
        return True
    return False


def _detect_high_clarification_load(
    *,
    state: dict[str, Any],
    dialogue_policy: dict[str, Any],
    conversation_memory: dict[str, Any],
) -> bool:
    progress = _as_dict(state.get("progress_signals"))
    turn_count = int(state.get("turn_count") or 0)
    question_count = int(progress.get("question_count") or 0)
    action = _clean_text(dialogue_policy.get("action")).lower()
    guidance_strength = _clean_text(dialogue_policy.get("guidance_strength")).lower()
    policy_stage = _clean_text(dialogue_policy.get("policy_stage")).lower()
    last_action = _clean_text(conversation_memory.get("last_dialogue_action")).lower()
    last_turn_type = _clean_text(conversation_memory.get("last_turn_type")).lower()

    if turn_count < CLARIFICATION_LOAD_TURN_THRESHOLD:
        return False
    if question_count >= 3 and action in {"ask", "hybrid"}:
        return True
    if action == "ask" and last_action == "ask":
        return True
    if policy_stage == "clarify" and guidance_strength == "low":
        return True
    if last_turn_type == "clarification" and action == "ask":
        return True
    return False


def _detect_low_user_cooperation(
    *,
    user_message: str,
    turn_count: int,
    dialogue_policy: dict[str, Any],
    conversation_memory: dict[str, Any],
) -> bool:
    if turn_count < 3 or not user_message:
        return False

    short_message = _is_short_message(user_message)
    vague_message = _is_vague_message(user_message)
    low_novelty = _has_low_novelty(user_message=user_message, conversation_memory=conversation_memory)
    repeated_like_previous = _is_repeated_like_previous(user_message=user_message, conversation_memory=conversation_memory)
    action = _clean_text(dialogue_policy.get("action")).lower()
    last_action = _clean_text(conversation_memory.get("last_dialogue_action")).lower()

    if action not in {"ask", "hybrid"} or last_action not in {"ask", "hybrid"}:
        return False
    if vague_message and (repeated_like_previous or low_novelty):
        return True
    if short_message and vague_message and low_novelty:
        return True
    return False


def _detect_ready_to_advance(
    *,
    state: dict[str, Any],
    dialogue_policy: dict[str, Any],
    high_clarification_load: bool,
    low_user_cooperation: bool,
    stalled_conversation: bool,
) -> bool:
    progress = _as_dict(state.get("progress_signals"))
    turn_count = int(state.get("turn_count") or 0)
    case_completeness = _clean_text(progress.get("case_completeness")).lower() or "low"
    blocking_missing = bool(progress.get("blocking_missing"))
    action = _clean_text(dialogue_policy.get("action")).lower()
    guidance_strength = _clean_text(dialogue_policy.get("guidance_strength")).lower()
    loop_risk = _clean_text(dialogue_policy.get("loop_risk")).lower()

    if blocking_missing or stalled_conversation:
        return False
    if _has_core_blocking_missing(dialogue_policy):
        return False
    if turn_count < READY_TO_ADVANCE_TURN_THRESHOLD:
        return False
    if case_completeness == "high" and loop_risk != "high" and not high_clarification_load and not low_user_cooperation:
        return True
    if case_completeness == "medium" and action in {"hybrid", "advise"} and guidance_strength == "high" and loop_risk == "low" and not high_clarification_load and not low_user_cooperation:
        return True
    return False


def _resolve_conversation_status(
    *,
    stalled_conversation: bool,
    high_clarification_load: bool,
    low_user_cooperation: bool,
    ready_to_advance: bool,
) -> str:
    if ready_to_advance:
        return "ready_to_advance"
    if stalled_conversation:
        return "stalled"
    if high_clarification_load:
        return "overloaded"
    if low_user_cooperation:
        return "fragile"
    return "stable"


def _resolve_recommended_adjustment(
    *,
    stalled_conversation: bool,
    high_clarification_load: bool,
    low_user_cooperation: bool,
    ready_to_advance: bool,
) -> str:
    if ready_to_advance:
        return "advance_with_guidance"
    if stalled_conversation or high_clarification_load:
        return "reduce_questions"
    if low_user_cooperation:
        return "simplify_response"
    return "keep_policy"


def _resolve_intelligence_confidence(
    *,
    stalled_conversation: bool,
    high_clarification_load: bool,
    low_user_cooperation: bool,
    ready_to_advance: bool,
    same_missing_repetition: int,
    turn_count: int,
    case_completeness: str,
    dominant_missing_key: str,
    dominant_missing_purpose: str,
) -> str:
    active_signals = sum(
        1
        for flag in (stalled_conversation, high_clarification_load, low_user_cooperation, ready_to_advance)
        if flag
    )
    if ready_to_advance and (stalled_conversation or high_clarification_load):
        return "low"
    if same_missing_repetition >= 2 and dominant_missing_key:
        return "high"
    if ready_to_advance and case_completeness == "high" and not _is_core_identify_or_enable(dominant_missing_purpose, "relevant"):
        return "high"
    if active_signals >= 2:
        return "medium"
    if low_user_cooperation and turn_count < 4:
        return "low"
    if dominant_missing_key or dominant_missing_purpose:
        return "medium"
    return "low"


def _resolve_conversational_pressure_score(
    *,
    stalled_conversation: bool,
    high_clarification_load: bool,
    low_user_cooperation: bool,
) -> int:
    score = 0
    if stalled_conversation:
        score += PRESSURE_STALLED_WEIGHT
    if high_clarification_load:
        score += PRESSURE_CLARIFICATION_WEIGHT
    if low_user_cooperation:
        score += PRESSURE_LOW_COOPERATION_WEIGHT
    return score


def _can_relax_policy(policy: dict[str, Any] | None) -> bool:
    return not _is_legally_blocked(policy)


def _is_legally_blocked(policy: dict[str, Any] | None) -> bool:
    data = dict(policy or {})
    if bool(data.get("blocking_missing")):
        return True
    if _clean_text(data.get("action")).lower() == "ask" and _has_core_blocking_missing(data):
        return True
    return _has_core_blocking_missing(data)


def _has_core_blocking_missing(policy: dict[str, Any] | None) -> bool:
    data = dict(policy or {})
    purpose = _clean_text(data.get("dominant_missing_purpose")).lower()
    importance = _clean_text(data.get("dominant_missing_importance")).lower()
    return _is_core_identify_or_enable(purpose, importance)


def _is_core_identify_or_enable(purpose: str, importance: str) -> bool:
    return importance == "core" and purpose in {"identify", "enable"}


def _count_same_missing_repetitions(*, asked_missing_keys: list[str], dominant_missing_key: str) -> int:
    if not dominant_missing_key:
        return 0
    return sum(1 for item in asked_missing_keys if _canonical_key(item) == dominant_missing_key)


def _extract_user_message(normalized_input: dict[str, Any] | None) -> str:
    data = _as_dict(normalized_input)
    metadata = _as_dict(data.get("metadata"))
    clarification_context = _as_dict(metadata.get("clarification_context"))
    return _clean_text(
        clarification_context.get("submitted_text")
        or clarification_context.get("last_user_answer")
        or data.get("query")
    )


def _is_short_or_vague_message(message: str) -> bool:
    return _is_short_message(message) or _is_vague_message(message)


def _is_short_message(message: str) -> bool:
    normalized = _normalize_text(message).replace("_", " ").strip()
    tokens = [token for token in normalized.split() if token]
    if len(tokens) <= SHORT_MESSAGE_MAX_TOKENS:
        return True
    if len(normalized) <= SHORT_MESSAGE_MAX_CHARS:
        return True
    return False


def _is_vague_message(message: str) -> bool:
    normalized = _normalize_text(message).replace("_", " ").strip()
    return normalized in VAGUE_RESPONSES


def _has_low_novelty(*, user_message: str, conversation_memory: dict[str, Any]) -> bool:
    normalized_message = _normalize_text(user_message).replace("_", " ").strip()
    previous = _normalize_text(conversation_memory.get("last_user_message") or "").replace("_", " ").strip()
    if not normalized_message or not previous:
        return False
    if normalized_message == previous:
        return True
    current_tokens = _tokenize(normalized_message)
    previous_tokens = _tokenize(previous)
    if not current_tokens:
        return False
    overlap = len(current_tokens.intersection(previous_tokens))
    return overlap >= max(1, min(len(current_tokens), len(previous_tokens)) - 1)


def _is_repeated_like_previous(*, user_message: str, conversation_memory: dict[str, Any]) -> bool:
    normalized_message = _normalize_text(user_message).replace("_", " ").strip()
    previous = _normalize_text(conversation_memory.get("last_user_message") or "").replace("_", " ").strip()
    if not normalized_message or not previous:
        return False
    if normalized_message == previous:
        return True
    return normalized_message in previous or previous in normalized_message


def _normalize_memory(raw: dict[str, Any] | None) -> dict[str, Any]:
    memory = dict(raw or {})
    return {
        "last_dialogue_action": _clean_text(memory.get("last_dialogue_action")),
        "last_guidance_strength": _clean_text(memory.get("last_guidance_strength")),
        "last_dominant_missing_key": _clean_text(memory.get("last_dominant_missing_key")),
        "last_turn_type": _clean_text(memory.get("last_turn_type")),
        "asked_missing_keys_history": _as_str_list(memory.get("asked_missing_keys_history")),
        "last_user_message": _clean_text(memory.get("last_user_message")),
    }


def _tokenize(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value) if token}


def _canonical_key(value: Any) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized[:80]


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean_text(value))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.casefold()


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
