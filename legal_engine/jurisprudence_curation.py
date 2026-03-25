"""
AILEX -- curated jurisprudence validation and ingestion support.

This module defines the operational standard for admitting `dataset_kind=real`
records into the local corpus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from legal_engine.jurisprudence_corpus import (
    DEFAULT_JURISPRUDENCE_CORPUS_ROOT,
    JurisprudenceCorpus,
)


REAL_REQUIRED_METADATA_FIELDS = (
    "verification_status",
    "curation_status",
    "verified_at",
    "verified_by",
    "curated_by",
    "source_reference",
)
REAL_ALLOWED_VERIFICATION_STATUS = {"verified"}
REAL_ALLOWED_CURATION_STATUS = {"approved"}
MIN_SUBSTANTIVE_TEXT_LENGTH = 40
JUJUY_LOCAL_REQUIRED_FIELDS = (
    "territorial_priority",
    "local_practice_value",
    "court_level",
    "redundancy_group",
    "practical_frequency",
    "local_topic_cluster",
)


@dataclass
class CuratedCaseValidationIssue:
    code: str
    message: str
    severity: str = "error"
    field_name: str = ""


@dataclass
class CuratedCaseValidationResult:
    case_id: str
    dataset_kind: str
    is_valid: bool
    issues: list[CuratedCaseValidationIssue] = field(default_factory=list)

    def error_messages(self) -> list[str]:
        return [issue.message for issue in self.issues if issue.severity == "error"]


@dataclass
class CuratedDatasetValidationReport:
    file_path: str
    is_valid: bool
    total_cases: int
    valid_cases: int
    invalid_cases: int
    results: list[CuratedCaseValidationResult] = field(default_factory=list)
    global_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "is_valid": self.is_valid,
            "total_cases": self.total_cases,
            "valid_cases": self.valid_cases,
            "invalid_cases": self.invalid_cases,
            "global_issues": list(self.global_issues),
            "results": [
                {
                    "case_id": result.case_id,
                    "dataset_kind": result.dataset_kind,
                    "is_valid": result.is_valid,
                    "issues": [
                        {
                            "code": issue.code,
                            "message": issue.message,
                            "severity": issue.severity,
                            "field_name": issue.field_name,
                        }
                        for issue in result.issues
                    ],
                }
                for result in self.results
            ],
        }


def validate_curated_case(raw_case: dict[str, Any], dataset_meta: dict[str, Any] | None = None) -> CuratedCaseValidationResult:
    dataset_meta = dataset_meta or {}
    dataset_kind = JurisprudenceCorpus._as_dataset_kind(raw_case.get("dataset_kind") or dataset_meta.get("dataset_kind") or "real")
    case_id = JurisprudenceCorpus._as_text(raw_case.get("case_id") or raw_case.get("id") or raw_case.get("source_id")) or "<missing>"
    issues: list[CuratedCaseValidationIssue] = []

    required_fields = (
        "case_id",
        "court",
        "jurisdiction",
        "forum",
        "year",
        "case_name",
        "source",
        "source_url",
        "legal_issue",
        "facts_summary",
        "decision_summary",
        "key_reasoning",
        "holding",
        "outcome",
        "topics",
        "keywords",
        "applied_articles",
        "procedural_stage",
        "document_type",
        "action_slug",
        "strategic_value",
    )
    for field_name in required_fields:
        if not _field_present(raw_case, field_name):
            issues.append(
                CuratedCaseValidationIssue(
                    code="missing_required_field",
                    message=f"Falta el campo obligatorio '{field_name}' para curacion real.",
                    field_name=field_name,
                )
            )

    for field_name in ("legal_issue", "facts_summary", "decision_summary", "key_reasoning", "holding", "outcome", "strategic_value"):
        value = JurisprudenceCorpus._as_text(raw_case.get(field_name))
        if value and len(value) < MIN_SUBSTANTIVE_TEXT_LENGTH:
            issues.append(
                CuratedCaseValidationIssue(
                    code="text_too_short",
                    message=f"El campo '{field_name}' es demasiado breve para un caso real curado.",
                    field_name=field_name,
                )
            )

    metadata = raw_case.get("metadata") if isinstance(raw_case.get("metadata"), dict) else {}
    merged_metadata = dict(dataset_meta) if isinstance(dataset_meta, dict) else {}
    merged_metadata.update(metadata)

    if dataset_kind == "real":
        for field_name in REAL_REQUIRED_METADATA_FIELDS:
            value = merged_metadata.get(field_name)
            if not JurisprudenceCorpus._as_text(value):
                issues.append(
                    CuratedCaseValidationIssue(
                        code="missing_real_metadata",
                        message=f"Falta metadata obligatoria '{field_name}' para dataset real.",
                        field_name=field_name,
                    )
                )

        verification_status = JurisprudenceCorpus.normalize_text(merged_metadata.get("verification_status") or "")
        if verification_status and verification_status not in REAL_ALLOWED_VERIFICATION_STATUS:
            issues.append(
                CuratedCaseValidationIssue(
                    code="invalid_verification_status",
                    message="verification_status debe ser 'verified' para dataset real.",
                    field_name="metadata.verification_status",
                )
            )

        curation_status = JurisprudenceCorpus.normalize_text(merged_metadata.get("curation_status") or "")
        if curation_status and curation_status not in REAL_ALLOWED_CURATION_STATUS:
            issues.append(
                CuratedCaseValidationIssue(
                    code="invalid_curation_status",
                    message="curation_status debe ser 'approved' para dataset real.",
                    field_name="metadata.curation_status",
                )
            )

    if _is_jujuy_editorial_case(raw_case, dataset_meta):
        for field_name in JUJUY_LOCAL_REQUIRED_FIELDS:
            if not _field_present(raw_case, field_name):
                issues.append(
                    CuratedCaseValidationIssue(
                        code="missing_jujuy_local_field",
                        message=f"Falta el campo local obligatorio '{field_name}' para la linea editorial Jujuy.",
                        field_name=field_name,
                    )
                )

    if _looks_placeholder(raw_case):
        issues.append(
            CuratedCaseValidationIssue(
                code="placeholder_content",
                message="El registro contiene texto de plantilla o placeholder y no puede entrar como real.",
            )
        )

    if dataset_kind == "real" and not _source_url_looks_verifiable(JurisprudenceCorpus._as_text(raw_case.get("source_url"))):
        issues.append(
            CuratedCaseValidationIssue(
                code="non_verifiable_source_url",
                message="El dataset real requiere source_url verificable (http(s) o referencia documental estable).",
                field_name="source_url",
            )
        )

    is_valid = not any(issue.severity == "error" for issue in issues)
    return CuratedCaseValidationResult(
        case_id=case_id,
        dataset_kind=dataset_kind,
        is_valid=is_valid,
        issues=issues,
    )


def validate_curated_dataset_file(path: Path) -> CuratedDatasetValidationReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return CuratedDatasetValidationReport(
            file_path=str(path),
            is_valid=False,
            total_cases=0,
            valid_cases=0,
            invalid_cases=0,
            global_issues=[f"No se pudo leer el archivo: {exc}"],
        )

    dataset_meta = payload.get("_meta") if isinstance(payload, dict) else {}
    raw_cases = JurisprudenceCorpus._extract_case_dicts(payload)
    results = [validate_curated_case(case, dataset_meta=dataset_meta) for case in raw_cases]
    valid_cases = sum(1 for result in results if result.is_valid)
    invalid_cases = len(results) - valid_cases
    return CuratedDatasetValidationReport(
        file_path=str(path),
        is_valid=(invalid_cases == 0),
        total_cases=len(results),
        valid_cases=valid_cases,
        invalid_cases=invalid_cases,
        results=results,
    )


def validate_curated_corpus_root(root: Path | None = None) -> list[CuratedDatasetValidationReport]:
    corpus_root = Path(root) if root is not None else DEFAULT_JURISPRUDENCE_CORPUS_ROOT
    corpus = JurisprudenceCorpus(corpus_root=corpus_root, allowed_dataset_kinds={"real", "seed", "fixture"})
    reports: list[CuratedDatasetValidationReport] = []
    for path in sorted(corpus._iter_dataset_files()):
        reports.append(validate_curated_dataset_file(path))
    return reports


def build_curated_case_template() -> dict[str, Any]:
    return {
        "case_id": "provincia-fuero-anio-identificador",
        "court": "",
        "jurisdiction": "",
        "forum": "",
        "year": 0,
        "case_name": "",
        "source": "",
        "source_url": "",
        "legal_issue": "",
        "facts_summary": "",
        "decision_summary": "",
        "key_reasoning": "",
        "holding": "",
        "outcome": "",
        "topics": [],
        "keywords": [],
        "applied_articles": [],
        "procedural_stage": "",
        "document_type": "",
        "action_slug": "",
        "strategic_value": "",
        "territorial_priority": "",
        "local_practice_value": "",
        "court_level": "",
        "redundancy_group": "",
        "practical_frequency": "",
        "local_topic_cluster": "",
        "chamber": "",
        "date": "",
        "parties": [],
        "full_text": "",
        "dataset_kind": "real",
        "metadata": {
            "verification_status": "verified",
            "curation_status": "approved",
            "verified_at": "YYYY-MM-DD",
            "verified_by": "",
            "curated_by": "",
            "source_reference": "",
            "ingested_at": "YYYY-MM-DD",
            "dataset_version": "v1",
            "redundancy_group": "",
            "notes": "",
        },
    }


def _field_present(raw_case: dict[str, Any], field_name: str) -> bool:
    value = raw_case.get(field_name)
    if field_name in {"topics", "keywords", "applied_articles"}:
        return isinstance(value, list) and any(JurisprudenceCorpus._as_text(item) for item in value)
    if field_name == "year":
        return JurisprudenceCorpus._coerce_year(value, raw_case.get("date")) is not None
    if not JurisprudenceCorpus._as_text(value):
        metadata = raw_case.get("metadata") if isinstance(raw_case.get("metadata"), dict) else {}
        if JurisprudenceCorpus._as_text(metadata.get(field_name)):
            return True
        local_meta = metadata.get("local") if isinstance(metadata.get("local"), dict) else {}
        if JurisprudenceCorpus._as_text(local_meta.get(field_name)):
            return True
    return bool(JurisprudenceCorpus._as_text(value))


def _looks_placeholder(raw_case: dict[str, Any]) -> bool:
    placeholder_markers = {
        "campo de ejemplo",
        "ejemplo",
        "placeholder",
        "completar",
        "pendiente",
        "no usar",
        "tribunal de ejemplo",
    }
    for value in raw_case.values():
        text = JurisprudenceCorpus.normalize_text(value) if isinstance(value, str) else ""
        if any(marker in text for marker in placeholder_markers):
            return True
    return False


def _source_url_looks_verifiable(value: str) -> bool:
    text = JurisprudenceCorpus._as_text(value)
    if not text:
        return False
    lowered = text.casefold()
    return lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("ref:")


def _is_jujuy_editorial_case(raw_case: dict[str, Any], dataset_meta: dict[str, Any] | None) -> bool:
    dataset_meta = dataset_meta or {}
    jurisdiction = JurisprudenceCorpus.normalize_text(raw_case.get("jurisdiction") or "")
    editorial_line = JurisprudenceCorpus.normalize_text(dataset_meta.get("editorial_line") or "")
    metadata = raw_case.get("metadata") if isinstance(raw_case.get("metadata"), dict) else {}
    metadata_editorial_line = JurisprudenceCorpus.normalize_text(metadata.get("editorial_line") or "")
    return jurisdiction == "jujuy" or editorial_line == "jujuy_local" or metadata_editorial_line == "jujuy_local"
