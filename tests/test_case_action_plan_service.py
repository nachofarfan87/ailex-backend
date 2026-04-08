from __future__ import annotations

from app.services.case_action_plan_service import build_case_action_plan


def test_build_case_action_plan_prioritizes_unblock_step():
    plan = build_case_action_plan(
        api_payload={
            "case_followup": {
                "should_ask": True,
                "question": "Podes aclarar cual es el vinculo correcto?",
                "reason": "Primero conviene aclarar la contradiccion relevante antes de seguir avanzando.",
            },
            "case_progress": {
                "contradictions": [
                    {"key": "vinculo", "prev_value": "padre", "new_value": "tio"},
                ],
            },
            "execution_output": {
                "execution_output": {
                    "what_to_do_now": ["Presentar el escrito inicial."],
                }
            },
        },
        case_status="needs_fact_reconciliation",
        operating_phase="clarify",
    )

    assert plan[0]["priority"] == "high"
    assert "contradiccion" in plan[0]["title"].lower()
    assert plan[0]["is_primary"] is True
    assert plan[0]["step_id"] == plan[0]["id"]
    assert plan[0]["phase"] == "clarify"
    assert plan[0]["phase_label"]
    assert plan[1]["depends_on"] == [plan[0]["id"]]
    assert plan[1]["status"] == "blocked"
    assert plan[1]["blocked_by_missing_info"] is True


def test_build_case_action_plan_uses_execution_and_documents_when_available():
    plan = build_case_action_plan(
        api_payload={
            "execution_output": {
                "execution_output": {
                    "what_to_do_now": ["Presentar el escrito inicial.", "Pedir medida provisoria."],
                    "documents_needed": ["Partida de nacimiento.", "Comprobantes de gastos."],
                    "where_to_go": ["Juzgado de familia competente."],
                }
            }
        },
        case_status="ready_for_execution",
        operating_phase="execute",
    )

    titles = [step["title"] for step in plan]
    assert any("presentar el escrito inicial" in title.lower() for title in titles)
    assert any(title == "Reunir documentacion clave" for title in titles)
    assert any(title == "Confirmar donde tramitarlo" for title in titles)
    assert any(step["phase"] == "file" for step in plan)
    assert any(step["phase"] == "prove" for step in plan)


def test_build_case_action_plan_falls_back_to_strategy_steps_without_inventing():
    plan = build_case_action_plan(
        api_payload={
            "case_strategy": {
                "recommended_actions": [
                    "Ordenar la estrategia principal.",
                    "Revisar la prueba disponible.",
                ]
            }
        },
        case_status="ready_for_strategy_decision",
        operating_phase="decide",
    )

    assert len(plan) == 2
    assert plan[0]["source_hint"] == "case_strategy.recommended_actions"
    assert plan[0]["phase"] == "decide"


def test_build_case_action_plan_returns_empty_without_signals():
    plan = build_case_action_plan(
        api_payload={},
        case_status="intake_in_progress",
        operating_phase="structure",
    )

    assert plan == []
