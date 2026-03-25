"""
AILEX -- loader and validator for structured jurisprudence corpora.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from legal_engine.jurisprudence_schema import (
    ALLOWED_MODES,
    LEGACY_MODE,
    STRICT_MODE,
    JurisprudencePrecedent,
    clean_text,
    normalize_text,
    validate_precedent,
)


DEFAULT_JURISPRUDENCE_CORPUS_ROOT = Path(__file__).resolve().parent.parent / "data" / "jurisprudence"
DEFAULT_ALLOWED_DATASET_KINDS = frozenset({"real", "fixture"})
SKIPPED_DIR_NAMES = frozenset({"templates", "schema", "__pycache__"})
SKIPPED_FILE_SUFFIXES = (".template.json", ".schema.json")


@dataclass(slots=True)
class RejectedPrecedentRecord:
    record_id: str
    mode: str
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LoadedJurisprudenceFile:
    path: str
    mode: str
    precedents: list[JurisprudencePrecedent] = field(default_factory=list)
    rejected_records: list[RejectedPrecedentRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return len(self.precedents)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_records)

    @property
    def integrity_ratio(self) -> float:
        total = self.accepted_count + self.rejected_count
        if total == 0:
            return 0.0
        return self.accepted_count / total


class JurisprudenceLoader:
    def __init__(
        self,
        corpus_root: Path | None = None,
        *,
        allowed_dataset_kinds: Iterable[str] | None = None,
        default_mode: str = "auto",
    ) -> None:
        self._corpus_root = Path(corpus_root) if corpus_root is not None else DEFAULT_JURISPRUDENCE_CORPUS_ROOT
        self._allowed_dataset_kinds = {
            normalize_text(kind)
            for kind in (allowed_dataset_kinds or DEFAULT_ALLOWED_DATASET_KINDS)
            if clean_text(kind)
        }
        self._default_mode = default_mode if default_mode in {"auto", *ALLOWED_MODES} else "auto"

    @property
    def corpus_root(self) -> Path:
        return self._corpus_root

    def iter_dataset_files(self) -> list[Path]:
        dataset_files: list[Path] = []
        for path in self._corpus_root.rglob("*.json"):
            if any(part in SKIPPED_DIR_NAMES for part in path.parts):
                continue
            if any(path.name.endswith(suffix) for suffix in SKIPPED_FILE_SUFFIXES):
                continue
            dataset_files.append(path)
        return sorted(dataset_files)

    def load_file(self, path: Path, *, mode: str | None = None) -> LoadedJurisprudenceFile:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return LoadedJurisprudenceFile(
                path=str(path),
                mode=mode or self._default_mode,
                warnings=[f"No se pudo cargar el archivo jurisprudencial '{path.name}': {exc}"],
            )

        dataset_meta = payload.get("_meta") if isinstance(payload, dict) and isinstance(payload.get("_meta"), dict) else {}
        records = self.extract_records(payload)
        dataset_kind = normalize_text(dataset_meta.get("dataset_kind") or "real") or "real"
        resolved_mode = self._resolve_mode(mode=mode, dataset_kind=dataset_kind)

        precedents: list[JurisprudencePrecedent] = []
        rejected_records: list[RejectedPrecedentRecord] = []
        warnings: list[str] = []

        for raw_record in records:
            merged = self._merge_metadata(raw_record, dataset_meta)
            record_kind = normalize_text(merged.get("dataset_kind") or dataset_kind) or dataset_kind
            if record_kind not in self._allowed_dataset_kinds:
                continue

            record_mode = self._resolve_mode(mode=mode, dataset_kind=record_kind)
            precedent = JurisprudencePrecedent.from_record(merged, mode=record_mode)
            errors = validate_precedent(precedent, mode=record_mode)
            if errors:
                rejected_records.append(
                    RejectedPrecedentRecord(
                        record_id=precedent.id or "<missing>",
                        mode=record_mode,
                        reasons=[f"{item.field_name}: {item.message}" for item in errors],
                    )
                )
                continue
            precedents.append(precedent)

        if rejected_records:
            warnings.append(
                f"Se rechazaron {len(rejected_records)} registros en '{path.name}' por falta de integridad o calidad juridica."
            )
        if resolved_mode == STRICT_MODE and precedents and len(precedents) < 2:
            warnings.append(
                f"El archivo '{path.name}' aporto pocos precedentes strict aceptados; la base puede ser insuficiente para una orientacion estable."
            )

        return LoadedJurisprudenceFile(
            path=str(path),
            mode=resolved_mode,
            precedents=precedents,
            rejected_records=rejected_records,
            warnings=warnings,
        )

    @staticmethod
    def extract_records(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            for key in ("precedents", "cases"):
                items = payload.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
            if all(isinstance(value, dict) for value in payload.values()):
                return [value for value in payload.values() if isinstance(value, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def _resolve_mode(self, *, mode: str | None, dataset_kind: str) -> str:
        if mode in ALLOWED_MODES:
            return mode
        if self._default_mode in ALLOWED_MODES:
            return self._default_mode
        return STRICT_MODE if dataset_kind == "real" else LEGACY_MODE

    @staticmethod
    def _merge_metadata(raw_record: dict[str, Any], dataset_meta: dict[str, Any]) -> dict[str, Any]:
        merged = dict(raw_record)
        metadata = dict(dataset_meta or {})
        metadata.update(raw_record.get("metadata") or {})
        merged["metadata"] = metadata

        for field_name in (
            "territorial_priority",
            "local_practice_value",
            "court_level",
            "redundancy_group",
            "practical_frequency",
            "local_topic_cluster",
        ):
            if clean_text(merged.get(field_name)):
                continue
            if clean_text(metadata.get(field_name)):
                merged[field_name] = metadata.get(field_name)

        if not clean_text(merged.get("dataset_kind")) and clean_text(dataset_meta.get("dataset_kind")):
            merged["dataset_kind"] = dataset_meta.get("dataset_kind")
        if not clean_text(merged.get("source_name")) and clean_text(dataset_meta.get("source_name")):
            merged["source_name"] = dataset_meta.get("source_name")
        return merged
