# backend/legal_engine/jurisprudence_engine.py
"""
AILEX -- JurisprudenceEngine

Endurece la capa jurisprudencial para que:
- priorice precedentes reales strict,
- use legacy solo como segunda capa excepcional,
- use perfiles internos solo cuando haya contexto minimo suficiente,
- exponga flags claros para que la capa de generacion no redacte como si
  hubiera jurisprudencia real cuando no la hay.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from legal_engine.jurisprudence_index import JurisprudenceIndex
from legal_engine.jurisprudence_retriever import JurisprudenceRetrievalResult, JurisprudenceRetriever


SOURCE_MODE_RETRIEVED = "retrieved_real_precedent"
SOURCE_MODE_LEGACY = "legacy_imported_precedent"
SOURCE_MODE_INTERNAL = "internal_fallback_profile"

SOURCE_QUALITY_REAL = "real"
SOURCE_QUALITY_LEGACY = "legacy"
SOURCE_QUALITY_FALLBACK = "fallback"
SOURCE_QUALITY_NONE = "none"

JURISPRUDENCE_STRENGTH_STRONG = "strong"
JURISPRUDENCE_STRENGTH_MODERATE = "moderate"
JURISPRUDENCE_STRENGTH_WEAK = "weak"
JURISPRUDENCE_STRENGTH_NONE = "none"


@dataclass
class JurisprudenceCase:
    court: str
    year: int
    case_name: str
    legal_issue: str
    decision_summary: str
    applied_articles: list[str] = field(default_factory=list)
    thematic_references: list[str] = field(default_factory=list)
    key_reasoning: str = ""
    outcome: str = ""
    source_mode: str = SOURCE_MODE_INTERNAL
    source_id: str = ""
    source: str = ""
    source_url: str = ""
    chamber: str = ""
    jurisdiction: str = ""
    forum: str = ""
    date: str = ""
    case_id: str = ""
    facts_summary: str = ""
    holding: str = ""
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    action_slug: str = ""
    procedural_stage: str = ""
    document_type: str = ""
    dataset_kind: str = ""
    strategic_value: str = ""
    territorial_priority: str = ""
    local_practice_value: str = ""
    court_level: str = ""
    redundancy_group: str = ""
    practical_frequency: str = ""
    local_topic_cluster: str = ""
    retrieval_score: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    criterion_summary: str = ""
    strategic_use: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "court": self.court,
            "year": self.year,
            "case_name": self.case_name,
            "legal_issue": self.legal_issue,
            "decision_summary": self.decision_summary,
            "applied_articles": list(self.applied_articles),
            "thematic_references": list(self.thematic_references or self.applied_articles),
            "key_reasoning": self.key_reasoning,
            "outcome": self.outcome,
            "source_mode": self.source_mode,
            "source_id": self.source_id,
            "source": self.source,
            "source_url": self.source_url,
            "chamber": self.chamber,
            "jurisdiction": self.jurisdiction,
            "forum": self.forum,
            "date": self.date,
            "case_id": self.case_id or self.source_id,
            "facts_summary": self.facts_summary,
            "holding": self.holding,
            "topics": list(self.topics),
            "keywords": list(self.keywords),
            "action_slug": self.action_slug,
            "procedural_stage": self.procedural_stage,
            "document_type": self.document_type,
            "dataset_kind": self.dataset_kind,
            "strategic_value": self.strategic_value,
            "territorial_priority": self.territorial_priority,
            "local_practice_value": self.local_practice_value,
            "court_level": self.court_level,
            "redundancy_group": self.redundancy_group,
            "practical_frequency": self.practical_frequency,
            "local_topic_cluster": self.local_topic_cluster,
            "retrieval_score": self.retrieval_score,
            "matched_terms": list(self.matched_terms),
            "criterion_summary": self.criterion_summary,
            "criterion": self.criterion_summary,
            "strategic_use": self.strategic_use,
        }


@dataclass
class JurisprudenceHighlight:
    case_name: str
    court: str
    year: int
    legal_issue: str
    criterion: str
    strategic_use: str
    applied_articles: list[str]
    source_mode: str
    source_label: str
    source_url: str = ""
    retrieval_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_name": self.case_name,
            "court": self.court,
            "year": self.year,
            "legal_issue": self.legal_issue,
            "criterion": self.criterion,
            "strategic_use": self.strategic_use,
            "applied_articles": list(self.applied_articles),
            "source_mode": self.source_mode,
            "source_label": self.source_label,
            "source_url": self.source_url,
            "retrieval_score": self.retrieval_score,
        }


@dataclass
class StructuredInternalProfile:
    profile_label: str
    profile_revision: int
    profile_name: str
    legal_issue: str
    criterion: str
    strategic_use: str
    thematic_references: list[str] = field(default_factory=list)
    projected_outcome: str = ""

    def to_case(self, *, action_slug: str) -> JurisprudenceCase:
        return JurisprudenceCase(
            court=self.profile_label,
            year=self.profile_revision,
            case_name=self.profile_name,
            legal_issue=self.legal_issue,
            decision_summary=self.criterion,
            applied_articles=list(self.thematic_references),
            thematic_references=list(self.thematic_references),
            key_reasoning=self.criterion,
            outcome=self.projected_outcome or self.strategic_use,
            source_mode=SOURCE_MODE_INTERNAL,
            action_slug=action_slug,
            criterion_summary=self.criterion,
            strategic_use=self.strategic_use,
            strategic_value=self.strategic_use,
        )


@dataclass
class JurisprudenceAnalysisResult:
    relevant_cases: list[JurisprudenceCase] = field(default_factory=list)
    jurisprudence_highlights: list[JurisprudenceHighlight] = field(default_factory=list)
    dominant_criteria: list[str] = field(default_factory=list)
    possible_outcomes: list[str] = field(default_factory=list)
    strategic_implications: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    source_mode_summary: str = ""
    source_quality: str = SOURCE_QUALITY_NONE
    jurisprudence_strength: str = JURISPRUDENCE_STRENGTH_NONE
    usable_real_precedents: int = 0
    usable_legacy_precedents: int = 0
    used_internal_fallback: bool = False
    should_limit_claims: bool = True
    should_avoid_jurisprudential_assertions: bool = True
    precedent_trend: str = "neutral"
    confidence_delta: float = 0.0
    reasoning_directive: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevant_cases": [item.to_dict() for item in self.relevant_cases],
            "jurisprudence_highlights": [item.to_dict() for item in self.jurisprudence_highlights],
            "dominant_criteria": list(self.dominant_criteria),
            "possible_outcomes": list(self.possible_outcomes),
            "strategic_implications": list(self.strategic_implications),
            "warnings": list(self.warnings),
            "confidence_score": self.confidence_score,
            "source_mode_summary": self.source_mode_summary,
            "source_quality": self.source_quality,
            "jurisprudence_strength": self.jurisprudence_strength,
            "usable_real_precedents": self.usable_real_precedents,
            "usable_legacy_precedents": self.usable_legacy_precedents,
            "used_internal_fallback": self.used_internal_fallback,
            "should_limit_claims": self.should_limit_claims,
            "should_avoid_jurisprudential_assertions": self.should_avoid_jurisprudential_assertions,
            "precedent_trend": self.precedent_trend,
            "confidence_delta": self.confidence_delta,
            "reasoning_directive": self.reasoning_directive,
        }


class JurisprudenceEngine:
    _ADMIN_MARKERS = (
        "registrese",
        "notifiquese",
        "hagase saber",
        "archivese",
        "poder judicial",
        "en la ciudad de",
        "expte",
        "expediente",
        "legajo",
    )

    def __init__(self, *, jurisprudence_retriever: JurisprudenceRetriever | None = None) -> None:
        self._retriever = jurisprudence_retriever or JurisprudenceRetriever()
        self._structured_profiles = self._build_structured_profiles()

    def analyze(
        self,
        query: str,
        classification: Any = None,
        case_structure: Any = None,
        normative_reasoning: Any = None,
        case_theory: Any = None,
        evidence_reasoning_links: Any = None,
    ) -> JurisprudenceAnalysisResult:
        cls = self._coerce_dict(classification)
        case = self._coerce_dict(case_structure)
        normative = self._coerce_dict(normative_reasoning)
        theory = self._coerce_dict(case_theory)
        evidence = self._coerce_dict(evidence_reasoning_links)

        action_slug = JurisprudenceIndex.normalize_action_slug(str(cls.get("action_slug") or "").strip().lower())
        if action_slug:
            cls["action_slug"] = action_slug

        retrieval = self._retriever.search(
            query=query,
            classification=cls,
            case_structure=case,
            normative_reasoning=normative,
            case_theory=theory,
            evidence_reasoning_links=evidence,
            jurisdiction=str(cls.get("jurisdiction") or ""),
            forum=str(cls.get("forum") or ""),
            top_k=3,
        )

        real_matches = [item for item in retrieval.matches if item.case.ingest_mode == "strict"]
        legacy_matches = [item for item in retrieval.matches if item.case.ingest_mode != "strict"]

        relevant_cases: list[JurisprudenceCase] = []
        source_mode_summary = ""
        source_quality = SOURCE_QUALITY_NONE
        jurisprudence_strength = JURISPRUDENCE_STRENGTH_NONE
        used_internal_fallback = False

        if real_matches:
            relevant_cases = [
                self._from_retrieved_match(item, source_mode=SOURCE_MODE_RETRIEVED)
                for item in real_matches
            ]
            source_mode_summary = self._build_retrieved_summary(real_matches, retrieval, real=True)
            source_quality = SOURCE_QUALITY_REAL
            jurisprudence_strength = self._infer_strength_from_real_matches(real_matches)
        elif legacy_matches:
            relevant_cases = [
                self._from_retrieved_match(item, source_mode=SOURCE_MODE_LEGACY)
                for item in legacy_matches
            ]
            source_mode_summary = self._build_retrieved_summary(legacy_matches, retrieval, real=False)
            source_quality = SOURCE_QUALITY_LEGACY
            jurisprudence_strength = JURISPRUDENCE_STRENGTH_WEAK
        elif self._should_use_internal_fallback(
            query=query,
            action_slug=action_slug,
            classification=cls,
            case_structure=case,
            normative_reasoning=normative,
            case_theory=theory,
            evidence_reasoning_links=evidence,
        ):
            relevant_cases = self._build_internal_profiles(action_slug)
            source_mode_summary = self._build_internal_summary(retrieval)
            source_quality = SOURCE_QUALITY_FALLBACK
            jurisprudence_strength = JURISPRUDENCE_STRENGTH_WEAK if relevant_cases else JURISPRUDENCE_STRENGTH_NONE
            used_internal_fallback = bool(relevant_cases)
        else:
            relevant_cases = []
            source_mode_summary = self._build_empty_summary(retrieval)
            source_quality = SOURCE_QUALITY_NONE
            jurisprudence_strength = JURISPRUDENCE_STRENGTH_NONE

        relevant_cases = self._enrich_cases(relevant_cases)
        highlights = self._build_highlights(relevant_cases)
        warnings = self._build_warnings(
            cases=relevant_cases,
            retrieval=retrieval,
            source_quality=source_quality,
            used_internal_fallback=used_internal_fallback,
        )
        dominant_criteria = self._dedupe([item.criterion_summary for item in relevant_cases if item.criterion_summary])
        possible_outcomes = self._dedupe([item.outcome for item in relevant_cases if item.outcome])
        strategic_implications = self._dedupe([item.strategic_use for item in relevant_cases if item.strategic_use])
        precedent_trend = self._precedent_trend(relevant_cases)
        confidence_delta = self._confidence_delta(
            precedent_trend=precedent_trend,
            source_quality=source_quality,
            jurisprudence_strength=jurisprudence_strength,
        )
        reasoning_directive = self._reasoning_directive(precedent_trend, source_quality)

        should_limit_claims = source_quality != SOURCE_QUALITY_REAL or jurisprudence_strength != JURISPRUDENCE_STRENGTH_STRONG
        should_avoid_jurisprudential_assertions = source_quality in {SOURCE_QUALITY_NONE, SOURCE_QUALITY_FALLBACK}

        return JurisprudenceAnalysisResult(
            relevant_cases=relevant_cases[:4],
            jurisprudence_highlights=highlights[:4],
            dominant_criteria=dominant_criteria[:5],
            possible_outcomes=possible_outcomes[:5],
            strategic_implications=strategic_implications[:6],
            warnings=warnings,
            confidence_score=round(self._confidence_score(relevant_cases, retrieval), 4),
            source_mode_summary=source_mode_summary,
            source_quality=source_quality,
            jurisprudence_strength=jurisprudence_strength,
            usable_real_precedents=len([item for item in relevant_cases if item.source_mode == SOURCE_MODE_RETRIEVED]),
            usable_legacy_precedents=len([item for item in relevant_cases if item.source_mode == SOURCE_MODE_LEGACY]),
            used_internal_fallback=used_internal_fallback,
            should_limit_claims=should_limit_claims,
            should_avoid_jurisprudential_assertions=should_avoid_jurisprudential_assertions,
            precedent_trend=precedent_trend,
            confidence_delta=confidence_delta,
            reasoning_directive=reasoning_directive,
        )

    build = analyze
    run = analyze

    def _from_retrieved_match(self, match: Any, *, source_mode: str) -> JurisprudenceCase:
        precedent = match.case
        return JurisprudenceCase(
            court=precedent.court,
            year=precedent.year or 0,
            case_name=precedent.case_name,
            legal_issue=precedent.legal_issue,
            decision_summary=precedent.decision_summary or precedent.summary,
            applied_articles=list(precedent.cited_rules),
            thematic_references=list(precedent.cited_rules or precedent.keywords),
            key_reasoning=precedent.criterion or precedent.key_reasoning or precedent.holding,
            outcome=precedent.outcome or precedent.strategic_use,
            source_mode=source_mode,
            source_id=precedent.id,
            source=precedent.source,
            source_url=precedent.source_url,
            chamber=precedent.chamber,
            jurisdiction=precedent.jurisdiction,
            forum=precedent.forum,
            date=precedent.date,
            case_id=precedent.case_id,
            facts_summary=precedent.facts_summary,
            holding=precedent.holding,
            topics=list(precedent.topics),
            keywords=list(precedent.keywords),
            action_slug=precedent.action_slug,
            procedural_stage=precedent.procedural_stage,
            document_type=precedent.document_type,
            dataset_kind=precedent.dataset_kind,
            strategic_value=precedent.strategic_use,
            territorial_priority=precedent.territorial_priority,
            local_practice_value=precedent.local_practice_value,
            court_level=precedent.court_level,
            redundancy_group=precedent.redundancy_group,
            practical_frequency=precedent.practical_frequency,
            local_topic_cluster=precedent.local_topic_cluster,
            retrieval_score=round(float(match.score), 4),
            matched_terms=list(match.matched_terms),
            criterion_summary=precedent.criterion,
            strategic_use=precedent.strategic_use,
        )

    def _enrich_cases(self, cases: list[JurisprudenceCase]) -> list[JurisprudenceCase]:
        enriched: list[JurisprudenceCase] = []
        for item in cases:
            if item.source_mode == SOURCE_MODE_INTERNAL:
                enriched.append(item)
                continue
            if not item.criterion_summary:
                item.criterion_summary = self._legacy_criterion(item)
            if not item.strategic_use:
                item.strategic_use = self._legacy_strategic_use(item)
            if not item.key_reasoning:
                item.key_reasoning = item.criterion_summary
            if not item.strategic_value:
                item.strategic_value = item.strategic_use
            enriched.append(item)
        return enriched

    def _build_highlights(self, cases: list[JurisprudenceCase]) -> list[JurisprudenceHighlight]:
        result: list[JurisprudenceHighlight] = []
        for item in cases:
            label = {
                SOURCE_MODE_RETRIEVED: "Precedente real recuperado",
                SOURCE_MODE_LEGACY: "Precedente legacy importado",
                SOURCE_MODE_INTERNAL: "Perfil interno de fallback",
            }[item.source_mode]
            result.append(
                JurisprudenceHighlight(
                    case_name=item.case_name,
                    court=item.court,
                    year=item.year,
                    legal_issue=item.legal_issue,
                    criterion=item.criterion_summary,
                    strategic_use=item.strategic_use,
                    applied_articles=list(item.applied_articles),
                    source_mode=item.source_mode,
                    source_label=label,
                    source_url=item.source_url,
                    retrieval_score=item.retrieval_score,
                )
            )
        return result

    def _build_retrieved_summary(
        self,
        matches: list[Any],
        retrieval: JurisprudenceRetrievalResult,
        *,
        real: bool,
    ) -> str:
        reasons = list(matches[0].reasons[:3]) if matches else []
        base = (
            "Se utilizaron precedentes reales recuperados del corpus estructurado."
            if real
            else "No hubo precedentes reales suficientes; se utilizaron precedentes legacy importados del corpus."
        )
        if reasons:
            return base + " Razones principales de recuperacion: " + "; ".join(reasons) + "."
        return base

    @staticmethod
    def _build_internal_summary(retrieval: JurisprudenceRetrievalResult) -> str:
        if not retrieval.corpus_available:
            return "No hubo corpus jurisprudencial disponible; se recurrió a perfiles internos de fallback."
        if not retrieval.corpus_loaded:
            return "El corpus disponible no contenia precedentes utilizables; se recurrió a perfiles internos de fallback."
        return "No hubo precedentes suficientemente solidos en el corpus; se recurrió de manera excepcional a perfiles internos de fallback."

    @staticmethod
    def _build_empty_summary(retrieval: JurisprudenceRetrievalResult) -> str:
        if not retrieval.corpus_available:
            return "No fue posible construir orientacion jurisprudencial porque el corpus local no estuvo disponible."
        if not retrieval.corpus_loaded:
            return "No fue posible construir orientacion jurisprudencial porque el corpus local no aporto precedentes utilizables."
        return "No hay base jurisprudencial suficiente para sostener una orientacion confiable en esta consulta."

    def _build_warnings(
        self,
        *,
        cases: list[JurisprudenceCase],
        retrieval: JurisprudenceRetrievalResult,
        source_quality: str,
        used_internal_fallback: bool,
    ) -> list[str]:
        warnings = list(retrieval.warnings)

        if not cases:
            warnings.append("No se encontraron precedentes suficientes para orientar la consulta con prudencia.")
            warnings.append("La respuesta no debe presentar criterios jurisprudenciales como base consolidada del caso.")
            return self._dedupe(warnings)

        if source_quality == SOURCE_QUALITY_FALLBACK and used_internal_fallback:
            warnings.append("Se esta usando fallback interno; no debe citarse como jurisprudencia verificable.")
            warnings.append("La salida interna es excepcional y tiene fuerza orientativa baja frente a litigacion real.")
        elif source_quality == SOURCE_QUALITY_LEGACY:
            warnings.append("La respuesta se apoya solo en precedentes legacy importados; su valor es menor que el de precedentes reales curados.")
            warnings.append("Conviene evitar afirmaciones jurisprudenciales concluyentes y reforzar la estrategia con hechos, prueba y norma positiva.")
        elif source_quality == SOURCE_QUALITY_REAL:
            if len([item for item in cases if item.source_mode == SOURCE_MODE_RETRIEVED]) < 2:
                warnings.append("Se recuperaron pocos precedentes reales; conviene tratar la orientacion como util pero no consolidada.")
        return self._dedupe(warnings)

    def _confidence_score(self, cases: list[JurisprudenceCase], retrieval: JurisprudenceRetrievalResult) -> float:
        if not cases:
            return 0.08
        real_cases = [item for item in cases if item.source_mode == SOURCE_MODE_RETRIEVED]
        legacy_cases = [item for item in cases if item.source_mode == SOURCE_MODE_LEGACY]
        internal_cases = [item for item in cases if item.source_mode == SOURCE_MODE_INTERNAL]

        if real_cases:
            avg_score = sum(item.retrieval_score for item in real_cases) / len(real_cases)
            quantity_bonus = min(0.12, 0.04 * len(real_cases))
            return min(0.9, 0.52 + avg_score * 0.30 + quantity_bonus)
        if legacy_cases:
            avg_score = sum(item.retrieval_score for item in legacy_cases) / len(legacy_cases)
            return min(0.5, 0.24 + avg_score * 0.18)
        if internal_cases:
            return 0.18
        return 0.08

    def _precedent_trend(self, cases: list[JurisprudenceCase]) -> str:
        if not cases:
            return "neutral"
        favorable = 0
        adverse = 0
        for item in cases:
            orientation = self._case_orientation(item)
            if orientation == "favorable":
                favorable += 1
            elif orientation == "adverse":
                adverse += 1
        if favorable > adverse:
            return "favorable"
        if adverse > favorable:
            return "adverse"
        return "neutral"

    def _case_orientation(self, case: JurisprudenceCase) -> str:
        text = " ".join(
            [
                str(case.outcome or ""),
                str(case.strategic_use or ""),
                str(case.decision_summary or ""),
                str(case.criterion_summary or ""),
            ]
        ).casefold()
        favorable_terms = ("hace lugar", "admite", "procede", "otorga", "concede", "favorable", "habilita")
        adverse_terms = ("rechaza", "desestima", "improcedente", "inadmisible", "deniega", "limita", "desfavorable")
        favorable_hits = sum(1 for term in favorable_terms if term in text)
        adverse_hits = sum(1 for term in adverse_terms if term in text)
        if favorable_hits > adverse_hits:
            return "favorable"
        if adverse_hits > favorable_hits:
            return "adverse"
        return "neutral"

    def _confidence_delta(
        self,
        *,
        precedent_trend: str,
        source_quality: str,
        jurisprudence_strength: str,
    ) -> float:
        if precedent_trend == "neutral":
            return 0.0
        quality_weight = {
            SOURCE_QUALITY_REAL: 1.0,
            SOURCE_QUALITY_LEGACY: 0.6,
            SOURCE_QUALITY_FALLBACK: 0.0,
            SOURCE_QUALITY_NONE: 0.0,
        }.get(source_quality, 0.0)
        strength_weight = {
            JURISPRUDENCE_STRENGTH_STRONG: 1.0,
            JURISPRUDENCE_STRENGTH_MODERATE: 0.7,
            JURISPRUDENCE_STRENGTH_WEAK: 0.4,
            JURISPRUDENCE_STRENGTH_NONE: 0.0,
        }.get(jurisprudence_strength, 0.0)
        base = round(0.06 * quality_weight * strength_weight, 4)
        if precedent_trend == "favorable":
            return base
        return round(-min(base, 0.04), 4)

    @staticmethod
    def _reasoning_directive(precedent_trend: str, source_quality: str) -> str:
        if source_quality not in {SOURCE_QUALITY_REAL, SOURCE_QUALITY_LEGACY}:
            return ""
        if precedent_trend == "favorable":
            return "Los precedentes recuperados permiten sostener el razonamiento con mayor confianza."
        if precedent_trend == "adverse":
            return "Los precedentes recuperados introducen cautela y obligan a acotar el alcance del razonamiento."
        return "La jurisprudencia recuperada orienta el enfoque, pero no altera de manera clara la direccion del razonamiento."

    def _infer_strength_from_real_matches(self, real_matches: list[Any]) -> str:
        if not real_matches:
            return JURISPRUDENCE_STRENGTH_NONE
        top_score = float(real_matches[0].score)
        count = len(real_matches)
        if count >= 2 and top_score >= 0.52:
            return JURISPRUDENCE_STRENGTH_STRONG
        if top_score >= 0.40:
            return JURISPRUDENCE_STRENGTH_MODERATE
        return JURISPRUDENCE_STRENGTH_WEAK

    def _should_use_internal_fallback(
        self,
        *,
        query: str,
        action_slug: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        case_theory: dict[str, Any],
        evidence_reasoning_links: dict[str, Any],
    ) -> bool:
        if not action_slug:
            return False
        if action_slug not in self._structured_profiles:
            return False

        query_terms = len(str(query or "").split())
        has_structural_context = any(
            bool(source)
            for source in (
                classification,
                case_structure,
                normative_reasoning,
                case_theory,
                evidence_reasoning_links,
            )
        )
        has_min_classification = bool(classification.get("action_slug") or classification.get("topic") or classification.get("forum"))
        return query_terms >= 2 and (has_structural_context or has_min_classification)

    def _legacy_criterion(self, case: JurisprudenceCase) -> str:
        for candidate in (case.holding, case.key_reasoning, case.decision_summary):
            cleaned = self._clean_case_text(candidate)
            if cleaned and 12 <= len(cleaned.split()) <= 40:
                return cleaned
        return ""

    def _legacy_strategic_use(self, case: JurisprudenceCase) -> str:
        for candidate in (case.strategic_value, case.outcome):
            cleaned = self._clean_case_text(candidate, max_len=220)
            if cleaned:
                return cleaned
        return ""

    def _build_internal_profiles(self, action_slug: str) -> list[JurisprudenceCase]:
        return [item.to_case(action_slug=action_slug) for item in self._structured_profiles.get(action_slug, [])]

    @classmethod
    def _build_structured_profiles(cls) -> dict[str, list[StructuredInternalProfile]]:
        return {
            "divorcio": [
                StructuredInternalProfile(
                    profile_label="Perfil interno de familia",
                    profile_revision=1,
                    profile_name="Perfil interno sobre divorcio incausado",
                    legal_issue="Procedencia del divorcio cuando los efectos accesorios se discuten separadamente.",
                    criterion="La voluntad de divorciarse permite decretar el divorcio aunque algunos efectos accesorios requieran tratamiento posterior por carriles separados.",
                    strategic_use="Solo orienta la organizacion del planteo y la separacion entre decision principal y efectos accesorios cuando faltan precedentes reales utilizables.",
                    thematic_references=["divorcio", "efectos accesorios"],
                )
            ],
            "alimentos_hijos": [
                StructuredInternalProfile(
                    profile_label="Perfil interno de familia",
                    profile_revision=1,
                    profile_name="Perfil interno sobre alimentos de hijos",
                    legal_issue="Fijacion provisoria de alimentos con prueba inicial de necesidades.",
                    criterion="La cuota provisoria puede habilitarse cuando las necesidades del hijo estan acreditadas y la prueba economica completa aun no se produjo.",
                    strategic_use="Solo orienta la priorizacion de hechos, necesidades y capacidad economica cuando el corpus real no ofrece precedentes suficientes.",
                    thematic_references=["alimentos", "cuota provisoria"],
                )
            ],
            "cuidado_personal": [
                StructuredInternalProfile(
                    profile_label="Perfil interno de familia",
                    profile_revision=1,
                    profile_name="Perfil interno sobre cuidado personal",
                    legal_issue="Determinacion de modalidad de cuidado segun interes superior y centro de vida.",
                    criterion="La modalidad de cuidado debe responder al interes superior, al centro de vida y a la cooperacion parental efectivamente demostrada en el caso.",
                    strategic_use="Solo orienta la focalizacion en interes superior, centro de vida y cooperacion parental cuando no hay precedentes reales recuperables.",
                    thematic_references=["cuidado personal", "centro de vida"],
                )
            ],
            "sucesion_ab_intestato": [
                StructuredInternalProfile(
                    profile_label="Perfil interno sucesorio",
                    profile_revision=1,
                    profile_name="Perfil interno sobre sucesion intestada",
                    legal_issue="Apertura sucesoria con suficiencia documental inicial.",
                    criterion="La apertura sucesoria requiere una base documental suficiente sobre fallecimiento, legitimacion hereditaria y competencia territorial.",
                    strategic_use="Solo orienta el orden de prueba documental y competencia cuando el corpus real no aporta precedentes sucesorios aprovechables.",
                    thematic_references=["sucesion", "declaratoria de herederos"],
                )
            ],
        }

    @staticmethod
    def _clean_case_text(value: str, *, max_len: int = 220) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            return ""
        text = re.sub(r"\b(?:DNI|CUIL|CUIT)\b[^,.;:]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:expte?\.?|expediente|legajo|causa)\s*(?:n[°ºo]?\.?\s*)?[\w./-]+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b\d{1,3}(?:\.\d{3}){1,3}\b", "", text)
        text = re.sub(r"\$\s*[\d\.,]+", "", text)
        text = re.sub(r"\b\d+(?:[.,]\d+)?\s*%", "", text)
        text = re.sub(r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b", "", text)
        text = re.sub(
            r"\b(?:hacer lugar|decretar|declarar|fijar|regular|imponer|intimar|ordenar|condenar)\b\s+(?:a|al|el|la|los|las|que)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\b(?:con costas|sin costas|las costas)\b[^.;]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s{2,}", " ", text).strip(" ;:-,.()\"'")
        lowered = text.casefold()
        if any(marker in lowered for marker in JurisprudenceEngine._ADMIN_MARKERS):
            return ""
        if len(text.split()) < 6:
            return ""
        if len(text) <= max_len:
            return text
        shortened = text[:max_len].rstrip(" ,;:-")
        cut = shortened.rfind(" ")
        if cut >= int(max_len * 0.6):
            shortened = shortened[:cut]
        return shortened.rstrip(" ,;:-") + "."

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

    @staticmethod
    def _coerce_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return value.to_dict()
        if hasattr(value, "__dict__"):
            return vars(value)
        return {}
