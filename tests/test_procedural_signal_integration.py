from __future__ import annotations

from copy import deepcopy

from tests.fixtures.legal_benchmark_cases import benchmark_case_by_id
from tests.legal_benchmark_support import evaluate_benchmark_case, run_benchmark_case


def test_timeline_case_state_and_decision_align_on_competence_case():
    payload = run_benchmark_case(benchmark_case_by_id("alimentos_provisoria_incompetencia_posterior"))

    timeline_labels = [event["label"] for event in payload["procedural_timeline"]["ordered_events"]]
    case_state = payload["procedural_case_state"]
    decision = payload["legal_decision"]

    assert "competence_issue" in timeline_labels
    assert case_state["blocking_factor"] == "competence"
    assert decision["signal_summary"]["blocking_factor"] == "competence"
    assert decision["dominant_factor"] == "procesal"
    assert decision["strategic_posture"] == "conservadora"


def test_default_improves_litigation_signal_without_erasing_operational_block():
    case = benchmark_case_by_id("aumento_cuota_rebeldia_demora_operativa")
    payload_with_default = run_benchmark_case(case)

    case_without_default = deepcopy(case)
    case_without_default["procedural_events"] = [
        item
        for item in case_without_default["procedural_events"]
        if "decaimiento" not in str(item.get("title") or "").lower()
    ]
    payload_without_default = run_benchmark_case(case_without_default)

    assert payload_with_default["procedural_case_state"]["defense_status"] == "defaulted"
    assert payload_with_default["procedural_case_state"]["blocking_factor"] == "administrative_delay"
    assert payload_with_default["legal_decision"]["confidence_score"] > payload_without_default["legal_decision"]["confidence_score"]
    assert any("rebeldia" in note.lower() or "decaimiento" in note.lower() for note in payload_with_default["legal_decision"]["decision_notes"])


def test_operational_block_changes_strategy_without_destroying_material_strength():
    payload = run_benchmark_case(benchmark_case_by_id("aumento_cuota_rebeldia_demora_operativa"))

    focus = " ".join(payload["case_strategy"]["procedural_focus"]).lower()
    actions = " ".join(payload["case_strategy"]["recommended_actions"]).lower()

    assert payload["legal_decision"]["case_strength_label"] == "alto"
    assert payload["legal_decision"]["strategic_posture"] == "conservadora"
    assert payload["procedural_case_state"]["blocking_factor"] == "administrative_delay"
    assert "destrabar" in focus or "operativas" in focus
    assert "pase a resolver" in actions or "destrabar" in actions


def test_competence_issue_impacts_procedural_risk_without_destroying_material_case():
    payload = run_benchmark_case(benchmark_case_by_id("alimentos_provisoria_incompetencia_posterior"))

    assert payload["legal_decision"]["case_strength_label"] == "alto"
    assert payload["procedural_case_state"]["procedural_status"] == "blocked_by_competence"
    assert payload["legal_decision"]["signal_summary"]["blocking_factor"] == "competence"
    assert payload["legal_decision"]["confidence_score"] >= 0.64
    assert any("competencia" in note.lower() for note in payload["legal_decision"]["decision_notes"])


def test_real_procedural_benchmark_cases_pass_structural_evaluation():
    real_case_ids = [
        "divorcio_convenio_parcial_conflictos_derivados",
        "alimentos_provisoria_incompetencia_posterior",
        "alimentos_audiencia_fallida_defensa_friccion",
        "aumento_cuota_rebeldia_demora_operativa",
    ]

    for case_id in real_case_ids:
        evaluation = evaluate_benchmark_case(benchmark_case_by_id(case_id))
        assert evaluation["passed"], "; ".join(evaluation["failures"]) or evaluation["summary"]
