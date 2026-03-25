from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.services.safety_constants import (
    HARD_REJECT_QUERY_LENGTH,
    MAX_QUERY_LENGTH,
    MAX_REPEATED_CHAR_RATIO,
    MAX_REPEATED_CHAR_RUN,
    MAX_SINGLE_TOKEN_DOMINANCE,
    MIN_QUERY_LENGTH,
)


def evaluate_query_input(raw_query: str | None) -> dict[str, Any]:
    original_query = str(raw_query or "")
    normalized_query = " ".join(original_query.split()).strip()
    reasons: list[str] = []

    if not normalized_query:
        return _result(
            decision="rejected",
            safety_status="input_rejected",
            normalized_query="",
            reasons=["empty_input"],
        )

    alnum_chars = re.sub(r"[\W_]+", "", normalized_query, flags=re.UNICODE)
    if len(alnum_chars) < MIN_QUERY_LENGTH:
        return _result(
            decision="rejected",
            safety_status="input_rejected",
            normalized_query=normalized_query,
            reasons=["input_too_short"],
        )

    if len(normalized_query) >= HARD_REJECT_QUERY_LENGTH:
        return _result(
            decision="rejected",
            safety_status="input_rejected",
            normalized_query=normalized_query[:MAX_QUERY_LENGTH],
            reasons=["input_extremely_long"],
        )

    if _looks_repetitive(normalized_query):
        return _result(
            decision="rejected",
            safety_status="input_rejected",
            normalized_query=normalized_query,
            reasons=["repetitive_or_spam_input"],
        )

    decision = "accepted"
    safety_status = "normal"
    if normalized_query != original_query.strip():
        reasons.append("input_normalized")
        decision = "normalized"
    if len(normalized_query) > MAX_QUERY_LENGTH:
        normalized_query = normalized_query[:MAX_QUERY_LENGTH].rstrip()
        reasons.append("input_truncated_for_safety")
        decision = "degraded"
        safety_status = "degraded"

    return _result(
        decision=decision,
        safety_status=safety_status,
        normalized_query=normalized_query,
        reasons=reasons,
    )


def _looks_repetitive(normalized_query: str) -> bool:
    if not normalized_query:
        return True

    char_counter = Counter(normalized_query)
    most_common_char_count = char_counter.most_common(1)[0][1]
    if most_common_char_count / max(len(normalized_query), 1) >= MAX_REPEATED_CHAR_RATIO:
        return True

    tokens = [token for token in re.split(r"\s+", normalized_query.lower()) if token]
    if not tokens:
        return True
    token_counter = Counter(tokens)
    most_common_token_count = token_counter.most_common(1)[0][1]
    if len(tokens) >= 6 and most_common_token_count / len(tokens) >= MAX_SINGLE_TOKEN_DOMINANCE:
        return True

    longest_run = max((len(match.group(0)) for match in re.finditer(r"(.)\1*", normalized_query)), default=0)
    return longest_run >= MAX_REPEATED_CHAR_RUN


def _result(
    *,
    decision: str,
    safety_status: str,
    normalized_query: str,
    reasons: list[str],
) -> dict[str, Any]:
    unique_reasons = list(dict.fromkeys(reasons))
    fallback_type = None
    if decision == "rejected":
        fallback_type = "input_invalid"
    elif decision == "degraded":
        fallback_type = "degraded_mode"
    return {
        "decision": decision,
        "accepted": decision in {"accepted", "normalized", "degraded"},
        "normalized_query": normalized_query,
        "safety_status": safety_status,
        "reasons": unique_reasons,
        "dominant_safety_reason": unique_reasons[0] if unique_reasons else None,
        "fallback_type": fallback_type,
        "excluded_from_learning": decision in {"rejected", "degraded"},
    }
