from __future__ import annotations

from app.services.auto_healing_executor import (
    build_change_proposals,
    build_primary_change_proposal,
)


def test_build_change_proposals_maps_known_actions_to_safe_templates():
    proposals = build_change_proposals(
        [
            {
                "action": "review_first_question",
                "reason": "high_dropoff_turn_1",
                "priority": "high",
            },
            {
                "action": "improve_advice_generation",
                "reason": "low_effectiveness",
                "priority": "high",
            },
        ]
    )

    assert proposals == [
        {
            "action": "improve_advice_generation",
            "proposal": "Strengthen the first complete advice block before closure",
            "risk": "medium",
            "reversible": True,
            "reason": "low_effectiveness",
            "priority": "high",
        },
        {
            "action": "review_first_question",
            "proposal": "Simplify first clarification question wording",
            "risk": "low",
            "reversible": True,
            "reason": "high_dropoff_turn_1",
            "priority": "high",
        },
    ]


def test_build_change_proposals_falls_back_safely_for_unknown_actions():
    proposals = build_change_proposals(
        [
            {
                "action": "custom_manual_review",
                "reason": "unknown_signal",
                "priority": "medium",
            }
        ]
    )

    assert proposals == [
        {
            "action": "custom_manual_review",
            "proposal": "Review this recommendation manually before preparing a system change",
            "risk": "medium",
            "reversible": True,
            "reason": "unknown_signal",
            "priority": "medium",
        }
    ]


def test_build_change_proposals_deduplicates_same_action_and_reason():
    proposals = build_change_proposals(
        [
            {
                "action": "reduce_questions",
                "reason": "high_clarification_rate",
                "priority": "medium",
            },
            {
                "action": "reduce_questions",
                "reason": "high_clarification_rate",
                "priority": "medium",
            },
        ]
    )

    assert len(proposals) == 1
    assert proposals[0]["action"] == "reduce_questions"


def test_build_primary_change_proposal_returns_first_ranked_proposal():
    proposal = build_primary_change_proposal(
        {
            "action": "review_question_flow",
            "reason": "low_closure_rate",
            "priority": "high",
        }
    )

    assert proposal == {
        "action": "review_question_flow",
        "proposal": "Review clarification flow order and exit criteria before advice mode",
        "risk": "low",
        "reversible": True,
        "reason": "low_closure_rate",
        "priority": "high",
    }
