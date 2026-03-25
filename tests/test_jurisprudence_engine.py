from pathlib import Path

from legal_engine.jurisprudence_engine import (
    SOURCE_MODE_INTERNAL,
    SOURCE_MODE_LEGACY,
    SOURCE_MODE_RETRIEVED,
    JurisprudenceEngine,
)
from legal_engine.jurisprudence_retriever import JurisprudenceRetriever


REAL_ROOT = Path(__file__).resolve().parents[1] / "data" / "jurisprudence"
LEGACY_ROOT = Path(__file__).resolve().parent / "fixtures" / "jurisprudence"


def test_engine_prioritizes_retrieved_real_precedents():
    engine = JurisprudenceEngine(
        jurisprudence_retriever=JurisprudenceRetriever(corpus_root=REAL_ROOT)
    )

    result = engine.analyze(
        query="Necesito impulsar divorcio unilateral aunque no haya acuerdo total sobre el convenio regulador",
        classification={"action_slug": "divorcio_unilateral", "jurisdiction": "jujuy", "forum": "familia"},
        normative_reasoning={"requirements": ["Presentar propuesta reguladora."]},
    )

    assert result.relevant_cases
    assert all(item.source_mode == SOURCE_MODE_RETRIEVED for item in result.relevant_cases)
    assert result.confidence_score >= 0.55
    assert "precedentes reales" in result.source_mode_summary.lower()


def test_engine_uses_legacy_imported_precedents_when_no_real_exist():
    engine = JurisprudenceEngine(
        jurisprudence_retriever=JurisprudenceRetriever(corpus_root=LEGACY_ROOT)
    )

    result = engine.analyze(
        query="El padre no paga alimentos del hijo menor",
        classification={"action_slug": "alimentos_hijos", "jurisdiction": "jujuy", "forum": "familia"},
        case_structure={"facts": ["Hay gastos de salud y escolaridad."]},
    )

    assert result.relevant_cases
    assert all(item.source_mode == SOURCE_MODE_LEGACY for item in result.relevant_cases)
    assert any("legacy" in item.lower() for item in result.warnings)
    assert result.confidence_score < 0.6


def test_engine_falls_back_to_internal_only_when_corpus_is_missing(tmp_path):
    engine = JurisprudenceEngine(
        jurisprudence_retriever=JurisprudenceRetriever(corpus_root=tmp_path / "missing")
    )

    result = engine.analyze(
        query="Quiero cuidado personal para mi hijo",
        classification={"action_slug": "cuidado_personal", "jurisdiction": "jujuy", "forum": "familia"},
    )

    assert result.relevant_cases
    assert all(item.source_mode == SOURCE_MODE_INTERNAL for item in result.relevant_cases)
    assert any("fallback interno" in item.lower() or "fallback" in item.lower() for item in result.warnings)
    assert result.confidence_score <= 0.24
