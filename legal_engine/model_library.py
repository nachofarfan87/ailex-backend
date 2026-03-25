from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StyleProfile:
    tone: str = "balanced_prudent"
    structure: list[str] = field(default_factory=list)
    argument_density: str = "standard"
    facts_style: str = "concrete"
    petitum_style: str = "prudent"
    opening_line: str = ""
    analysis_directive: str = ""
    facts_directive: str = ""
    petitum_directive: str = ""
    section_cues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApplicabilityRules:
    jurisdiction: str = ""
    forum: str = ""
    action_slug: str = ""
    document_kind: str = ""
    tags: list[str] = field(default_factory=list)
    preferred_tags: list[str] = field(default_factory=list)
    excluded_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    name: str
    source_path: str = ""
    source_type: str = "pdf"
    priority: int = 0
    rating: int = 0
    applicability: ApplicabilityRules = field(default_factory=ApplicabilityRules)
    style_profile: StyleProfile = field(default_factory=StyleProfile)
    argument_strategy: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected_style_directives"] = self.style_profile.to_dict()
        return payload


class ModelLibrary:
    FIELD_WEIGHTS = {
        "jurisdiction": 30,
        "forum": 25,
        "action_slug": 25,
        "document_kind": 20,
    }

    # Source types that require a physical file on disk.
    _FILE_BACKED_SOURCE_TYPES = frozenset({"pdf", "docx", "odt", "txt"})

    def __init__(self, index_path: str | Path, *, validate: bool = True) -> None:
        self.index_path = Path(index_path)
        self._all_records = self._load_records(self.index_path)
        self._integrity_warnings: list[str] = []
        self._excluded_model_ids: list[str] = []
        if validate:
            self._run_integrity_check()
        self.records = [
            r for r in self._all_records
            if r.model_id not in set(self._excluded_model_ids)
        ]

    def select_model(
        self,
        jurisdiction: str | None,
        forum: str | None,
        action_slug: str | None,
        document_kind: str | None,
        detected_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        tags = self._dedupe_normalized(detected_tags or [])
        normalized = {
            "jurisdiction": self._norm(jurisdiction),
            "forum": self._norm(forum),
            "action_slug": self._norm(action_slug),
            "document_kind": self._norm(document_kind),
        }

        attempts = [
            ("exact", self._exact_candidates),
            ("fallback_forum_action_document_kind", self._fallback_forum_action_document_candidates),
            ("fallback_forum_document_kind", self._fallback_forum_document_candidates),
        ]
        warnings: list[str] = []

        for match_type, finder in attempts:
            candidates = finder(normalized)
            if not candidates:
                continue
            best_record, best_score, score_notes = max(
                (self._score_candidate(record, normalized, tags, match_type) for record in candidates),
                key=lambda item: item[1],
            )
            warnings.extend(score_notes)
            if match_type != "exact":
                warnings.append(f"Se aplico {match_type} por falta de coincidencia exacta.")
            return {
                "selected_model": best_record.to_dict(),
                "match_type": match_type,
                "confidence": self._confidence(best_score, match_type),
                "style_directives": best_record.style_profile.to_dict(),
                "argument_strategy": dict(best_record.argument_strategy),
                "warnings": self._dedupe_preserve_order(warnings),
                "detected_tags": list(tags),
            }

        return {
            "selected_model": None,
            "match_type": "none",
            "confidence": 0.0,
            "style_directives": {},
            "argument_strategy": {},
            "warnings": ["No se encontro un modelo aplicable para los parametros recibidos."],
            "detected_tags": list(tags),
        }

    # ------------------------------------------------------------------
    # Integrity validation
    # ------------------------------------------------------------------

    def _run_integrity_check(self) -> None:
        """Check physical existence of source files at load time.

        Models whose source_type requires a file but whose source_path
        does not resolve are excluded from runtime selection and logged.
        """
        base_dir = self.index_path.parent.parent.parent.parent  # project root
        for record in self._all_records:
            if record.source_type not in self._FILE_BACKED_SOURCE_TYPES:
                continue
            if not record.source_path:
                msg = f"Modelo '{record.model_id}' tiene source_type='{record.source_type}' pero source_path vacio."
                self._integrity_warnings.append(msg)
                self._excluded_model_ids.append(record.model_id)
                logger.warning(msg)
                continue
            resolved = base_dir / record.source_path
            if not resolved.exists():
                msg = f"Modelo '{record.model_id}': archivo fuente no encontrado en '{resolved}'."
                self._integrity_warnings.append(msg)
                self._excluded_model_ids.append(record.model_id)
                logger.warning(msg)

    def validate_integrity(self) -> bool:
        """Return True if no integrity issues were found."""
        return len(self._integrity_warnings) == 0

    def get_integrity_report(self) -> dict[str, Any]:
        """Return a structured report of integrity checks."""
        return {
            "valid": self.validate_integrity(),
            "total_records": len(self._all_records),
            "active_records": len(self.records),
            "excluded_model_ids": list(self._excluded_model_ids),
            "warnings": list(self._integrity_warnings),
        }

    def _exact_candidates(self, normalized: dict[str, str]) -> list[ModelRecord]:
        return [
            record for record in self.records
            if self._matches_field(record.applicability.jurisdiction, normalized["jurisdiction"])
            and self._matches_field(record.applicability.forum, normalized["forum"])
            and self._matches_field(record.applicability.action_slug, normalized["action_slug"])
            and self._matches_field(record.applicability.document_kind, normalized["document_kind"])
        ]

    def _fallback_forum_action_document_candidates(self, normalized: dict[str, str]) -> list[ModelRecord]:
        return [
            record for record in self.records
            if self._matches_field(record.applicability.forum, normalized["forum"])
            and self._matches_field(record.applicability.action_slug, normalized["action_slug"])
            and self._matches_field(record.applicability.document_kind, normalized["document_kind"])
        ]

    def _fallback_forum_document_candidates(self, normalized: dict[str, str]) -> list[ModelRecord]:
        return [
            record for record in self.records
            if self._matches_field(record.applicability.forum, normalized["forum"])
            and self._matches_field(record.applicability.document_kind, normalized["document_kind"])
        ]

    def _score_candidate(
        self,
        record: ModelRecord,
        normalized: dict[str, str],
        tags: list[str],
        match_type: str,
    ) -> tuple[ModelRecord, int, list[str]]:
        applicability = record.applicability
        score = 0
        warnings: list[str] = []

        if match_type == "exact":
            for field_name, weight in self.FIELD_WEIGHTS.items():
                record_value = getattr(applicability, field_name)
                input_value = normalized[field_name]
                if record_value and input_value and self._norm(record_value) == input_value:
                    score += weight

        else:
            if applicability.forum and normalized["forum"] and self._norm(applicability.forum) == normalized["forum"]:
                score += self.FIELD_WEIGHTS["forum"]
            if applicability.action_slug and normalized["action_slug"] and self._norm(applicability.action_slug) == normalized["action_slug"]:
                score += self.FIELD_WEIGHTS["action_slug"]
            if applicability.document_kind and normalized["document_kind"] and self._norm(applicability.document_kind) == normalized["document_kind"]:
                score += self.FIELD_WEIGHTS["document_kind"]
            if applicability.jurisdiction and normalized["jurisdiction"] and self._norm(applicability.jurisdiction) == normalized["jurisdiction"]:
                score += 8
            if applicability.action_slug and normalized["action_slug"] and self._norm(applicability.action_slug) != normalized["action_slug"]:
                score -= 22
                warnings.append("Se penalizo un modelo especifico de otra accion dentro del fallback.")
            if applicability.jurisdiction and normalized["jurisdiction"] and self._norm(applicability.jurisdiction) != normalized["jurisdiction"]:
                score -= 8

        matched_tags = set(tags) & set(self._dedupe_normalized(applicability.tags))
        preferred_tags = set(tags) & set(self._dedupe_normalized(applicability.preferred_tags))
        excluded_tags = set(tags) & set(self._dedupe_normalized(applicability.excluded_tags))

        score += len(matched_tags) * 5
        score += len(preferred_tags) * 7
        score += max(int(record.priority), 0) * 3
        score += max(int(record.rating), 0)
        score -= len(excluded_tags) * 9

        if preferred_tags:
            warnings.append("La seleccion se reforzo por tags preferidos coincidentes.")
        if excluded_tags:
            warnings.append("Se detectaron tags excluidos y se penalizo la coincidencia.")

        return record, score, warnings

    def _confidence(self, score: int, match_type: str) -> float:
        base = {
            "exact": 0.7,
            "fallback_forum_action_document_kind": 0.5,
            "fallback_forum_document_kind": 0.35,
        }.get(match_type, 0.0)
        scaled = min(max(score, 0), 140) / 140.0
        return round(min(0.99, base + scaled * 0.29), 4)

    def _load_records(self, index_path: Path) -> list[ModelRecord]:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        raw_models = payload.get("models") if isinstance(payload, dict) else payload
        if not isinstance(raw_models, list):
            raise ValueError("El indice de model_library debe contener una lista en 'models'.")

        records: list[ModelRecord] = []
        for index, item in enumerate(raw_models):
            if not isinstance(item, dict):
                raise ValueError(f"Registro invalido en posicion {index}: se esperaba un objeto.")
            records.append(self._parse_record(item, index))
        return records

    def _parse_record(self, raw: dict[str, Any], index: int) -> ModelRecord:
        applicability_raw = raw.get("applicability")
        style_raw = raw.get("style_profile")
        if not isinstance(applicability_raw, dict):
            raise ValueError(f"Registro {index} sin bloque 'applicability' valido.")
        if not isinstance(style_raw, dict):
            raise ValueError(f"Registro {index} sin bloque 'style_profile' valido.")
        model_id = str(raw.get("model_id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not model_id or not name:
            raise ValueError(f"Registro {index} requiere 'model_id' y 'name'.")

        applicability = ApplicabilityRules(
            jurisdiction=self._norm(applicability_raw.get("jurisdiction")),
            forum=self._norm(applicability_raw.get("forum")),
            action_slug=self._norm(applicability_raw.get("action_slug")),
            document_kind=self._norm(applicability_raw.get("document_kind")),
            tags=self._dedupe_normalized(applicability_raw.get("tags") or []),
            preferred_tags=self._dedupe_normalized(applicability_raw.get("preferred_tags") or []),
            excluded_tags=self._dedupe_normalized(applicability_raw.get("excluded_tags") or []),
        )
        style_profile = StyleProfile(
            tone=str(style_raw.get("tone") or "balanced_prudent").strip(),
            structure=[str(item).strip() for item in (style_raw.get("structure") or []) if str(item).strip()],
            argument_density=str(style_raw.get("argument_density") or "standard").strip(),
            facts_style=str(style_raw.get("facts_style") or "concrete").strip(),
            petitum_style=str(style_raw.get("petitum_style") or "prudent").strip(),
            opening_line=str(style_raw.get("opening_line") or "").strip(),
            analysis_directive=str(style_raw.get("analysis_directive") or "").strip(),
            facts_directive=str(style_raw.get("facts_directive") or "").strip(),
            petitum_directive=str(style_raw.get("petitum_directive") or "").strip(),
            section_cues=[str(item).strip() for item in (style_raw.get("section_cues") or []) if str(item).strip()],
        )
        return ModelRecord(
            model_id=model_id,
            name=name,
            source_path=str(raw.get("source_path") or "").strip(),
            source_type=str(raw.get("source_type") or "pdf").strip(),
            priority=int(raw.get("priority", 0) or 0),
            rating=int(raw.get("rating", 0) or 0),
            applicability=applicability,
            style_profile=style_profile,
            argument_strategy=self._parse_argument_strategy(raw.get("argument_strategy")),
            notes=str(raw.get("notes") or "").strip(),
        )

    @staticmethod
    def _parse_argument_strategy(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        return {
            "focus": str(raw.get("focus") or "").strip(),
            "risk_tolerance": str(raw.get("risk_tolerance") or "").strip(),
            "proof_priority": [str(item).strip() for item in (raw.get("proof_priority") or []) if str(item).strip()],
            "normative_anchor": str(raw.get("normative_anchor") or "").strip(),
        }

    @staticmethod
    def _matches_field(record_value: str, input_value: str) -> bool:
        if not record_value:
            return False
        return record_value == input_value

    @staticmethod
    def _norm(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().replace("-", "_").split())

    def _dedupe_normalized(self, values: list[Any]) -> list[str]:
        return self._dedupe_preserve_order(self._norm(value) for value in values if self._norm(value))

    @staticmethod
    def _dedupe_preserve_order(values: Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result
