from pathlib import Path

from legal_engine.jurisprudence_corpus import JurisprudenceCorpus
from legal_engine.jurisprudence_index import JurisprudenceIndex
from legal_engine.jurisprudence_retriever import JurisprudenceRetriever


REAL_ROOT = Path(__file__).resolve().parents[1] / "data" / "jurisprudence"
LEGACY_ROOT = Path(__file__).resolve().parent / "fixtures" / "jurisprudence"


def test_corpus_separates_core_and_editorial_text():
    snapshot = JurisprudenceCorpus(corpus_root=REAL_ROOT).load()

    assert snapshot.available
    assert snapshot.loaded
    assert snapshot.strict_cases >= 1
    first = snapshot.documents[0]
    assert first.core_search_text
    assert first.ranking_metadata_text
    assert isinstance(first.editorial_metadata_text, str)
    assert "redundancy_group" not in first.core_search_text


def test_retriever_prefers_real_strict_precedents_over_legacy():
    retriever = JurisprudenceRetriever(corpus_root=REAL_ROOT)

    result = retriever.search(
        query="Divorcio unilateral sin acuerdo sobre convenio regulador en Jujuy",
        classification={"action_slug": "divorcio_unilateral", "jurisdiction": "jujuy", "forum": "familia"},
    )

    assert result.matches
    assert result.accepted_real_cases >= 1
    assert result.accepted_legacy_cases == 0
    assert all(match.case.ingest_mode == "strict" for match in result.matches)


def test_retriever_can_still_use_legacy_when_real_corpus_is_absent():
    retriever = JurisprudenceRetriever(corpus_root=LEGACY_ROOT)

    result = retriever.search(
        query="Cuota alimentaria provisoria para hijo menor en Jujuy",
        classification={"action_slug": "alimentos_hijos", "jurisdiction": "jujuy", "forum": "familia"},
    )

    assert result.matches
    assert result.accepted_real_cases == 0
    assert result.accepted_legacy_cases >= 1
    assert any("legacy" in item.lower() for item in result.warnings)


def test_index_scoring_relies_on_core_legal_fields():
    snapshot = JurisprudenceCorpus(corpus_root=REAL_ROOT).load()
    index = JurisprudenceIndex(snapshot.documents)
    context = index.build_query_context(
        query="cuidado personal con centro de vida y coparentalidad en Jujuy",
        classification={"action_slug": "cuidado_personal", "jurisdiction": "jujuy", "forum": "familia"},
    )

    results = index.search(context, top_k=3)

    assert results
    assert results[0].document.case.topic == "cuidado_personal"
    assert any(
        "topic" in reason.lower() or "criterion" in reason.lower() or "subtopic" in reason.lower()
        for reason in results[0].reasons
    )
