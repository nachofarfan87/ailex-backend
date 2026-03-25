"""
AILEX -- CaseEvaluationEngine

Evalua estrategicamente el estado consolidado del caso sin reemplazar ningun
modulo previo del pipeline. Toma senales de clasificacion, estructura,
razonamiento normativo, estrategia procesal, teoria del caso y preguntas
pendientes para producir una lectura sintetica de fortaleza, riesgo e
incertidumbre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CaseEvaluationResult:
    case_strength: str
    legal_risk_level: str
    uncertainty_level: str
    strength_score: float
    risk_score: float
    uncertainty_score: float
    strategic_observations: list[str] = field(default_factory=list)
    possible_scenarios: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_strength": self.case_strength,
            "legal_risk_level": self.legal_risk_level,
            "uncertainty_level": self.uncertainty_level,
            "strength_score": self.strength_score,
            "risk_score": self.risk_score,
            "uncertainty_score": self.uncertainty_score,
            "strategic_observations": list(self.strategic_observations),
            "possible_scenarios": list(self.possible_scenarios),
            "warnings": list(self.warnings),
        }


_ScenarioHandler = Callable[
    [str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    list[str],
]


class CaseEvaluationEngine:
    _CRITICAL_TERMS: tuple[str, ...] = (
        "competencia",
        "domicilio",
        "legitimacion",
        "partida",
        "vinculo",
        "notificacion",
        "prescripcion",
        "caducidad",
        "violencia",
        "riesgo",
        "ingresos",
        "prueba",
    )

    def __init__(self) -> None:
        self._scenario_registry: dict[str, _ScenarioHandler] = {
            "divorcio_mutuo_acuerdo": self._scenarios_divorcio_mutuo_acuerdo,
            "divorcio_unilateral": self._scenarios_divorcio_unilateral,
            "alimentos_hijos": self._scenarios_alimentos_hijos,
            "sucesion_ab_intestato": self._scenarios_sucesion_ab_intestato,
        }
        self._domain_registry: dict[str, _ScenarioHandler] = {
            "divorcio": self._scenarios_divorcio_unilateral,
            "alimentos": self._scenarios_alimentos_hijos,
            "conflicto_patrimonial": self._scenarios_conflicto_patrimonial,
            "cuidado_personal": self._scenarios_cuidado_personal,
            "regimen_comunicacional": self._scenarios_regimen_comunicacional,
        }

    def evaluate(
        self,
        query: str,
        classification: Any = None,
        case_structure: Any = None,
        normative_reasoning: Any = None,
        procedural_strategy: Any = None,
        case_theory: Any = None,
        question_engine_result: Any = None,
        case_domain: str | None = None,
    ) -> CaseEvaluationResult:
        cls = self._coerce_dict(classification)
        case = self._coerce_dict(case_structure)
        normative = self._coerce_dict(normative_reasoning)
        strategy = self._coerce_dict(procedural_strategy)
        theory = self._coerce_dict(case_theory)
        questions = self._coerce_dict(question_engine_result)

        strength_score = self._strength_score(cls, case, normative, questions)
        risk_score = self._risk_score(case, normative, questions)
        uncertainty_score = self._uncertainty_score(case, normative, questions)

        action_slug = str(cls.get("action_slug") or "generic")
        resolved_domain = str(case_domain or "").strip()
        scenario_handler = self._resolve_handler(resolved_domain, action_slug)
        possible_scenarios = self._dedupe_preserve_order(
            scenario_handler(query, cls, case, normative, strategy, theory, questions)
        )[:5]

        strategic_observations = self._build_observations(case, normative, strategy, theory, questions)
        warnings = self._build_warnings(case, normative, questions, action_slug, resolved_domain)

        return CaseEvaluationResult(
            case_strength=self._strength_label(strength_score),
            legal_risk_level=self._risk_label(risk_score),
            uncertainty_level=self._uncertainty_label(uncertainty_score),
            strength_score=round(strength_score, 4),
            risk_score=round(risk_score, 4),
            uncertainty_score=round(uncertainty_score, 4),
            strategic_observations=strategic_observations,
            possible_scenarios=possible_scenarios,
            warnings=warnings,
        )

    analyze = evaluate
    run = evaluate

    def _strength_score(
        self,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> float:
        cls_score = float(classification.get("confidence_score") or 0.0)
        rule_count = len(normative_reasoning.get("applied_rules") or [])
        fact_count = len(case_structure.get("facts") or [])
        unresolved_count = len(normative_reasoning.get("unresolved_issues") or [])
        missing_count = len(case_structure.get("missing_information") or [])
        critical_question_count = len(question_engine_result.get("critical_questions") or [])
        risks_count = len(case_structure.get("risks") or [])
        critical_signal_count = self._critical_signal_count(case_structure, normative_reasoning, question_engine_result)

        support = 0.24
        support += min(cls_score * 0.18, 0.18)
        support += min(rule_count * 0.03, 0.18)
        support += min(fact_count * 0.025, 0.15)

        penalty = 0.0
        penalty += min(unresolved_count * 0.035, 0.18)
        penalty += min(missing_count * 0.03, 0.15)
        penalty += min(critical_question_count * 0.035, 0.18)
        penalty += min(risks_count * 0.05, 0.22)
        penalty += min(critical_signal_count * 0.045, 0.18)

        if risks_count >= 3 and unresolved_count >= 2:
            penalty += 0.08
        if critical_signal_count >= 2 and missing_count >= 2:
            penalty += 0.10
        if critical_question_count >= 3:
            penalty += 0.06

        return self._clamp(support - penalty + 0.22)

    def _risk_score(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> float:
        risks_count = len(case_structure.get("risks") or [])
        unresolved_count = len(normative_reasoning.get("unresolved_issues") or [])
        critical_count = len(question_engine_result.get("critical_questions") or [])

        critical_signal_count = self._critical_signal_count(case_structure, normative_reasoning, question_engine_result)

        score = 0.14
        score += min(risks_count * 0.11, 0.44)
        score += min(unresolved_count * 0.07, 0.21)
        score += min(critical_count * 0.04, 0.16)
        score += min(critical_signal_count * 0.06, 0.18)
        if risks_count >= 3:
            score += 0.08
        if risks_count >= 2 and critical_signal_count >= 2:
            score += 0.10
        if unresolved_count >= 3 and critical_count >= 2:
            score += 0.07
        return self._clamp(score)

    def _uncertainty_score(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> float:
        unresolved_count = len(normative_reasoning.get("unresolved_issues") or [])
        critical_count = len(question_engine_result.get("critical_questions") or [])
        missing_count = len(case_structure.get("missing_information") or [])

        critical_signal_count = self._critical_signal_count(case_structure, normative_reasoning, question_engine_result)

        score = 0.1
        score += min(unresolved_count * 0.13, 0.39)
        score += min(critical_count * 0.09, 0.27)
        score += min(missing_count * 0.05, 0.2)
        score += min(critical_signal_count * 0.04, 0.12)
        if missing_count >= 3 and critical_count >= 2:
            score += 0.06
        return self._clamp(score)

    def _critical_signal_count(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> int:
        items = [
            *[str(item) for item in (case_structure.get("risks") or [])],
            *[str(item) for item in (case_structure.get("missing_information") or [])],
            *[str(item) for item in (normative_reasoning.get("unresolved_issues") or [])],
            *[str(item) for item in (question_engine_result.get("critical_questions") or [])],
        ]
        return sum(1 for item in items if self._contains_terms(item, self._CRITICAL_TERMS))

    def _build_observations(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        observations: list[str] = []
        missing = [str(item) for item in case_structure.get("missing_information") or []]
        risks = [str(item) for item in case_structure.get("risks") or []]
        unresolved = [str(item) for item in normative_reasoning.get("unresolved_issues") or []]
        critical_questions = [str(item) for item in question_engine_result.get("critical_questions") or []]
        evidentiary_needs = [str(item) for item in case_theory.get("evidentiary_needs") or []]

        if missing:
            observations.append("Precisar hechos clave antes de cerrar la estrategia principal.")
        if len(missing) > 2 or evidentiary_needs:
            observations.append("Reforzar prueba documental y soporte objetivo de los hechos invocados.")
        if any(self._contains_terms(item, ("domicilio", "competencia", "territorial", "juzgado")) for item in [*missing, *risks, *unresolved]):
            observations.append("Verificar competencia territorial y domicilios relevantes antes de presentar.")
        if any(self._contains_terms(item, ("cautelar", "urgencia", "provisionales", "aseguramiento", "embargo", "retencion")) for item in [*risks, *unresolved, *critical_questions]):
            observations.append("Evaluar medidas cautelares o provisorias para proteger la posicion procesal.")
        if unresolved:
            observations.append("Cerrar cuestiones normativas pendientes antes de asumir una posicion definitiva.")
        if risks:
            observations.append("Anticipar objeciones procesales y puntos de conflicto para reducir contingencias.")
        if procedural_strategy.get("next_steps"):
            observations.append("Priorizar los proximos pasos procesales ya identificados para ordenar la ejecucion.")

        return self._dedupe_preserve_order(observations)[:6]

    def _build_warnings(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        question_engine_result: dict[str, Any],
        action_slug: str,
        case_domain: str,
    ) -> list[str]:
        warnings = []
        if action_slug == "generic" and not case_domain:
            warnings.append("Se aplico evaluacion estrategica generica por falta de handler especifico.")
        if len(normative_reasoning.get("unresolved_issues") or []) > 3:
            warnings.append("El caso presenta varias cuestiones normativas sin resolver.")
        if len(question_engine_result.get("critical_questions") or []) > 3:
            warnings.append("Persisten preguntas criticas que pueden alterar la estrategia.")
        if len(case_structure.get("missing_information") or []) > 3:
            warnings.append("La informacion faltante todavia es significativa para una evaluacion estable.")
        return self._dedupe_preserve_order(warnings)

    def _scenarios_conflicto_patrimonial(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        return [
            "Acuerdo de adjudicacion o liquidacion si la titularidad y el origen del bien quedan suficientemente delimitados.",
            "Conflicto sobre ganancialidad, bien propio o fecha de adquisicion del inmueble.",
            "Necesidad de division o reglas de condominio si no hay acuerdo patrimonial.",
        ]

    def _scenarios_cuidado_personal(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        return [
            "Definicion judicial del centro de vida y modalidad de cuidado personal.",
            "Conflicto sobre aptitud cotidiana, disponibilidad y estabilidad de cada progenitor.",
            "Necesidad de complementar la decision con regimen comunicacional y alimentos.",
        ]

    def _scenarios_regimen_comunicacional(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        return [
            "Fijacion judicial de un cronograma de contacto concreto y ejecutable.",
            "Discusion sobre impedimentos u obstrucciones previas al contacto.",
            "Necesidad de medidas urgentes si el contacto esta bloqueado.",
        ]

    def _scenarios_divorcio_mutuo_acuerdo(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        return [
            "Aprobacion rapida del divorcio con homologacion del convenio.",
            "Observacion judicial del acuerdo regulador por insuficiencias o falta de precision.",
            "Conflicto sobre bienes, vivienda o compensacion economica que obligue a redefinir efectos del divorcio.",
        ]

    def _scenarios_divorcio_unilateral(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        return [
            "Sentencia de divorcio sin oposicion relevante sobre la disolucion del vinculo.",
            "Conflicto sobre efectos patrimoniales, vivienda o compensacion economica.",
            "Disputa por cuidado personal, comunicacion o alimentos respecto de hijos.",
        ]

    def _scenarios_alimentos_hijos(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        return [
            "Fijacion judicial de cuota alimentaria a favor del hijo.",
            "Discusion sobre monto, capacidad economica del obligado y alcance de gastos.",
            "Ejecucion o medidas de aseguramiento por incumplimiento de la cuota.",
        ]

    def _scenarios_sucesion_ab_intestato(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        return [
            "Declaratoria de herederos sin oposicion relevante.",
            "Aparicion de heredero omitido o cuestionamiento sobre legitimacion sucesoria.",
            "Conflicto sobre bienes, inventario o composicion del acervo hereditario.",
        ]

    def _scenarios_generic(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        case_theory: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        _ = case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        action_label = str(classification.get("action_label") or classification.get("action_slug") or "la consulta")
        return [
            f"Avance favorable si se completa la informacion necesaria para {action_label.lower()}.",
            f"Observaciones u oposiciones por insuficiencia factica o documental en {action_label.lower()}.",
            f"Necesidad de redefinir la estrategia segun evolucione la prueba y el objetivo del caso. Consulta base: {query[:80]}",
        ]

    def _resolve_handler(self, case_domain: str, action_slug: str) -> _ScenarioHandler:
        if case_domain and case_domain != "generic" and case_domain in self._domain_registry:
            return self._domain_registry[case_domain]
        return self._scenario_registry.get(action_slug, self._scenarios_generic)

    @staticmethod
    def _strength_label(score: float) -> str:
        if score < 0.35:
            return "debil"
        if score < 0.65:
            return "media"
        return "fuerte"

    @staticmethod
    def _risk_label(score: float) -> str:
        if score < 0.35:
            return "bajo"
        if score < 0.65:
            return "medio"
        return "alto"

    @staticmethod
    def _uncertainty_label(score: float) -> str:
        if score < 0.35:
            return "baja"
        if score < 0.65:
            return "media"
        return "alta"

    @staticmethod
    def _contains_terms(text: str, terms: tuple[str, ...]) -> bool:
        lowered = str(text or "").lower()
        return any(term in lowered for term in terms)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)
        return deduped

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
