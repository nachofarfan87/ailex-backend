"""
AILEX -- local jurisprudence corpus loading, validation and normalization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from legal_engine.jurisprudence_loader import (
    DEFAULT_ALLOWED_DATASET_KINDS,
    DEFAULT_JURISPRUDENCE_CORPUS_ROOT,
    JurisprudenceLoader,
    RejectedPrecedentRecord,
)
from legal_engine.jurisprudence_schema import (
    JurisprudencePrecedent,
    clean_text,
    coerce_list,
    coerce_year,
    normalize_text,
)


JurisprudenceCorpusCase = JurisprudencePrecedent


@dataclass
class JurisprudenceIndexDocument:
    case: JurisprudenceCorpusCase
    core_search_text: str
    ranking_metadata_text: str
    editorial_metadata_text: str
    searchable_text: str
    core_tokens: set[str]
    searchable_tokens: set[str]
    topic_tokens: set[str]
    subtopic_tokens: set[str]
    keyword_tokens: set[str]
    factual_tokens: set[str]
    legal_issue_tokens: set[str]
    criterion_tokens: set[str]
    strategic_tokens: set[str]
    article_tokens: set[str]
    editorial_tokens: set[str]


@dataclass
class JurisprudenceCorpusSnapshot:
    root: str
    available: bool
    loaded: bool
    cases: list[JurisprudenceCorpusCase] = field(default_factory=list)
    documents: list[JurisprudenceIndexDocument] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_loaded: int = 0
    skipped_records: int = 0
    dataset_kinds: list[str] = field(default_factory=list)
    strict_cases: int = 0
    legacy_cases: int = 0
    rejected_details: list[RejectedPrecedentRecord] = field(default_factory=list)


class JurisprudenceCorpus:
    def __init__(
        self,
        corpus_root: Path | None = None,
        *,
        allowed_dataset_kinds: Iterable[str] | None = None,
    ) -> None:
        self._loader = JurisprudenceLoader(
            corpus_root=corpus_root if corpus_root is not None else DEFAULT_JURISPRUDENCE_CORPUS_ROOT,
            allowed_dataset_kinds=allowed_dataset_kinds or DEFAULT_ALLOWED_DATASET_KINDS,
        )
        self._snapshot: JurisprudenceCorpusSnapshot | None = None

    @property
    def corpus_root(self) -> Path:
        return self._loader.corpus_root

    @property
    def allowed_dataset_kinds(self) -> set[str]:
        return set(self._loader._allowed_dataset_kinds)

    def load(self) -> JurisprudenceCorpusSnapshot:
        if self._snapshot is not None:
            return self._snapshot

        available = self.corpus_root.exists()
        snapshot = JurisprudenceCorpusSnapshot(
            root=str(self.corpus_root),
            available=available,
            loaded=False,
        )
        if not available:
            self._snapshot = snapshot
            return snapshot

        warnings: list[str] = []
        cases: list[JurisprudenceCorpusCase] = []
        documents: list[JurisprudenceIndexDocument] = []
        dataset_kinds: set[str] = set()
        files_loaded = 0
        skipped_records = 0
        strict_cases = 0
        legacy_cases = 0
        rejected_details: list[RejectedPrecedentRecord] = []

        for path in self._iter_dataset_files():
            loaded_file = self._loader.load_file(path)
            warnings.extend(loaded_file.warnings)
            rejected_details.extend(loaded_file.rejected_records)
            skipped_records += loaded_file.rejected_count
            if not loaded_file.precedents:
                continue
            files_loaded += 1
            for precedent in loaded_file.precedents:
                cases.append(precedent)
                documents.append(self._build_index_document(precedent))
                dataset_kinds.add(precedent.dataset_kind)
                if precedent.ingest_mode == "strict":
                    strict_cases += 1
                else:
                    legacy_cases += 1

        snapshot.cases = cases
        snapshot.documents = documents
        snapshot.loaded = bool(cases)
        snapshot.warnings = self._dedupe(warnings)
        snapshot.files_loaded = files_loaded
        snapshot.skipped_records = skipped_records
        snapshot.dataset_kinds = sorted(dataset_kinds)
        snapshot.strict_cases = strict_cases
        snapshot.legacy_cases = legacy_cases
        snapshot.rejected_details = rejected_details
        self._snapshot = snapshot
        return snapshot

    @staticmethod
    def _extract_case_dicts(payload: Any) -> list[dict[str, Any]]:
        return JurisprudenceLoader.extract_records(payload)

    def _iter_dataset_files(self) -> list[Path]:
        return self._loader.iter_dataset_files()

    def _build_index_document(self, case: JurisprudenceCorpusCase) -> JurisprudenceIndexDocument:
        core_search_text = " ".join(
            part
            for part in (
                case.topic.replace("_", " "),
                (case.subtopic or "").replace("_", " "),
                case.legal_issue,
                case.criterion,
                case.strategic_use,
                " ".join(case.applied_articles),
                " ".join(case.keywords),
                case.facts_summary,
            )
            if part
        )
        ranking_metadata_text = " ".join(
            part
            for part in (
                case.case_name,
                case.action_slug,
                case.jurisdiction,
                case.forum,
                case.court,
                case.document_type,
                case.procedural_stage,
            )
            if part
        )
        editorial_metadata_text = " ".join(
            part
            for part in (
                case.territorial_priority,
                case.local_practice_value,
                case.court_level,
                case.redundancy_group,
                case.practical_frequency,
                case.local_topic_cluster,
            )
            if part
        )
        searchable_text = " ".join(part for part in (core_search_text, ranking_metadata_text) if part)
        return JurisprudenceIndexDocument(
            case=case,
            core_search_text=core_search_text,
            ranking_metadata_text=ranking_metadata_text,
            editorial_metadata_text=editorial_metadata_text,
            searchable_text=searchable_text,
            core_tokens=set(self.tokenize(core_search_text)),
            searchable_tokens=set(self.tokenize(searchable_text)),
            topic_tokens=set(self.tokenize(case.topic.replace("_", " "))),
            subtopic_tokens=set(self.tokenize((case.subtopic or "").replace("_", " "))),
            keyword_tokens=set(self.tokenize(" ".join(case.keywords))),
            factual_tokens=set(self.tokenize(case.facts_summary)),
            legal_issue_tokens=set(self.tokenize(case.legal_issue)),
            criterion_tokens=set(self.tokenize(case.criterion)),
            strategic_tokens=set(self.tokenize(case.strategic_use)),
            article_tokens=set(self.tokenize(" ".join(case.applied_articles))),
            editorial_tokens=set(self.tokenize(editorial_metadata_text)),
        )

    @staticmethod
    def normalize_text(text: Any) -> str:
        return normalize_text(text)

    @classmethod
    def tokenize(cls, text: Any) -> list[str]:
        normalized = cls.normalize_text(text)
        if not normalized:
            return []
        return [token for token in normalized.replace("/", " ").replace("_", " ").split() if len(token) >= 3]

    @staticmethod
    def _as_text(value: Any) -> str:
        return clean_text(value)

    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        return coerce_list(value)

    @classmethod
    def _coerce_year(cls, year_value: Any, date_value: Any) -> int | None:
        return coerce_year(year_value, date_value)

    @classmethod
    def _as_dataset_kind(cls, value: Any) -> str:
        normalized = cls.normalize_text(cls._as_text(value))
        if normalized in {"real", "seed", "fixture"}:
            return normalized
        return "real"

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            text = clean_text(item)
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result
