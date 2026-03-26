from __future__ import annotations

from typing import Any


_ACTION_PROPOSALS = {
    "review_first_question": {
        "proposal": "Simplify first clarification question wording",
        "risk": "low",
        "reversible": True,
    },
    "improve_advice_generation": {
        "proposal": "Strengthen the first complete advice block before closure",
        "risk": "medium",
        "reversible": True,
    },
    "review_question_flow": {
        "proposal": "Review clarification flow order and exit criteria before advice mode",
        "risk": "low",
        "reversible": True,
    },
    "reduce_questions": {
        "proposal": "Reduce non-critical clarification questions and tighten stop conditions",
        "risk": "low",
        "reversible": True,
    },
    "improve_quick_reply_visibility": {
        "proposal": "Make quick replies more visible and align them with frequent clarification paths",
        "risk": "low",
        "reversible": True,
    },
    "accelerate_advice_transition": {
        "proposal": "Review thresholds that delay the transition from clarification to advice mode",
        "risk": "medium",
        "reversible": True,
    },
    "wait_for_more_data": {
        "proposal": "Collect more analytics data before proposing a product change",
        "risk": "low",
        "reversible": True,
    },
    "keep_monitoring": {
        "proposal": "Keep the current configuration and continue monitoring beta analytics",
        "risk": "low",
        "reversible": True,
    },
}

_PRIORITY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


def build_change_proposals(
    recommended_actions: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in recommended_actions or []:
        action = str(item.get("action") or "").strip()
        reason = str(item.get("reason") or "").strip()
        priority = _normalize_priority(item.get("priority"))
        if not action or not reason:
            continue
        key = (action.casefold(), reason.casefold())
        if key in seen:
            continue
        seen.add(key)

        template = _ACTION_PROPOSALS.get(
            action,
            {
                "proposal": "Review this recommendation manually before preparing a system change",
                "risk": "medium",
                "reversible": True,
            },
        )
        proposals.append(
            {
                "action": action,
                "proposal": template["proposal"],
                "risk": template["risk"],
                "reversible": bool(template["reversible"]),
                "reason": reason,
                "priority": priority,
            }
        )

    proposals.sort(
        key=lambda item: (
            _PRIORITY_ORDER.get(item["priority"], 3),
            item["action"],
        )
    )
    return proposals


def build_primary_change_proposal(
    primary_action: dict[str, Any] | None,
) -> dict[str, Any] | None:
    proposals = build_change_proposals([primary_action] if primary_action else [])
    if not proposals:
        return None
    return proposals[0]


def _normalize_priority(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _PRIORITY_ORDER:
        return normalized
    return "medium"
