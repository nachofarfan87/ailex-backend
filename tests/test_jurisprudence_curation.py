from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from legal_engine.jurisprudence_curation import (
    build_curated_case_template,
    validate_curated_case,
    validate_curated_dataset_file,
)


def _valid_real_case() -> dict:
    payload = build_curated_case_template()
    payload.update(
        {
            "case_id": "jujuy-familia-2024-0001",
            "court": "Camara de Apelaciones de Familia de Jujuy",
            "jurisdiction": "jujuy",
            "forum": "familia",
            "year": 2024,
            "case_name": "A. B. c/ C. D. s/ alimentos",
            "source": "boletin_judicial_curado",
            "source_url": "https://example.org/fallo-verificable",
            "legal_issue": "Determinacion de cuota alimentaria provisoria con base en gastos acreditados y capacidad economica discutida.",
            "facts_summary": "La progenitora conviviente promovio alimentos para su hijo menor y acompaño comprobantes de salud y escolaridad frente a incumplimientos persistentes.",
            "decision_summary": "El tribunal admitio una cuota provisoria y ordeno continuar la produccion de prueba para precisar la capacidad economica del alimentante.",
            "key_reasoning": "La tutela urgente resulta procedente cuando los gastos esenciales del hijo aparecen acreditados y la asistencia previa fue insuficiente.",
            "holding": "La existencia de necesidades actuales del hijo y la verosimilitud del deber alimentario justifican una cuota provisoria aun sin prueba patrimonial completa.",
            "outcome": "Se fija cuota provisoria y se abre etapa probatoria complementaria.",
            "topics": ["alimentos", "hijo menor", "cuota provisoria"],
            "keywords": ["alimentos", "cuota", "gastos del hijo"],
            "applied_articles": ["CCyC 658", "CCyC 659"],
            "procedural_stage": "apelacion",
            "document_type": "sentencia",
            "action_slug": "alimentos_hijos",
            "strategic_value": "Util para sostener pedidos urgentes de cuota provisoria cuando el actor ya puede probar gastos del hijo pero aun no tiene prueba patrimonial completa del demandado.",
            "territorial_priority": "alta",
            "local_practice_value": "alta",
            "court_level": "camara",
            "redundancy_group": "jujuy-alimentos-provisorios",
            "practical_frequency": "alta",
            "local_topic_cluster": "alimentos_jujuy",
            "metadata": {
                "verification_status": "verified",
                "curation_status": "approved",
                "verified_at": "2026-03-13",
                "verified_by": "equipo_ailex",
                "curated_by": "equipo_ailex",
                "source_reference": "Registro interno de verificacion 2026-03-13",
                "editorial_line": "jujuy_local",
                "ingested_at": "2026-03-13",
                "dataset_version": "v1",
            },
        }
    )
    return payload


def test_real_case_validation_accepts_verified_curated_record():
    result = validate_curated_case(_valid_real_case(), dataset_meta={"dataset_kind": "real"})

    assert result.is_valid
    assert not result.issues


def test_real_case_validation_rejects_missing_verification_metadata():
    case = _valid_real_case()
    case["metadata"].pop("verified_by")
    case["metadata"]["verification_status"] = "pending"

    result = validate_curated_case(case, dataset_meta={"dataset_kind": "real"})

    assert not result.is_valid
    assert any(issue.code == "missing_real_metadata" for issue in result.issues)
    assert any(issue.code == "invalid_verification_status" for issue in result.issues)


def test_real_case_validation_rejects_placeholder_or_weak_content():
    case = _valid_real_case()
    case["holding"] = "Ejemplo"
    case["strategic_value"] = "Completar"

    result = validate_curated_case(case, dataset_meta={"dataset_kind": "real"})

    assert not result.is_valid
    assert any(issue.code in {"text_too_short", "placeholder_content"} for issue in result.issues)


def test_dataset_validator_reports_invalid_real_case(tmp_path: Path):
    dataset = {
        "_meta": {"dataset_kind": "real"},
        "cases": [
            _valid_real_case(),
            {
                "case_id": "bad-real-1",
                "court": "Tribunal de ejemplo",
                "jurisdiction": "jujuy",
                "forum": "familia",
                "year": 2025,
                "case_name": "No usar",
                "source": "desconocido",
                "source_url": "fixture://bad-real-1",
                "legal_issue": "Campo de ejemplo",
                "facts_summary": "Campo de ejemplo",
                "decision_summary": "Campo de ejemplo",
                "key_reasoning": "Campo de ejemplo",
                "holding": "Campo de ejemplo",
                "outcome": "Campo de ejemplo",
                "topics": ["divorcio"],
                "keywords": ["ejemplo"],
                "applied_articles": ["CCyC 437"],
                "procedural_stage": "apelacion",
                "document_type": "sentencia",
                "action_slug": "divorcio",
                "strategic_value": "Campo de ejemplo",
                "dataset_kind": "real",
                "metadata": {
                    "verification_status": "verified",
                    "curation_status": "approved",
                    "verified_at": "2026-03-13",
                    "verified_by": "equipo_ailex",
                    "curated_by": "equipo_ailex",
                    "source_reference": "interna",
                },
            },
        ],
    }
    path = tmp_path / "real_cases.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    report = validate_curated_dataset_file(path)

    assert not report.is_valid
    assert report.total_cases == 2
    assert report.invalid_cases == 1


def test_validation_script_returns_non_zero_on_invalid_dataset(tmp_path: Path):
    dataset_root = tmp_path / "jurisprudence"
    dataset_root.mkdir()
    path = dataset_root / "real_cases.json"
    path.write_text(json.dumps({"_meta": {"dataset_kind": "real"}, "cases": [{"case_id": "x"}]}), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/validate_jurisprudence_corpus.py", str(dataset_root)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "missing_required_field" in completed.stdout


def test_jujuy_editorial_case_requires_local_metadata():
    case = _valid_real_case()
    case["jurisdiction"] = "jujuy"
    case["metadata"]["editorial_line"] = "jujuy_local"
    for field_name in (
        "territorial_priority",
        "local_practice_value",
        "court_level",
        "redundancy_group",
        "practical_frequency",
        "local_topic_cluster",
    ):
        case[field_name] = ""

    result = validate_curated_case(case, dataset_meta={"dataset_kind": "real", "editorial_line": "jujuy_local"})

    assert not result.is_valid
    assert any(issue.code == "missing_jujuy_local_field" for issue in result.issues)
