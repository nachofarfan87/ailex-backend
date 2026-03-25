"""
AILEX -- ActionClassifier

Clasifica consultas juridicas en lenguaje natural combinando:

  - patterns exactos
  - scoring por senales lexico-juridicas
  - metadatos procesales de una taxonomia separada
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from legal_engine.action_taxonomy import ACTION_TAXONOMY, ActionTaxonomyEntry


@dataclass
class ActionClassification:
    query: str
    normalized_query: str
    legal_intent: str
    action_slug: str
    action_label: str
    forum: str
    jurisdiction: str
    process_type: str
    domain: str
    confidence_score: float
    matched_patterns: list[str] = field(default_factory=list)
    semantic_aliases: list[str] = field(default_factory=list)
    retrieval_queries: list[str] = field(default_factory=list)
    priority_articles: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "normalized_query": self.normalized_query,
            "legal_intent": self.legal_intent,
            "action_slug": self.action_slug,
            "action_label": self.action_label,
            "forum": self.forum,
            "jurisdiction": self.jurisdiction,
            "process_type": self.process_type,
            "domain": self.domain,
            "confidence_score": self.confidence_score,
            "matched_patterns": list(self.matched_patterns),
            "semantic_aliases": list(self.semantic_aliases),
            "retrieval_queries": list(self.retrieval_queries),
            "priority_articles": [dict(item) for item in self.priority_articles],
            "metadata": dict(self.metadata),
        }


class ActionClassifier:
    def __init__(self, default_jurisdiction: str = "jujuy") -> None:
        self._default_jurisdiction = default_jurisdiction

    def classify(
        self,
        query: str,
        jurisdiction: str | None = None,
        forum: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ActionClassification | None:
        query = (query or "").strip()
        if not query:
            return None

        normalized_query = normalize_legal_text(query)
        best_entry: ActionTaxonomyEntry | None = None
        best_score = 0.0
        best_hits: list[str] = []

        for entry in ACTION_TAXONOMY:
            score, hits = self._score_entry(normalized_query, entry)
            if score > best_score:
                best_score = score
                best_entry = entry
                best_hits = hits

        if best_entry is None or best_score < best_entry.minimum_score:
            return None

        resolved_jurisdiction = (
            normalize_legal_text(jurisdiction or self._default_jurisdiction)
            or self._default_jurisdiction
        )
        resolved_forum = normalize_legal_text(forum or best_entry.forum) or best_entry.forum

        retrieval_queries = [
            normalized_query,
            *best_entry.retrieval_queries,
            *best_entry.semantic_aliases,
        ]
        retrieval_queries = _dedupe_preserve_order(
            [item for item in retrieval_queries if item]
        )

        confidence = round(
            min(max(best_score / max(best_entry.minimum_score + 1.8, 1.0), 0.0), 0.99),
            4,
        )

        return ActionClassification(
            query=query,
            normalized_query=normalized_query,
            legal_intent=best_entry.legal_intent,
            action_slug=best_entry.action_slug,
            action_label=best_entry.action_label,
            forum=resolved_forum,
            jurisdiction=resolved_jurisdiction,
            process_type=best_entry.process_type,
            domain=best_entry.domain,
            confidence_score=confidence,
            matched_patterns=best_hits,
            semantic_aliases=list(best_entry.semantic_aliases),
            retrieval_queries=retrieval_queries,
            priority_articles=[dict(item) for item in best_entry.priority_articles],
            metadata={**best_entry.metadata, **(metadata or {})},
        )

    def _score_entry(
        self,
        normalized_query: str,
        entry: ActionTaxonomyEntry,
    ) -> tuple[float, list[str]]:
        hits: list[str] = []
        score = 0.0

        pattern_hits = [
            pattern for pattern in entry.patterns
            if pattern in normalized_query
        ]
        if pattern_hits:
            score += len(pattern_hits) * 2.2
            hits.extend(pattern_hits)

        signal_hits = []
        for signal, weight in entry.weighted_signals.items():
            if signal in normalized_query:
                score += weight
                signal_hits.append(signal)

        if signal_hits:
            hits.extend(f"signal:{signal}" for signal in signal_hits)

        missing_required_groups = 0
        for group in entry.required_signal_groups:
            if any(signal in normalized_query for signal in group):
                score += 0.55
            else:
                missing_required_groups += 1

        if missing_required_groups and not pattern_hits:
            return 0.0, []

        if pattern_hits and missing_required_groups:
            score -= 0.35 * missing_required_groups

        if pattern_hits and signal_hits:
            score += 0.4

        return round(score, 4), _dedupe_preserve_order(hits)


def normalize_legal_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    lowered = stripped.casefold()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return " ".join(lowered.split())


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
