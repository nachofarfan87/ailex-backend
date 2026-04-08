from __future__ import annotations

from app.services.case_workspace_service import (
    build_case_workspace,
    build_operating_phase_reason,
    build_professional_handoff,
    build_workspace_summary,
    resolve_operating_phase,
    resolve_case_status,
)


def _payload() -> dict:
    return {
        "request_id": "req-workspace-1",
        "conversation_id": "conv-workspace-1",
        "case_domain": "alimentos",
        "conversation_state": {
            "conversation_id": "conv-workspace-1",
        },
        "case_memory": {
            "facts": {
                "hay_hijos": {"value": True, "source": "confirmed", "confidence": 1.0},
                "ingresos_otro_progenitor": {"value": 250000, "source": "confirmed", "confidence": 1.0},
            },
            "missing": {
                "critical": [
                    {
                        "key": "domicilio_relevante",
                        "label": "domicilio relevante",
                        "priority": "critical",
                        "purpose": "identify",
                        "source": "case_memory",
                    }
                ],
                "important": [],
                "optional": [],
            },
            "contradictions": [
                {
                    "key": "vinculo",
                    "prev_value": "padre",
                    "new_value": "tio",
                    "detected_at": 2,
                }
            ],
            "memory_confidence": "medium",
        },
        "case_progress": {
            "stage": "inconsistente",
            "readiness_label": "low",
            "progress_status": "blocked",
            "critical_gaps": [
                {"key": "domicilio_relevante", "label": "domicilio relevante", "priority": "critical"}
            ],
            "important_gaps": [],
            "blocking_issues": [
                {
                    "type": "contradictions",
                    "severity": "high",
                    "source": "case_memory",
                    "reason": "1 contradiction(s) detected",
                }
            ],
            "contradictions": [
                {
                    "key": "vinculo",
                    "prev_value": "padre",
                    "new_value": "tio",
                    "detected_at": 2,
                }
            ],
        },
        "case_followup": {
            "should_ask": True,
            "question": "Podes aclarar cual es el vinculo correcto?",
            "reason": "Primero conviene aclarar la contradiccion relevante antes de seguir avanzando.",
        },
        "case_summary": {
            "applies": True,
            "summary_text": "Reclamo de alimentos con datos utiles ya identificados y una contradiccion pendiente.",
            "summary_version": "v1",
        },
        "smart_strategy": {
            "strategy_mode": "clarify_critical",
            "response_goal": "obtener la ultima aclaracion critica que destraba el caso",
            "recommended_structure": "brief",
            "reason": "Modo elegido: clarify_critical.",
            "should_prioritize_action": False,
        },
        "strategy_composition_profile": {
            "allow_followup": True,
            "prioritize_action": False,
        },
        "strategy_language_profile": {
            "tone_style": "prudent",
        },
        "progression_policy": {
            "output_mode": "estrategia",
        },
        "execution_output": {
            "execution_output": {
                "what_to_do_now": ["Revisar la contradiccion.", "Confirmar el hecho correcto."],
                "documents_needed": ["Partida de nacimiento."],
            }
        },
        "fallback_used": True,
        "case_confidence": {
            "case_stage": "developing",
        },
    }


def test_resolve_case_status_prioritizes_fact_reconciliation():
    status = resolve_case_status(
        case_progress={"stage": "inconsistente", "progress_status": "blocked", "readiness_label": "low"},
        case_followup={"should_ask": True},
        case_confidence={"case_stage": "developing"},
    )

    assert status == "needs_fact_reconciliation"


def test_resolve_case_status_detects_contradictions_even_without_inconsistent_stage():
    status = resolve_case_status(
        case_progress={
            "stage": "decision",
            "progress_status": "advancing",
            "readiness_label": "medium",
            "contradictions": [{"key": "domicilio_relevante"}],
        },
        case_followup={"should_ask": False},
        case_confidence={"case_stage": "developing"},
    )

    assert status == "needs_fact_reconciliation"


def test_resolve_operating_phase_separates_status_from_movement():
    phase = resolve_operating_phase(
        case_progress={
            "stage": "decision",
            "next_step_type": "decide",
            "critical_gaps": [],
            "contradictions": [],
            "blocking_issues": [],
        },
        case_followup={"should_ask": False},
        case_status="ready_for_strategy_decision",
    )

    assert phase == "decide"


def test_build_operating_phase_reason_is_prudent_for_missing_info():
    reason = build_operating_phase_reason(
        case_progress={
            "critical_gaps": [{"key": "jurisdiccion"}],
            "contradictions": [],
            "blocking_issues": [],
        },
        case_followup={"should_ask": True},
        case_status="needs_information",
        operating_phase="clarify",
    )

    assert "dato faltante" in reason.lower() or "prioridad operativa" in reason.lower()


def test_build_workspace_summary_prefers_existing_case_summary():
    summary = build_workspace_summary(
        api_payload={
            "case_summary": {
                "applies": True,
                "summary_text": "Resumen consolidado del caso.",
            }
        },
        case_status="structuring_case",
    )

    assert summary == "Resumen consolidado del caso."


def test_build_professional_handoff_surfaces_open_items():
    handoff = build_professional_handoff(
        api_payload=_payload(),
        case_status="needs_fact_reconciliation",
        operating_phase="clarify",
        case_summary="Resumen del caso.",
        recommended_next_question="Podes aclarar cual es el vinculo correcto?",
    )

    assert handoff["ready_for_professional_review"] is False
    assert handoff["status"] == "needs_fact_reconciliation"
    assert handoff["review_readiness"] == "needs_reconciliation"
    assert handoff["primary_friction"]
    assert handoff["recommended_professional_focus"]
    assert handoff["professional_entry_point"]
    assert "domicilio relevante" in handoff["open_items"]
    assert handoff["next_question"] == "Podes aclarar cual es el vinculo correcto?"


def test_build_case_workspace_builds_required_shape():
    workspace = build_case_workspace(api_payload=_payload())

    assert workspace["case_id"] == "conv-workspace-1"
    assert workspace["workspace_version"] == "case_workspace_v1"
    assert workspace["case_status"] == "needs_fact_reconciliation"
    assert workspace["case_status_label"]
    assert workspace["case_status_helper"]
    assert workspace["operating_phase"] == "clarify"
    assert workspace["recommended_phase"] == "clarify_facts"
    assert workspace["recommended_phase_label"] == "Aclarar hechos"
    assert workspace["operating_phase_reason"]
    assert workspace["primary_focus"]["type"] == "contradiction"
    assert workspace["primary_focus"]["label"]
    assert "paso" in workspace["primary_focus"]["reason"].lower() or "procesal" in workspace["primary_focus"]["reason"].lower() or "base equivocada" in workspace["primary_focus"]["reason"].lower()
    assert workspace["case_summary"]
    assert workspace["recommended_next_question"] == "Podes aclarar cual es el vinculo correcto?"
    assert len(workspace["facts_confirmed"]) == 2
    assert workspace["facts_missing"][0]["key"] == "domicilio_relevante"
    assert workspace["facts_conflicting"][0]["key"] == "vinculo"
    assert workspace["strategy_snapshot"]["strategy_mode"] == "clarify_critical"
    assert len(workspace["action_plan"]) >= 2
    assert workspace["action_plan"][0]["id"]
    assert workspace["action_plan"][0]["step_id"] == workspace["action_plan"][0]["id"]
    assert workspace["action_plan"][0]["title"]
    assert "phase" in workspace["action_plan"][0]
    assert workspace["action_plan"][0]["phase_label"]
    assert workspace["evidence_checklist"]["critical"][0]["label"] == "Partida de nacimiento."
    assert workspace["evidence_checklist"]["critical"][0]["supports_step"] == workspace["action_plan"][0]["step_id"]
    assert workspace["risk_alerts"]
    assert workspace["professional_handoff"]["status"] == "needs_fact_reconciliation"
    assert workspace["last_updated_at"].endswith("Z")


def test_build_case_workspace_prioritizes_missing_facts_and_keeps_summary_without_question_duplication():
    payload = _payload()
    payload["case_summary"] = {}
    payload["case_memory"]["missing"]["important"] = [
        {
            "key": "documentacion_basica",
            "label": "documentacion basica",
            "priority": "medium",
            "purpose": "prove",
            "source": "case_memory",
        }
    ]
    payload["case_memory"]["missing"]["critical"].append(
        {
            "key": "jurisdiccion",
            "label": "jurisdiccion",
            "priority": "critical",
            "purpose": "identify",
            "source": "case_memory",
        }
    )

    workspace = build_case_workspace(api_payload=payload)

    assert workspace["facts_missing"][0]["key"] == "domicilio_relevante"
    assert workspace["facts_missing"][1]["key"] == "jurisdiccion"
    assert "Pregunta prioritaria:" not in workspace["case_summary"]
    assert any("dos versiones incompatibles" in item for item in workspace["professional_handoff"]["open_items"])


def test_workspace_keeps_primary_focus_primary_step_and_followup_aligned():
    workspace = build_case_workspace(api_payload=_payload())

    assert "contradiccion" in workspace["primary_focus"]["label"].lower()
    assert "contradiccion" in workspace["action_plan"][0]["title"].lower()
    assert "vinculo" in workspace["recommended_next_question"].lower()


def test_workspace_aplica_deduplicacion_global_minima_entre_pasos_y_evidencia():
    payload = _payload()
    payload["case_memory"]["contradictions"] = []
    payload["case_progress"]["contradictions"] = []
    payload["case_progress"]["blocking_issues"] = []
    payload["case_followup"] = {"should_ask": False, "question": "", "reason": ""}
    payload["case_strategy"] = {
        "recommended_actions": [
            "Reunir partida de nacimiento y prueba basica del vinculo filial.",
        ]
    }
    payload["case_memory"]["missing"]["critical"] = []
    payload["execution_output"] = {"execution_output": {}}
    payload["conflict_evidence"] = {
        "key_evidence_missing": [
            "Partida de nacimiento del hijo.",
            "Partida de nacimiento u otra acreditacion del vinculo filial.",
        ]
    }

    workspace = build_case_workspace(api_payload=payload)

    evidence_labels = [
        item["label"]
        for bucket in workspace["evidence_checklist"].values()
        if isinstance(bucket, list)
        for item in bucket
    ]
    assert any("partida de nacimiento" in step["title"].casefold() for step in workspace["action_plan"])
    assert len([label for label in evidence_labels if "partida de nacimiento" in label.casefold()]) <= 1
