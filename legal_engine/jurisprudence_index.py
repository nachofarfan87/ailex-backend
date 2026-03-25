"""
AILEX -- lightweight local index and hybrid ranking for jurisprudence retrieval.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from legal_engine.jurisprudence_corpus import JurisprudenceCorpus, JurisprudenceIndexDocument


ACTION_SLUG_ALIASES = {
    "divorcio": {"divorcio", "divorcio_incausado", "efectos_accesorios", "propuesta_reguladora"},
    "divorcio_unilateral": {"divorcio_unilateral", "divorcio", "oposicion_conyuge", "propuesta_reguladora"},
    "divorcio_mutuo_acuerdo": {"divorcio_mutuo_acuerdo", "divorcio", "acuerdo_regulador", "convenio_regulador"},
    "alimentos_hijos": {
        "alimentos_hijos",
        "alimentos",
        "cuota_alimentaria",
        "cuota_provisoria",
        "cuota_alimentaria_provisoria",
        "alimentos_provisorios",
        "aumento_de_cuota",
        "reduccion_de_cuota",
    },
    "cuidado_personal": {"cuidado_personal", "cuidado", "centro_de_vida", "coparentalidad"},
    "sucesion_ab_intestato": {"sucesion_ab_intestato", "sucesion", "sucesorio", "declaratoria_de_herederos"},
}


@dataclass
class JurisprudenceQueryContext:
    action_slug: str
    jurisdiction: str
    forum: str
    local_intent: bool = False
    query_tokens: set[str] = field(default_factory=set)
    topic_tokens: set[str] = field(default_factory=set)
    subtopic_tokens: set[str] = field(default_factory=set)
    issue_tokens: set[str] = field(default_factory=set)
    criterion_tokens: set[str] = field(default_factory=set)
    strategic_tokens: set[str] = field(default_factory=set)
    keyword_tokens: set[str] = field(default_factory=set)
    article_tokens: set[str] = field(default_factory=set)
    factual_tokens: set[str] = field(default_factory=set)

    @property
    def core_tokens(self) -> set[str]:
        return set().union(
            self.query_tokens,
            self.topic_tokens,
            self.subtopic_tokens,
            self.issue_tokens,
            self.criterion_tokens,
            self.strategic_tokens,
            self.keyword_tokens,
            self.article_tokens,
            self.factual_tokens,
        )


@dataclass
class JurisprudenceIndexMatch:
    document: JurisprudenceIndexDocument
    score: float
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)


class JurisprudenceIndex:
    W_ACTION = 0.18
    W_TOPIC = 0.18
    W_SUBTOPIC = 0.15
    W_LEGAL_ISSUE = 0.15
    W_CRITERION = 0.14
    W_STRATEGIC = 0.08
    W_ARTICLES = 0.05
    W_KEYWORDS = 0.04
    W_FACTS = 0.03
    W_JURISDICTION = 0.06
    W_FORUM = 0.03
    W_LOCAL_EDITORIAL = 0.02

    @staticmethod
    def normalize_action_slug(value: str) -> str:
        normalized = JurisprudenceCorpus.normalize_text(value).replace(" ", "_")
        if not normalized:
            return ""
        for canonical, aliases in ACTION_SLUG_ALIASES.items():
            if normalized == canonical or normalized in aliases:
                return canonical
        return normalized

    @staticmethod
    def action_aliases(value: str) -> set[str]:
        canonical = JurisprudenceIndex.normalize_action_slug(value)
        if not canonical:
            return set()
        return set(ACTION_SLUG_ALIASES.get(canonical, {canonical}))

    def __init__(self, documents: list[JurisprudenceIndexDocument]) -> None:
        self._documents = list(documents)
        self._idf = self._build_idf(self._documents)

    @property
    def idf(self) -> dict[str, float]:
        return dict(self._idf)

    def build_query_context(
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
    ) -> JurisprudenceQueryContext:
        classification = classification or {}
        case_structure = case_structure or {}
        normative_reasoning = normative_reasoning or {}
        case_theory = case_theory or {}
        evidence_reasoning_links = evidence_reasoning_links or {}

        action_slug = self.normalize_action_slug(str(classification.get("action_slug") or ""))
        issue_parts = [
            classification.get("action_label"),
            *(normative_reasoning.get("requirements") or []),
            *(normative_reasoning.get("unresolved_issues") or []),
        ]
        criterion_parts = [
            case_theory.get("primary_theory"),
            *(evidence_reasoning_links.get("globally_supported_requirements") or []),
        ]
        keyword_parts = [
            *(case_structure.get("keywords") or []),
            *(classification.get("keywords") or []),
        ]
        fact_parts = [
            *(case_structure.get("facts") or []),
            *(case_theory.get("key_facts_supporting") or []),
        ]

        subtopic_tokens = self._extract_subtopic_tokens(query, classification)
        return JurisprudenceQueryContext(
            action_slug=action_slug,
            jurisdiction=JurisprudenceCorpus.normalize_text(jurisdiction or classification.get("jurisdiction") or ""),
            forum=JurisprudenceCorpus.normalize_text(forum or classification.get("forum") or ""),
            local_intent=self._detect_local_intent(query, classification, jurisdiction),
            query_tokens=set(JurisprudenceCorpus.tokenize(query)),
            topic_tokens=self._action_alias_tokens(action_slug),
            subtopic_tokens=subtopic_tokens,
            issue_tokens=set(JurisprudenceCorpus.tokenize(" ".join(str(item) for item in issue_parts if item))),
            criterion_tokens=set(JurisprudenceCorpus.tokenize(" ".join(str(item) for item in criterion_parts if item))),
            strategic_tokens=set(JurisprudenceCorpus.tokenize(str(case_theory.get("objective") or ""))),
            keyword_tokens=set(JurisprudenceCorpus.tokenize(" ".join(str(item) for item in keyword_parts if item))),
            article_tokens=self._extract_article_tokens(normative_reasoning),
            factual_tokens=set(JurisprudenceCorpus.tokenize(" ".join(str(item) for item in fact_parts if item))),
        )

    def search(self, context: JurisprudenceQueryContext, *, top_k: int = 5) -> list[JurisprudenceIndexMatch]:
        results: list[JurisprudenceIndexMatch] = []
        for document in self._documents:
            score, reasons, matched_terms = self.score_document(document=document, context=context)
            if score <= 0:
                continue
            results.append(
                JurisprudenceIndexMatch(
                    document=document,
                    score=score,
                    reasons=reasons,
                    matched_terms=matched_terms,
                )
            )
        results.sort(
            key=lambda item: (
                item.score,
                1 if item.document.case.ingest_mode == "strict" else 0,
                1 if item.document.case.dataset_kind == "real" else 0,
            ),
            reverse=True,
        )
        return results[: max(1, top_k)]

    def score_document(
        self,
        *,
        document: JurisprudenceIndexDocument,
        context: JurisprudenceQueryContext,
    ) -> tuple[float, list[str], list[str]]:
        if not context.core_tokens and not context.action_slug:
            return 0.0, [], []

        action_match = self._action_score(document.case.action_slug, context.action_slug)
        topic_overlap = self._weighted_overlap(context.topic_tokens or context.core_tokens, document.topic_tokens)
        subtopic_overlap = self._weighted_overlap(context.subtopic_tokens, document.subtopic_tokens)
        issue_overlap = self._weighted_overlap(context.issue_tokens | context.query_tokens, document.legal_issue_tokens)
        criterion_overlap = self._weighted_overlap(context.criterion_tokens | context.query_tokens, document.criterion_tokens)
        strategic_overlap = self._weighted_overlap(context.strategic_tokens | context.keyword_tokens, document.strategic_tokens)
        article_overlap = self._weighted_overlap(context.article_tokens, document.article_tokens)
        keyword_overlap = self._weighted_overlap(context.keyword_tokens | context.query_tokens, document.keyword_tokens)
        facts_overlap = self._weighted_overlap(context.factual_tokens, document.factual_tokens)
        jurisdiction_match = 1.0 if context.jurisdiction and JurisprudenceCorpus.normalize_text(document.case.jurisdiction) == context.jurisdiction else 0.0
        forum_match = 1.0 if context.forum and JurisprudenceCorpus.normalize_text(document.case.forum) == context.forum else 0.0
        local_editorial_boost = self._local_editorial_score(document, context)

        score = (
            (action_match * self.W_ACTION)
            + (topic_overlap * self.W_TOPIC)
            + (subtopic_overlap * self.W_SUBTOPIC)
            + (issue_overlap * self.W_LEGAL_ISSUE)
            + (criterion_overlap * self.W_CRITERION)
            + (strategic_overlap * self.W_STRATEGIC)
            + (article_overlap * self.W_ARTICLES)
            + (keyword_overlap * self.W_KEYWORDS)
            + (facts_overlap * self.W_FACTS)
            + (jurisdiction_match * self.W_JURISDICTION)
            + (forum_match * self.W_FORUM)
            + (local_editorial_boost * self.W_LOCAL_EDITORIAL)
        )
        if document.case.ingest_mode == "strict":
            score += 0.015
        score = round(min(0.99, score), 6)

        reasons: list[str] = []
        if document.case.ingest_mode == "strict":
            reasons.append("precedente real curado en modo estricto")
        else:
            reasons.append("precedente importado en modo legacy")
        if action_match:
            reasons.append("coincidencia exacta de materia")
        if topic_overlap >= 0.18:
            reasons.append("coincidencia de topic")
        if subtopic_overlap >= 0.12:
            reasons.append("coincidencia de subtopic")
        if issue_overlap >= 0.14:
            reasons.append("similitud en legal_issue")
        if criterion_overlap >= 0.14:
            reasons.append("similitud en criterion")
        if article_overlap > 0:
            reasons.append("solapamiento de articulos aplicados")
        if keyword_overlap >= 0.12:
            reasons.append("coincidencia de keywords")
        if jurisdiction_match:
            reasons.append("coincidencia jurisdiccional")
        if local_editorial_boost >= 0.5:
            reasons.append("priorizacion editorial local de Jujuy")

        matched_terms = self._top_terms(context.core_tokens & document.core_tokens)
        return score, self._dedupe(reasons), matched_terms

    def _weighted_overlap(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        intersection = left & right
        if not intersection:
            return 0.0
        numerator = sum(self._idf.get(token, 1.0) for token in intersection)
        denominator = sum(self._idf.get(token, 1.0) for token in left)
        if denominator <= 0:
            return 0.0
        return numerator / denominator

    @staticmethod
    def _extract_article_tokens(normative_reasoning: dict[str, Any]) -> set[str]:
        tokens: set[str] = set()
        for item in normative_reasoning.get("applied_rules") or []:
            if not isinstance(item, dict):
                continue
            tokens.update(JurisprudenceCorpus.tokenize(str(item.get("article") or "")))
            tokens.update(JurisprudenceCorpus.tokenize(str(item.get("source") or item.get("source_id") or "")))
        return tokens

    @staticmethod
    def _detect_local_intent(query: str, classification: dict[str, Any], jurisdiction: str | None) -> bool:
        jurisdiction_hint = JurisprudenceCorpus.normalize_text(jurisdiction or classification.get("jurisdiction") or "")
        if jurisdiction_hint == "jujuy":
            return True
        query_text = JurisprudenceCorpus.normalize_text(query)
        return "jujuy" in query_text or "perico" in query_text or "san pedro" in query_text

    def _local_editorial_score(self, document: JurisprudenceIndexDocument, context: JurisprudenceQueryContext) -> float:
        if not context.local_intent:
            return 0.0
        if JurisprudenceCorpus.normalize_text(document.case.jurisdiction) != "jujuy":
            return 0.0
        values = [
            self._scale_local_value(document.case.territorial_priority),
            self._scale_local_value(document.case.local_practice_value),
        ]
        values = [value for value in values if value > 0]
        return sum(values) / len(values) if values else 0.2

    @staticmethod
    def _scale_local_value(value: str) -> float:
        normalized = JurisprudenceCorpus.normalize_text(value)
        if normalized in {"alta", "alto", "critica", "critico"}:
            return 1.0
        if normalized in {"media", "medio", "relevante"}:
            return 0.6
        if normalized in {"baja", "bajo"}:
            return 0.3
        return 0.0

    def _top_terms(self, tokens: set[str], limit: int = 6) -> list[str]:
        ranked = sorted(tokens, key=lambda token: (self._idf.get(token, 1.0), token), reverse=True)
        return ranked[:limit]

    @classmethod
    def _extract_subtopic_tokens(cls, query: str, classification: dict[str, Any]) -> set[str]:
        value = str(classification.get("subtopic") or "")
        tokens = set(JurisprudenceCorpus.tokenize(value))
        query_text = JurisprudenceCorpus.normalize_text(query)
        if "provisori" in query_text:
            tokens.update({"provisoria", "provisorios"})
        if "universitar" in query_text:
            tokens.update({"universitaria", "estudiante"})
        if "centro de vida" in query_text:
            tokens.update({"centro", "vida"})
        return tokens

    @classmethod
    def _action_alias_tokens(cls, action_slug: str) -> set[str]:
        tokens: set[str] = set()
        for alias in cls.action_aliases(action_slug):
            tokens.update(JurisprudenceCorpus.tokenize(alias.replace("_", " ")))
        return tokens

    @classmethod
    def _action_score(cls, document_slug: str, context_slug: str) -> float:
        document_canonical = cls.normalize_action_slug(document_slug)
        context_canonical = cls.normalize_action_slug(context_slug)
        if not document_canonical or not context_canonical:
            return 0.0
        if document_canonical == context_canonical:
            return 1.0
        if cls.action_aliases(document_canonical) & cls.action_aliases(context_canonical):
            return 0.82
        return 0.0

    @staticmethod
    def _build_idf(documents: list[JurisprudenceIndexDocument]) -> dict[str, float]:
        if not documents:
            return {}
        doc_freq: dict[str, int] = {}
        for document in documents:
            for token in document.core_tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1
        n_docs = len(documents)
        return {token: math.log((n_docs + 1) / (df + 1)) + 1.0 for token, df in doc_freq.items()}

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
