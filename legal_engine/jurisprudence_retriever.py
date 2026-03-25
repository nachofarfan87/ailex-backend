"""
AILEX -- jurisprudence retrieval over a local structured corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from legal_engine.jurisprudence_corpus import (
    DEFAULT_ALLOWED_DATASET_KINDS,
    DEFAULT_JURISPRUDENCE_CORPUS_ROOT,
    JurisprudenceCorpus,
    JurisprudenceCorpusCase,
)
from legal_engine.jurisprudence_index import JurisprudenceIndex


RetrievedJurisprudenceCase = JurisprudenceCorpusCase


@dataclass
class RetrievalMatch:
    case: RetrievedJurisprudenceCase
    score: float
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class JurisprudenceRetrievalResult:
    matches: list[RetrievalMatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    corpus_available: bool = False
    corpus_loaded: bool = False
    corpus_root: str = ""
    total_cases: int = 0
    strict_cases: int = 0
    legacy_cases: int = 0
    candidate_cases: int = 0
    accepted_cases: int = 0
    accepted_real_cases: int = 0
    accepted_legacy_cases: int = 0
    rejected_weak_matches: int = 0
    skipped_records: int = 0
    files_loaded: int = 0
    top_score: float = 0.0
    policy_summary: str = ""


class JurisprudenceRetriever:
    def __init__(
        self,
        corpus_root: Path | None = None,
        *,
        allowed_dataset_kinds: Iterable[str] | None = None,
        min_primary_score: float = 0.34,
        min_secondary_score: float = 0.27,
        weak_match_score: float = 0.25,
        relative_secondary_floor: float = 0.75,
        max_results: int = 4,
    ) -> None:
        self._corpus = JurisprudenceCorpus(
            corpus_root=corpus_root if corpus_root is not None else DEFAULT_JURISPRUDENCE_CORPUS_ROOT,
            allowed_dataset_kinds=allowed_dataset_kinds or DEFAULT_ALLOWED_DATASET_KINDS,
        )
        self._min_primary_score = float(min_primary_score)
        self._min_secondary_score = float(min_secondary_score)
        self._weak_match_score = float(weak_match_score)
        self._relative_secondary_floor = float(relative_secondary_floor)
        self._max_results = int(max(1, max_results))

    def search(
        self,
        *,
        query: str,
        classification: dict[str, Any] | None = None,
        case_structure: dict[str, Any] | None = None,
        normative_reasoning: dict[str, Any] | None = None,
        case_theory: dict[str, Any] | None = None,
        evidence_reasoning_links: dict[str, Any] | None = None,
        jurisdiction: str | None = None,
        forum: str | None = None,
        top_k: int | None = None,
    ) -> JurisprudenceRetrievalResult:
        classification = classification or {}
        case_structure = case_structure or {}
        normative_reasoning = normative_reasoning or {}
        case_theory = case_theory or {}
        evidence_reasoning_links = evidence_reasoning_links or {}

        snapshot = self._corpus.load()
        result = JurisprudenceRetrievalResult(
            warnings=list(snapshot.warnings),
            corpus_available=snapshot.available,
            corpus_loaded=snapshot.loaded,
            corpus_root=snapshot.root,
            total_cases=len(snapshot.cases),
            strict_cases=snapshot.strict_cases,
            legacy_cases=snapshot.legacy_cases,
            skipped_records=snapshot.skipped_records,
            files_loaded=snapshot.files_loaded,
            policy_summary=(
                "El retrieval prioriza precedentes reales strict; solo usa precedentes legacy cuando no hay base real suficiente y nunca confunde metadata editorial con criterio juridico."
            ),
        )

        if not snapshot.available:
            result.warnings.append("El corpus jurisprudencial local no esta disponible; no fue posible intentar retrieval.")
            return self._finalize(result)
        if not snapshot.loaded:
            result.warnings.append("El corpus jurisprudencial local no contiene precedentes utilizables para retrieval.")
            return self._finalize(result)
        if snapshot.strict_cases == 0:
            result.warnings.append("El corpus cargado no contiene precedentes reales en modo estricto; cualquier match sera necesariamente legacy.")
        elif snapshot.strict_cases < 2:
            result.warnings.append("El corpus real estricto es reducido; la inferencia jurisprudencial puede ser estrecha.")

        index = JurisprudenceIndex(snapshot.documents)
        context = index.build_query_context(
            query=query,
            classification=classification,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            case_theory=case_theory,
            evidence_reasoning_links=evidence_reasoning_links,
            jurisdiction=jurisdiction,
            forum=forum,
        )
        ranked = index.search(context, top_k=top_k or self._max_results)
        result.candidate_cases = len(ranked)
        result.top_score = ranked[0].score if ranked else 0.0
        if not ranked:
            result.warnings.append("No se encontraron coincidencias relevantes en el corpus jurisprudencial para esta consulta.")
            return self._finalize(result)

        accepted = self._accept_matches(ranked)
        result.matches = [
            RetrievalMatch(case=item.document.case, score=item.score, reasons=list(item.reasons), matched_terms=list(item.matched_terms))
            for item in accepted
        ]
        result.accepted_cases = len(result.matches)
        result.accepted_real_cases = sum(1 for item in result.matches if item.case.ingest_mode == "strict")
        result.accepted_legacy_cases = sum(1 for item in result.matches if item.case.ingest_mode != "strict")
        result.rejected_weak_matches = max(0, len(ranked) - len(result.matches))

        if not result.matches:
            if result.top_score >= self._weak_match_score:
                result.warnings.append("Hubo coincidencias en el corpus, pero fueron descartadas por insuficiencia para evitar falsa precision.")
            else:
                result.warnings.append("No se encontraron coincidencias relevantes en el corpus jurisprudencial para esta consulta.")
            return self._finalize(result)

        if result.accepted_real_cases:
            result.warnings.append("La orientacion se apoya prioritariamente en precedentes reales curados del corpus.")
        elif result.accepted_legacy_cases:
            result.warnings.append("No hubo precedentes reales suficientes; se utilizaron solo precedentes legacy importados con menor fuerza orientativa.")
        if result.rejected_weak_matches > 0:
            result.warnings.append("Se descartaron coincidencias mas debiles para preservar prudencia jurisprudencial.")
        return self._finalize(result)

    def _load_cases(self) -> tuple[list[RetrievedJurisprudenceCase], list[str]]:
        snapshot = self._corpus.load()
        return list(snapshot.cases), list(snapshot.warnings)

    def _ensure_idf(self, documents: list[Any]) -> dict[str, float]:
        return JurisprudenceIndex(list(documents)).idf

    def _tokenize(self, text: str) -> list[str]:
        return self._corpus.tokenize(text)

    def _field_overlap(self, context_tokens: set[str], field_text: str, idf: dict[str, float]) -> float:
        if not context_tokens:
            return 0.0
        field_tokens = set(self._tokenize(field_text))
        if not field_tokens:
            return 0.0
        intersection = context_tokens & field_tokens
        if not intersection:
            return 0.0
        numerator = sum(idf.get(token, 1.0) for token in intersection)
        denominator = sum(idf.get(token, 1.0) for token in context_tokens)
        if denominator <= 0:
            return 0.0
        return numerator / denominator

    def _accept_matches(self, matches: list[Any]) -> list[Any]:
        if not matches:
            return []
        top_match = matches[0]
        if top_match.score < self._min_primary_score:
            return []

        accepted: list[Any] = []
        for match in matches:
            if len(accepted) >= self._max_results:
                break
            if not accepted:
                accepted.append(match)
                continue
            if match.score < self._min_secondary_score:
                continue
            if match.score < (top_match.score * self._relative_secondary_floor):
                continue
            accepted.append(match)

        real_matches = [item for item in accepted if item.document.case.ingest_mode == "strict"]
        if real_matches:
            return real_matches
        return accepted

    @staticmethod
    def _finalize(result: JurisprudenceRetrievalResult) -> JurisprudenceRetrievalResult:
        result.warnings = JurisprudenceRetriever._dedupe(result.warnings)
        return result

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result
