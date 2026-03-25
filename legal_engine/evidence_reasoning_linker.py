"""
AILEX -- EvidenceReasoningLinker

Conecta reglas aplicadas, requisitos normativos, hechos del caso, evidencia
disponible y evidencia faltante en una estructura unificada que muestra el
nivel de soporte probatorio de cada requisito juridico.

Funciona como capa posterior a NormativeReasoner, CaseTheoryEngine,
CaseEvaluationEngine y ConflictEvidenceEngine, y previa o paralela al
ArgumentGenerator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses de salida
# ---------------------------------------------------------------------------

@dataclass
class RequirementLink:
    source: str
    article: str
    requirement: str
    supporting_facts: list[str] = field(default_factory=list)
    evidence_available: list[str] = field(default_factory=list)
    evidence_missing: list[str] = field(default_factory=list)
    support_level: str = "bajo"
    strategic_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "article": self.article,
            "requirement": self.requirement,
            "supporting_facts": list(self.supporting_facts),
            "evidence_available": list(self.evidence_available),
            "evidence_missing": list(self.evidence_missing),
            "support_level": self.support_level,
            "strategic_note": self.strategic_note,
        }


@dataclass
class EvidenceReasoningResult:
    summary: str
    requirement_links: list[RequirementLink] = field(default_factory=list)
    globally_supported_requirements: list[str] = field(default_factory=list)
    weakly_supported_requirements: list[str] = field(default_factory=list)
    critical_evidentiary_gaps: list[str] = field(default_factory=list)
    strategic_warnings: list[str] = field(default_factory=list)
    confidence_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "requirement_links": [link.to_dict() for link in self.requirement_links],
            "globally_supported_requirements": list(self.globally_supported_requirements),
            "weakly_supported_requirements": list(self.weakly_supported_requirements),
            "critical_evidentiary_gaps": list(self.critical_evidentiary_gaps),
            "strategic_warnings": list(self.strategic_warnings),
            "confidence_score": self.confidence_score,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EvidenceReasoningLinker:
    """Vincula reglas, requisitos, hechos y evidencia en una estructura unificada."""

    def analyze(
        self,
        query: str,
        classification: Any = None,
        case_structure: Any = None,
        normative_reasoning: Any = None,
        case_theory: Any = None,
        case_evaluation: Any = None,
        conflict_evidence: Any = None,
        question_engine_result: Any = None,
    ) -> EvidenceReasoningResult:
        cls = self._coerce_dict(classification)
        case = self._coerce_dict(case_structure)
        normative = self._coerce_dict(normative_reasoning)
        theory = self._coerce_dict(case_theory)
        evaluation = self._coerce_dict(case_evaluation)
        conflict = self._coerce_dict(conflict_evidence)
        questions = self._coerce_dict(question_engine_result)

        # Extraer datos base
        applied_rules = self._extract_rules(normative)
        requirements = [str(r) for r in normative.get("requirements") or []]
        facts = [str(f) for f in case.get("facts") or []]
        evidence_available = [str(e) for e in conflict.get("critical_evidence_available") or []]
        evidence_missing = [str(e) for e in conflict.get("key_evidence_missing") or []]
        critical_questions = [str(q) for q in questions.get("critical_questions") or []]
        vulnerable_point = str(conflict.get("most_vulnerable_point") or "")
        conflict_points = [str(p) for p in theory.get("likely_points_of_conflict") or []]
        evidentiary_needs = [str(n) for n in theory.get("evidentiary_needs") or []]

        # Construir links
        links = self._build_links(
            applied_rules=applied_rules,
            requirements=requirements,
            facts=facts,
            evidence_available=evidence_available,
            evidence_missing=evidence_missing,
            critical_questions=critical_questions,
            evidentiary_needs=evidentiary_needs,
            vulnerable_point=vulnerable_point,
            conflict_points=conflict_points,
        )

        # Clasificar requisitos
        globally_supported = [
            link.requirement for link in links
            if link.support_level == "alto"
        ]
        weakly_supported = [
            link.requirement for link in links
            if link.support_level == "bajo"
        ]

        # Gaps críticos: evidencia faltante que afecta requisitos con soporte bajo
        critical_gaps = self._build_critical_gaps(links, evidence_missing)

        # Warnings estratégicos
        strategic_warnings = self._build_strategic_warnings(
            links=links,
            evaluation=evaluation,
            vulnerable_point=vulnerable_point,
            conflict_points=conflict_points,
        )

        # Confianza
        confidence = self._compute_confidence(links, evaluation)

        # Summary
        action_label = str(
            cls.get("action_label")
            or cls.get("action_slug")
            or "la consulta"
        )
        total = len(links)
        alto = len(globally_supported)
        bajo = len(weakly_supported)

        if total == 0:
            summary = (
                f"No se identificaron requisitos normativos vinculables para {action_label.lower()}. "
                "Se requiere mayor informacion para establecer la trazabilidad probatoria."
            )
        else:
            summary = (
                f"Se vincularon {total} requisitos normativos para {action_label.lower()}. "
                f"{alto} con soporte alto, {total - alto - bajo} con soporte medio y {bajo} con soporte bajo."
            )

        return EvidenceReasoningResult(
            summary=summary,
            requirement_links=links,
            globally_supported_requirements=self._dedupe(globally_supported),
            weakly_supported_requirements=self._dedupe(weakly_supported),
            critical_evidentiary_gaps=self._dedupe(critical_gaps)[:8],
            strategic_warnings=self._dedupe(strategic_warnings)[:6],
            confidence_score=round(confidence, 4),
        )

    build = analyze
    run = analyze

    # ------------------------------------------------------------------
    # Link building
    # ------------------------------------------------------------------

    def _build_links(
        self,
        applied_rules: list[dict[str, str]],
        requirements: list[str],
        facts: list[str],
        evidence_available: list[str],
        evidence_missing: list[str],
        critical_questions: list[str],
        evidentiary_needs: list[str],
        vulnerable_point: str,
        conflict_points: list[str],
    ) -> list[RequirementLink]:
        links: list[RequirementLink] = []

        paired = self._pair_rules_requirements(applied_rules, requirements)

        facts_lower = [f.lower() for f in facts]
        avail_lower = [e.lower() for e in evidence_available]
        missing_lower = [e.lower() for e in evidence_missing]
        questions_lower = [q.lower() for q in critical_questions]
        needs_lower = [n.lower() for n in evidentiary_needs]
        vulnerable_lower = vulnerable_point.lower()
        conflict_lower = [p.lower() for p in conflict_points]

        for rule, requirement in paired:
            req_lower = requirement.lower()
            req_keywords = self._extract_keywords(req_lower)

            # Hechos que soportan
            supporting = [
                facts[i] for i, fl in enumerate(facts_lower)
                if self._keyword_overlap(req_keywords, fl)
            ]

            # Evidencia disponible vinculada
            ev_avail = [
                evidence_available[i] for i, el in enumerate(avail_lower)
                if self._keyword_overlap(req_keywords, el)
            ]

            # Evidencia faltante vinculada
            ev_missing = [
                evidence_missing[i] for i, ml in enumerate(missing_lower)
                if self._keyword_overlap(req_keywords, ml)
            ]

            # Preguntas críticas como evidencia faltante adicional
            for i, ql in enumerate(questions_lower):
                if self._keyword_overlap(req_keywords, ql):
                    ev_missing.append(critical_questions[i])

            # Necesidades probatorias como evidencia faltante
            for i, nl in enumerate(needs_lower):
                if self._keyword_overlap(req_keywords, nl):
                    ev_missing.append(evidentiary_needs[i])

            ev_missing = self._dedupe(ev_missing)

            # Nivel de soporte — criterio estricto
            support_level = self._compute_support_level(
                supporting_facts=supporting,
                evidence_available=ev_avail,
                evidence_missing=ev_missing,
            )

            # Nota estratégica
            strategic_note = self._build_strategic_note(
                requirement=requirement,
                req_keywords=req_keywords,
                support_level=support_level,
                vulnerable_lower=vulnerable_lower,
                conflict_lower=conflict_lower,
            )

            links.append(RequirementLink(
                source=rule.get("source", ""),
                article=rule.get("article", ""),
                requirement=requirement,
                supporting_facts=supporting[:4],
                evidence_available=ev_avail[:4],
                evidence_missing=ev_missing[:4],
                support_level=support_level,
                strategic_note=strategic_note,
            ))

        return links

    def _pair_rules_requirements(
        self,
        applied_rules: list[dict[str, str]],
        requirements: list[str],
    ) -> list[tuple[dict[str, str], str]]:
        """Emparejar reglas con requisitos. Fallback genérico si no hay match."""
        pairs: list[tuple[dict[str, str], str]] = []

        if not applied_rules and not requirements:
            return pairs

        used_reqs: set[int] = set()

        for rule in applied_rules:
            rule_text = f"{rule.get('relevance', '')} {rule.get('effect', '')}".lower()
            rule_keywords = self._extract_keywords(rule_text)

            best_idx = -1
            best_score = 0
            for i, req in enumerate(requirements):
                if i in used_reqs:
                    continue
                score = len(rule_keywords & self._extract_keywords(req.lower()))
                if score > best_score:
                    best_score = score
                    best_idx = i

            if best_idx >= 0 and best_score > 0:
                used_reqs.add(best_idx)
                pairs.append((rule, requirements[best_idx]))
            else:
                # Crear requisito sintético desde la regla
                relevance = rule.get("relevance", "")
                effect = rule.get("effect", "")
                synthetic = relevance or effect or f"Aplicacion del art. {rule.get('article', '?')} de {rule.get('source', '?')}."
                pairs.append((rule, synthetic))

        # Requisitos sobrantes sin regla específica
        for i, req in enumerate(requirements):
            if i not in used_reqs:
                pairs.append(({"source": "", "article": ""}, req))

        return pairs

    # ------------------------------------------------------------------
    # Support level — criterio estricto
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_support_level(
        supporting_facts: list[str],
        evidence_available: list[str],
        evidence_missing: list[str],
    ) -> str:
        """
        Calcula el nivel de soporte probatorio de un requisito.

        Criterio estricto:
        - "alto": hechos concretos Y evidencia disponible, sin gaps significativos
        - "medio": algún hecho o evidencia, pero con gaps relevantes
        - "bajo": sin hechos ni evidencia vinculada, o gaps mayores que soporte

        La mera existencia de una norma aplicable NO equivale a soporte.
        """
        n_facts = len(supporting_facts)
        n_evidence = len(evidence_available)
        n_missing = len(evidence_missing)

        total_support = n_facts + n_evidence

        # Sin hechos ni evidencia → siempre bajo
        if total_support == 0:
            return "bajo"

        # Tiene soporte pero los gaps son iguales o mayores → medio como máximo
        if n_missing >= total_support:
            return "medio"

        # Tiene hechos Y evidencia, con gaps menores al soporte → alto
        if n_facts > 0 and n_evidence > 0 and n_missing < total_support:
            return "alto"

        # Solo hechos O solo evidencia, sin gaps → medio
        # (necesita ambos para ser "alto")
        if n_missing == 0:
            return "medio"

        # Solo hechos O solo evidencia, con gaps → medio si gaps < soporte, bajo si no
        if n_missing < total_support:
            return "medio"

        return "bajo"

    # ------------------------------------------------------------------
    # Strategic note
    # ------------------------------------------------------------------

    @staticmethod
    def _build_strategic_note(
        requirement: str,
        req_keywords: set[str],
        support_level: str,
        vulnerable_lower: str,
        conflict_lower: list[str],
    ) -> str:
        # Si el punto vulnerable del ConflictEvidenceEngine toca este requisito
        if req_keywords and any(kw in vulnerable_lower for kw in req_keywords):
            return (
                "Este requisito coincide con el punto mas vulnerable del caso. "
                "Reforzar prueba antes de presentar."
            )

        # Si un punto de conflicto toca este requisito
        for cp in conflict_lower:
            if any(kw in cp for kw in req_keywords):
                return (
                    "Punto de conflicto identificado sobre este requisito. "
                    "Preparar respuesta frente a posible contradiccion."
                )

        if support_level == "bajo":
            return "No se identificaron hechos ni prueba que sostengan este requisito. Priorizar su acreditacion."
        if support_level == "medio":
            return "Soporte parcial. Completar prueba faltante para fortalecer la posicion."

        return "Requisito con buen nivel de soporte factico y probatorio."

    # ------------------------------------------------------------------
    # Critical gaps
    # ------------------------------------------------------------------

    @staticmethod
    def _build_critical_gaps(
        links: list[RequirementLink],
        evidence_missing: list[str],
    ) -> list[str]:
        gaps: list[str] = []

        for link in links:
            if link.support_level == "bajo":
                gaps.append(
                    f"Requisito sin soporte: {link.requirement}"
                )
            for item in link.evidence_missing:
                gaps.append(item)

        # Evidencia faltante global no vinculada a ningún link
        linked_missing = set()
        for link in links:
            for item in link.evidence_missing:
                linked_missing.add(item.lower())

        for item in evidence_missing:
            if item.lower() not in linked_missing:
                gaps.append(item)

        return gaps

    # ------------------------------------------------------------------
    # Strategic warnings
    # ------------------------------------------------------------------

    @staticmethod
    def _build_strategic_warnings(
        links: list[RequirementLink],
        evaluation: dict[str, Any],
        vulnerable_point: str,
        conflict_points: list[str],
    ) -> list[str]:
        warnings: list[str] = []

        bajo_count = sum(1 for link in links if link.support_level == "bajo")
        total = len(links)

        if total > 0 and bajo_count > total / 2:
            warnings.append(
                "La mayoria de los requisitos normativos tiene soporte probatorio bajo. "
                "Se recomienda reforzar la base factica antes de avanzar."
            )

        if bajo_count > 0 and bajo_count <= total / 2:
            warnings.append(
                f"{bajo_count} de {total} requisitos tienen soporte bajo. "
                "Evaluar si es posible acreditar los extremos faltantes."
            )

        risk_level = str(evaluation.get("legal_risk_level") or "").lower()
        if risk_level in ("alto", "critico"):
            warnings.append(
                f"El nivel de riesgo juridico es {risk_level}. "
                "Los requisitos con soporte bajo pueden ser decisivos."
            )

        if vulnerable_point:
            warnings.append(
                f"Punto vulnerable identificado: {vulnerable_point}"
            )

        for point in conflict_points[:2]:
            warnings.append(f"Punto de conflicto: {point}")

        return warnings

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_confidence(
        links: list[RequirementLink],
        evaluation: dict[str, Any],
    ) -> float:
        if not links:
            return 0.35

        scores = {"alto": 1.0, "medio": 0.6, "bajo": 0.2}
        total = sum(scores.get(link.support_level, 0.2) for link in links)
        avg = total / len(links)

        confidence = 0.3 + (avg * 0.5)

        strength = str(evaluation.get("case_strength") or "").lower()
        if strength == "fuerte":
            confidence += 0.05
        elif strength == "debil":
            confidence -= 0.05

        return max(0.2, min(0.95, confidence))

    # ------------------------------------------------------------------
    # Keyword helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extrae keywords significativas (>= 5 chars) de un texto."""
        stopwords = {
            "para", "como", "esta", "este", "esto", "esos", "esas",
            "sobre", "entre", "desde", "hasta", "donde", "quien",
            "sera", "sido", "sean", "tiene", "puede", "deben",
            "debe", "caso", "ante", "toda", "todo", "solo",
            "otro", "otra", "otros", "otras", "cual", "cuando",
            "cada", "ambos", "ambas", "mismo", "misma", "algunos",
            "forma", "base", "segun", "respecto", "aplicacion",
            "mediante", "conforme", "acuerdo", "efecto", "efectos",
        }
        words = set(text.split())
        return {w for w in words if len(w) >= 5 and w not in stopwords}

    @staticmethod
    def _keyword_overlap(keywords: set[str], text: str) -> bool:
        """Devuelve True si al menos una keyword aparece en el texto."""
        if not keywords:
            return False
        return any(kw in text for kw in keywords)

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

    @staticmethod
    def _extract_rules(normative: dict[str, Any]) -> list[dict[str, str]]:
        """Extrae reglas aplicadas como lista de dicts normalizados."""
        raw = normative.get("applied_rules") or []
        rules: list[dict[str, str]] = []
        for item in raw:
            if isinstance(item, dict):
                rules.append({
                    "source": str(item.get("source") or ""),
                    "article": str(item.get("article") or ""),
                    "relevance": str(item.get("relevance") or ""),
                    "effect": str(item.get("effect") or ""),
                })
        return rules
