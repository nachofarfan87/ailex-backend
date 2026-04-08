from __future__ import annotations

from app.services.case_evidence_service import build_case_evidence_checklist


def test_build_case_evidence_checklist_groups_critical_and_recommended_items():
    checklist = build_case_evidence_checklist(
        api_payload={
            "evidence_reasoning_links": {
                "critical_evidentiary_gaps": ["Partida de nacimiento."],
                "requirement_links": [
                    {
                        "requirement": "Acreditar necesidades del hijo.",
                        "support_level": "bajo",
                        "evidence_missing": ["Comprobantes de gastos del hijo."],
                        "strategic_note": "Sin eso el reclamo queda debil.",
                    },
                    {
                        "requirement": "Acreditar ingresos del obligado.",
                        "support_level": "medio",
                        "evidence_missing": ["Recibos de sueldo o indicios de ingresos."],
                        "strategic_note": "Ayuda a cuantificar la cuota.",
                    },
                ],
            }
        }
    )

    critical_labels = [item["label"] for item in checklist["critical"]]
    recommended_labels = [item["label"] for item in checklist["recommended"]]

    assert "Partida de nacimiento." in critical_labels
    assert "Comprobantes de gastos del hijo." in critical_labels
    assert "Recibos de sueldo o indicios de ingresos." in recommended_labels
    assert checklist["critical"][0]["priority_rank"] <= checklist["critical"][-1]["priority_rank"]
    assert checklist["critical"][0]["why_it_matters"]


def test_build_case_evidence_checklist_uses_execution_documents_and_conflict_signals():
    checklist = build_case_evidence_checklist(
        api_payload={
            "execution_output": {
                "execution_output": {
                    "documents_needed": ["DNI.", "Constancia de domicilio."],
                }
            },
            "conflict_evidence": {
                "key_evidence_missing": ["Capturas de mensajes."],
            },
            "case_progress": {
                "critical_gaps": [{"key": "domicilio_relevante"}],
            },
        }
    )

    critical_labels = [item["label"] for item in checklist["critical"]]
    recommended_labels = [item["label"] for item in checklist["recommended"]]

    assert "DNI." in critical_labels
    assert "Constancia de domicilio." in critical_labels
    assert "Capturas de mensajes." in recommended_labels
    assert checklist["critical"][0]["evidence_role"] in {"gap_unlock", "structural_document"}
    assert isinstance(checklist["critical"][0]["resolves"], list)


def test_build_case_evidence_checklist_prioritizes_gap_unlock_over_structural_documents():
    checklist = build_case_evidence_checklist(
        api_payload={
            "evidence_reasoning_links": {
                "critical_evidentiary_gaps": ["Comprobantes de gastos del hijo."],
            },
            "execution_output": {
                "execution_output": {
                    "documents_needed": ["DNI.", "Partida de nacimiento."],
                }
            },
            "case_progress": {
                "critical_gaps": [{"key": "monto"}],
            },
        }
    )

    assert checklist["critical"][0]["label"] == "Comprobantes de gastos del hijo."
    assert checklist["critical"][0]["priority_rank"] == 1
    assert checklist["critical"][0]["why_it_matters"]


def test_build_case_evidence_checklist_uses_missing_fact_proof_signals():
    checklist = build_case_evidence_checklist(
        api_payload={
            "case_memory": {
                "missing": {
                    "critical": [
                        {
                            "key": "comprobantes_de_pago",
                            "label": "Comprobantes de pago",
                            "purpose": "prove",
                        }
                    ],
                    "important": [],
                    "optional": [],
                }
            }
        }
    )

    assert checklist["critical"][0]["label"] == "Comprobantes de pago"
    assert checklist["critical"][0]["evidence_role"] in {"gap_unlock", "corroboration"}
    assert checklist["critical"][0]["resolves"] == ["comprobantes_de_pago"]


def test_build_case_evidence_checklist_returns_empty_groups_without_basis():
    checklist = build_case_evidence_checklist(api_payload={})

    assert checklist == {
        "critical": [],
        "recommended": [],
        "optional": [],
    }


def test_build_case_evidence_checklist_links_relevant_items_to_action_plan():
    checklist = build_case_evidence_checklist(
        api_payload={
            "case_progress": {
                "critical_gaps": [{"key": "jurisdiccion"}],
            },
            "execution_output": {
                "execution_output": {
                    "documents_needed": ["Constancia de domicilio."],
                }
            },
        },
        action_plan=[
            {
                "id": "clarify_jurisdiccion",
                "step_id": "clarify_jurisdiccion",
                "title": "Definir la jurisdiccion relevante",
                "phase": "clarify",
                "is_primary": True,
            }
        ],
    )

    assert checklist["critical"][0]["supports_step"] == "clarify_jurisdiccion"


def test_build_case_evidence_checklist_filtra_requisitos_academicos_en_bebe():
    checklist = build_case_evidence_checklist(
        api_payload={
            "query": "Quiero reclamar alimentos para mi hija de 3 meses",
            "case_memory": {
                "facts": {
                    "hay_hijos": {"value": True, "source": "confirmed", "confidence": 1.0},
                }
            },
            "case_theory": {
                "evidentiary_needs": [
                    "Acompanhar regularidad academica, plan de estudios y continuidad de asistencia.",
                    "Partida de nacimiento del hijo.",
                ]
            },
        }
    )

    all_labels = [item["label"] for bucket in checklist.values() for item in bucket]
    assert "Partida de nacimiento del hijo." in all_labels
    assert not any("regularidad academica" in label.casefold() for label in all_labels)


def test_build_case_evidence_checklist_deduplica_vinculo_filial_y_partida():
    checklist = build_case_evidence_checklist(
        api_payload={
            "evidence_reasoning_links": {
                "critical_evidentiary_gaps": [
                    "Partida de nacimiento del hijo.",
                    "Partida de nacimiento u otra acreditacion del vinculo filial.",
                ],
            },
            "conflict_evidence": {
                "key_evidence_missing": [
                    "Partidas de nacimiento y documentacion del grupo familiar.",
                ],
            },
        }
    )

    all_labels = [item["label"] for bucket in checklist.values() for item in bucket]
    family_link_items = [
        label for label in all_labels
        if "partida de nacimiento" in label.casefold() or "vinculo filial" in label.casefold()
    ]
    assert len(family_link_items) == 1
