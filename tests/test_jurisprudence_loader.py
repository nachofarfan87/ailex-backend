import json

from legal_engine.jurisprudence_loader import JurisprudenceLoader
from legal_engine.jurisprudence_schema import LEGACY_MODE, STRICT_MODE


def test_loader_rejects_incomplete_strict_real_precedent(tmp_path):
    payload = {
        "_meta": {"dataset_kind": "real"},
        "precedents": [
            {
                "id": "real-bad-001",
                "topic": "divorcio",
                "subtopic": "divorcio_unilateral",
                "jurisdiction": "jujuy",
                "forum": "familia",
                "court": "Tribunal de Familia",
                "year": 2025,
                "case_name": "S. c/ M. s/ divorcio",
                "source_type": "sentencia_judicial",
                "full_text": "Texto insuficiente porque faltan legal_issue, criterion y strategic_use.",
                "applied_articles": ["CCyC 437"]
            }
        ]
    }
    path = tmp_path / "strict_bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = JurisprudenceLoader(corpus_root=tmp_path).load_file(path)

    assert result.mode == STRICT_MODE
    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert "legal_issue" in " ".join(result.rejected_records[0].reasons)


def test_loader_accepts_legacy_fixture_and_tracks_integrity(tmp_path):
    payload = {
        "_meta": {"dataset_kind": "fixture"},
        "cases": [
            {
                "case_id": "legacy-ok-001",
                "court": "Juzgado de Familia",
                "jurisdiction": "jujuy",
                "forum": "familia",
                "year": 2024,
                "case_name": "A. c/ B. s/ alimentos",
                "source": "fixture",
                "legal_issue": "Alimentos provisorios para hijo menor.",
                "holding": "La existencia de gastos regulares del hijo justifica una cuota provisoria aun con informacion economica incompleta.",
                "strategic_value": "Util para sostener pedidos urgentes de cuota provisoria cuando ya hay comprobantes de gastos.",
                "topics": ["alimentos", "cuota provisoria"],
                "applied_articles": ["CCyC 658"],
                "document_type": "sentencia",
                "facts_summary": "Hechos relevantes.",
                "decision_summary": "Decision relevante."
            }
        ]
    }
    path = tmp_path / "legacy_ok.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = JurisprudenceLoader(corpus_root=tmp_path).load_file(path)

    assert result.mode == LEGACY_MODE
    assert result.accepted_count == 1
    assert result.rejected_count == 0
    assert result.integrity_ratio == 1.0
    assert result.precedents[0].ingest_mode == LEGACY_MODE


def test_loader_reports_rejected_reasons_with_quality_detail(tmp_path):
    payload = {
        "_meta": {"dataset_kind": "real"},
        "precedents": [
            {
                "id": "real-bad-002",
                "topic": "alimentos",
                "subtopic": "cuota_provisoria",
                "jurisdiction": "jujuy",
                "forum": "familia",
                "court": "Juzgado de Familia",
                "year": 2024,
                "case_name": "A. c/ B. s/ alimentos",
                "source_type": "sentencia_judicial",
                "legal_issue": "Alimentos provisorios para hijo menor.",
                "criterion": "Resuelvo fijar cuota provisoria en expte 123.",
                "strategic_use": "Sirve genericamente.",
                "full_text": "Texto suficiente.",
                "applied_articles": ["CCyC 658"]
            }
        ]
    }
    path = tmp_path / "strict_rejected.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = JurisprudenceLoader(corpus_root=tmp_path).load_file(path)

    assert result.rejected_count == 1
    reasons = " ".join(result.rejected_records[0].reasons).lower()
    assert "criterion" in reasons
