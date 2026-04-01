from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.services.chat_logger import sanitize_for_logging

ROOT_DIR = Path(__file__).resolve().parents[3]
CONVERSATION_LOG_PATH = ROOT_DIR / "logs" / "conversations.jsonl"
_QUESTION_SIMILARITY_THRESHOLD = 0.88
_MAX_HISTORY_SCAN = 50


def build_observation(
    turn_input: dict[str, Any] | None,
    response: dict[str, Any] | None,
    memory: dict[str, Any] | None,
) -> dict[str, Any]:
    safe_input = _as_dict(turn_input)
    safe_response = _as_dict(response)
    safe_memory = _as_dict(memory)
    metadata = _as_dict(safe_input.get("metadata"))
    clarification_context = _as_dict(metadata.get("clarification_context"))

    conversation_id = (
        _clean_text(metadata.get("conversation_id"))
        or _clean_text(metadata.get("conversationId"))
        or _clean_text(safe_input.get("request_id"))
        or _clean_text(safe_response.get("conversation_id"))
        or _clean_text(safe_response.get("request_id"))
        or "single-turn"
    )
    previous_turns = _load_previous_turns(conversation_id)
    previous_turn = previous_turns[-1] if previous_turns else {}

    query = _extract_query(safe_input, clarification_context)
    effective_query = (
        _clean_text(safe_input.get("query"))
        or _clean_text(safe_response.get("query"))
        or query
    )
    output_mode = _extract_output_mode(safe_response)
    question_asked = _extract_question(safe_response)
    facts_detected = _extract_facts(safe_input, safe_response, safe_memory)
    missing_information = _extract_missing_information(safe_response)
    quick_start = _clean_text(safe_response.get("quick_start"))
    strategy_stale = bool(_as_dict(_as_dict(safe_response.get("case_strategy")).get("strategy_reactivity")).get("stale"))
    confidence = _safe_float(safe_response.get("confidence_score", safe_response.get("confidence")))
    case_domain = _clean_text(safe_response.get("case_domain"))

    progress = compute_progress(previous_turn.get("facts_detected"), facts_detected)
    repeat_question = detect_repeated_question(previous_turn.get("question_asked"), question_asked)
    no_progress = not bool(progress.get("has_progress"))

    current_turn = {
        "conversation_id": conversation_id,
        "turn_number": len(previous_turns) + 1,
        "query": query,
        "effective_query": effective_query,
        "output_mode": output_mode,
        "question_asked": question_asked,
        "facts_detected": facts_detected,
        "missing_information": missing_information,
        "quick_start": quick_start,
        "strategy_stale": strategy_stale,
        "confidence": confidence,
        "case_domain": case_domain,
        "progress": progress,
        "signals": {
            "repeat_question": repeat_question,
            "no_progress": no_progress,
            "loop_detected": False,
            "domain_shift": _detect_domain_shift(previous_turn, case_domain),
            "unnecessary_clarification": _detect_unnecessary_clarification(
                output_mode=output_mode,
                question_asked=question_asked,
                missing_information=missing_information,
                quick_start=quick_start,
                progress=progress,
            ),
        },
    }
    current_turn["signals"]["loop_detected"] = detect_loop(previous_turns, current_turn)
    current_turn["timestamp"] = datetime.now(timezone.utc).isoformat()
    return sanitize_for_logging(current_turn)


def detect_loop(previous_turns: list[dict[str, Any]] | None, current_turn: dict[str, Any] | None) -> bool:
    history = [_as_dict(item) for item in (previous_turns or []) if isinstance(item, dict)]
    current = _as_dict(current_turn)
    if not current:
        return False

    window = [*history[-2:], current]
    if len(window) < 3:
        return False

    clarification_only = all(_clean_text(turn.get("output_mode")) == "clarification" for turn in window)
    if not clarification_only:
        return False

    repeated_question_pairs = 0
    for left, right in zip(window, window[1:]):
        if detect_repeated_question(left.get("question_asked"), right.get("question_asked")):
            repeated_question_pairs += 1

    no_progress_window = all(
        bool(_as_dict(turn.get("signals")).get("no_progress"))
        if "signals" in turn
        else not bool(_as_dict(turn.get("progress")).get("has_progress"))
        for turn in window
    )
    return repeated_question_pairs >= 2 and no_progress_window


def compute_progress(previous_facts: dict[str, Any] | None, current_facts: dict[str, Any] | None) -> dict[str, Any]:
    previous = _meaningful_facts(previous_facts)
    current = _meaningful_facts(current_facts)
    previous_keys = set(previous.keys())
    current_keys = set(current.keys())

    new_keys = sorted(current_keys - previous_keys)
    changed_keys = sorted(
        key for key in (current_keys & previous_keys)
        if _normalize_value(previous.get(key)) != _normalize_value(current.get(key))
    )
    delta = len(new_keys) + len(changed_keys)

    return {
        "previous_count": len(previous_keys),
        "current_count": len(current_keys),
        "new_keys": new_keys,
        "changed_keys": changed_keys,
        "delta": delta,
        "has_progress": delta > 0,
    }


def detect_repeated_question(last_question: str | None, current_question: str | None) -> bool:
    left = _normalize_text(last_question)
    right = _normalize_text(current_question)
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return True
    return SequenceMatcher(a=left, b=right).ratio() >= _QUESTION_SIMILARITY_THRESHOLD


def record_observation(
    turn_input: dict[str, Any] | None,
    response: dict[str, Any] | None,
    memory: dict[str, Any] | None,
) -> dict[str, Any]:
    observation = build_observation(turn_input, response, memory)
    _append_observation(observation)
    return observation


def _append_observation(observation: dict[str, Any]) -> None:
    CONVERSATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONVERSATION_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sanitize_for_logging(observation), ensure_ascii=False) + "\n")


def _load_previous_turns(conversation_id: str) -> list[dict[str, Any]]:
    if not conversation_id or not CONVERSATION_LOG_PATH.exists():
        return []

    matches: list[dict[str, Any]] = []
    try:
        with CONVERSATION_LOG_PATH.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if _clean_text(payload.get("conversation_id")) != conversation_id:
                    continue
                matches.append(_as_dict(payload))
    except Exception:
        return []
    return matches[-_MAX_HISTORY_SCAN:]


def _extract_query(turn_input: dict[str, Any], clarification_context: dict[str, Any]) -> str:
    return (
        _clean_text(clarification_context.get("submitted_text"))
        or _clean_text(clarification_context.get("last_user_answer"))
        or _clean_text(turn_input.get("query"))
    )


def _extract_output_mode(response: dict[str, Any]) -> str:
    conversational = _as_dict(response.get("conversational"))
    if conversational.get("should_ask_first"):
        return "clarification"
    return "advice"


def _extract_question(response: dict[str, Any]) -> str:
    conversational = _as_dict(response.get("conversational"))
    conversational_response = _as_dict(response.get("conversational_response") or response.get("conversationalResponse"))
    return (
        _clean_text(conversational.get("question"))
        or _clean_text(conversational_response.get("primary_question"))
        or ""
    )


def _extract_facts(
    turn_input: dict[str, Any],
    response: dict[str, Any],
    memory: dict[str, Any],
) -> dict[str, Any]:
    merged = {}
    merged.update(_as_dict(turn_input.get("facts")))
    merged.update(_as_dict(response.get("facts")))
    merged.update(_as_dict(memory.get("known_facts")))
    return _meaningful_facts(merged)


def _extract_missing_information(response: dict[str, Any]) -> list[str]:
    output_modes = _as_dict(response.get("output_modes"))
    user_mode = _as_dict(output_modes.get("user"))
    case_strategy = _as_dict(response.get("case_strategy"))
    procedural_strategy = _as_dict(response.get("procedural_strategy"))
    values = [
        *_as_str_list(user_mode.get("missing_information")),
        *_as_str_list(case_strategy.get("critical_missing_information")),
        *_as_str_list(case_strategy.get("ordinary_missing_information")),
        *_as_str_list(procedural_strategy.get("missing_information") or procedural_strategy.get("missing_info")),
    ]
    return _dedupe_texts(values)


def _detect_domain_shift(previous_turn: dict[str, Any], current_case_domain: str) -> bool:
    previous_domain = _clean_text(previous_turn.get("case_domain"))
    return bool(previous_domain and current_case_domain and previous_domain != current_case_domain)


def _detect_unnecessary_clarification(
    *,
    output_mode: str,
    question_asked: str,
    missing_information: list[str],
    quick_start: str,
    progress: dict[str, Any],
) -> bool:
    if output_mode != "clarification":
        return False
    if not question_asked:
        return True
    if quick_start and not missing_information:
        return True
    return bool(quick_start) and not bool(progress.get("has_progress"))


def _meaningful_facts(facts: dict[str, Any] | None) -> dict[str, Any]:
    safe = _as_dict(facts)
    return {
        key: value
        for key, value in safe.items()
        if value not in (None, "", [], {})
    }


def _normalize_value(value: Any) -> str:
    rendered = sanitize_for_logging(value)
    if isinstance(rendered, str):
        return _normalize_text(rendered)
    try:
        return json.dumps(rendered, ensure_ascii=False, sort_keys=True)
    except Exception:
        return _normalize_text(str(rendered))


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = _clean_text(item)
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
