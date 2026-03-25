from __future__ import annotations

import pytest

from tests.fixtures.legal_benchmark_cases import LEGAL_BENCHMARK_CASES, benchmark_case_by_id
from tests.legal_benchmark_support import (
    evaluate_benchmark_case,
    has_cautious_exception,
    run_benchmark_case,
    strategy_alignment_ok,
    strategy_support_text,
    summarize_benchmark_case,
)


@pytest.mark.parametrize("case", LEGAL_BENCHMARK_CASES, ids=[item["id"] for item in LEGAL_BENCHMARK_CASES])
def test_legal_benchmark_cases(case):
    evaluation = evaluate_benchmark_case(case)
    assert evaluation["passed"], "; ".join(evaluation["failures"]) or evaluation["summary"]


def test_high_risk_and_weak_evidence_never_becomes_aggressive():
    case = benchmark_case_by_id("alimentos_prueba_debil")
    payload = run_benchmark_case(case)
    assert payload["legal_decision"]["strategic_posture"] != "agresiva"


def test_favorable_precedent_impacts_materially():
    favorable = run_benchmark_case(benchmark_case_by_id("precedente_favorable_vs_adverso_base"))
    adverse = run_benchmark_case(benchmark_case_by_id("precedente_adverso_norma_favorable"))
    assert favorable["legal_decision"]["confidence_score"] > adverse["legal_decision"]["confidence_score"]
    assert favorable["legal_decision"]["strategic_posture"] == "agresiva"


def test_adverse_precedent_introduces_real_caution():
    adverse = run_benchmark_case(benchmark_case_by_id("precedente_adverso_norma_favorable"))
    notes = " ".join(adverse["legal_decision"].get("decision_notes", [])).lower()
    assert adverse["legal_decision"]["strategic_posture"] in {"conservadora", "cautelosa"}
    assert "jurisprudencia adversa" in notes or "cautela" in notes


def test_critical_gaps_reduce_strength():
    weak = run_benchmark_case(benchmark_case_by_id("falta_critica_estructural"))
    strong = run_benchmark_case(benchmark_case_by_id("alimentos_urgente_fuerte"))
    assert weak["legal_decision"]["case_strength_label"] == "bajo"
    assert weak["legal_decision"]["confidence_score"] < strong["legal_decision"]["confidence_score"]


def test_strategy_is_aligned_with_legal_decision():
    payload = run_benchmark_case(benchmark_case_by_id("norma_fuerte_evidencia_debil"))
    assert payload["case_strategy"]["strategy_mode"] == payload["legal_decision"]["strategic_posture"]
    assert payload["legal_decision"]["strategic_posture"] == "cautelosa"
    assert strategy_alignment_ok(payload)


def test_high_confidence_does_not_become_cautious_without_clear_support():
    for case in LEGAL_BENCHMARK_CASES:
        payload = run_benchmark_case(case)
        decision = payload["legal_decision"]
        if decision["confidence_score"] > 0.75 and decision["strategic_posture"] == "cautelosa":
            assert has_cautious_exception(payload), summarize_benchmark_case(case, payload)


def test_high_strength_cases_do_not_default_to_saneamiento_without_adverse_factor():
    for case in LEGAL_BENCHMARK_CASES:
        payload = run_benchmark_case(case)
        decision = payload["legal_decision"]
        if decision["case_strength_label"] != "alto":
            continue
        if payload["case_strategy"]["strategy_mode"] != "cautelosa":
            continue
        assert has_cautious_exception(payload), summarize_benchmark_case(case, payload)


def test_risk_dominant_cases_reflect_risk_structurally():
    for case in LEGAL_BENCHMARK_CASES:
        payload = run_benchmark_case(case)
        if payload["legal_decision"]["dominant_factor"] != "riesgo":
            continue
        support_text = strategy_support_text(payload)
        assert any(term in support_text for term in ("riesgo", "contencion", "prevenir rechazo")), summarize_benchmark_case(case, payload)


def test_evidence_dominant_cases_do_not_sound_expansive_without_saneamiento():
    for case in LEGAL_BENCHMARK_CASES:
        payload = run_benchmark_case(case)
        if payload["legal_decision"]["dominant_factor"] != "prueba":
            continue
        assert payload["case_strategy"]["strategy_mode"] != "agresiva", summarize_benchmark_case(case, payload)
        support_text = strategy_support_text(payload)
        assert any(term in support_text for term in ("prueba", "saneamiento", "soporte", "cobertura")), summarize_benchmark_case(case, payload)


def test_high_risk_weak_evidence_and_strong_norms_never_end_aggressive():
    payload = run_benchmark_case(benchmark_case_by_id("norma_fuerte_evidencia_debil"))
    assert payload["case_strategy"]["strategy_mode"] != "agresiva"
    assert payload["legal_decision"]["strategic_posture"] != "agresiva"
