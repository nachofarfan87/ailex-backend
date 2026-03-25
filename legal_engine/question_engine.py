"""
AILEX -- QuestionEngine

Genera preguntas de aclaracion y completitud juridica a partir del estado del
pipeline. Usa faltantes, riesgos, requisitos y cuestiones no resueltas para
producir preguntas priorizadas y serializables.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class QuestionItem:
    question: str
    purpose: str
    priority: str
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "purpose": self.purpose,
            "priority": self.priority,
            "category": self.category,
        }


@dataclass
class QuestionEngineResult:
    summary: str
    questions: list[QuestionItem] = field(default_factory=list)
    critical_questions: list[str] = field(default_factory=list)
    confidence_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "questions": [item.to_dict() for item in self.questions],
            "critical_questions": list(self.critical_questions),
            "confidence_score": self.confidence_score,
        }


_QuestionHandler = Callable[
    [str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    QuestionEngineResult,
]


def _normalise(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(text or "").casefold())
    return " ".join("".join(ch for ch in nfkd if not unicodedata.combining(ch)).split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _priority_order(priority: str) -> int:
    return {"alta": 0, "media": 1, "baja": 2}.get(priority, 3)


class QuestionEngine:
    def __init__(self) -> None:
        self._registry: dict[str, _QuestionHandler] = {
            "divorcio_mutuo_acuerdo": self._build_divorcio_mutuo_acuerdo_questions,
            "divorcio": self._build_divorcio_questions,
            "divorcio_unilateral": self._build_divorcio_unilateral_questions,
            "alimentos_hijos": self._build_alimentos_hijos_questions,
            "sucesion_ab_intestato": self._build_sucesion_ab_intestato_questions,
        }

    def generate(
        self,
        query: str,
        classification: Any = None,
        case_structure: Any = None,
        normative_reasoning: Any = None,
        procedural_strategy: Any = None,
    ) -> QuestionEngineResult:
        cls = self._coerce_dict(classification)
        case = self._coerce_dict(case_structure)
        normative = self._coerce_dict(normative_reasoning)
        procedural = self._coerce_dict(procedural_strategy)
        action_slug = str(cls.get("action_slug") or "generic")
        handler = self._registry.get(action_slug, self._build_generic_questions)
        return handler(query, cls, case, normative, procedural)

    run = generate

    def _build_divorcio_mutuo_acuerdo_questions(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> QuestionEngineResult:
        questions = self._build_questions_for_categories(
            query=query,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            category_specs=[
                (
                    "hijos_menores",
                    "¿Existen hijos menores de edad o con capacidad restringida y cómo acuerdan su cuidado, comunicación y alimentos?",
                    "Definir si el convenio debe incluir un plan de parentalidad completo.",
                    "alta",
                    ("hijos", "menores", "capacidad restringida", "parentalidad"),
                ),
                (
                    "bienes_gananciales",
                    "¿Hay bienes gananciales, deudas comunes o vivienda familiar que deban distribuirse o atribuirse?",
                    "Precisar el alcance patrimonial del convenio regulador.",
                    "alta",
                    ("bienes", "gananciales", "patrimonial", "vivienda"),
                ),
                (
                    "convenio_regulador",
                    "¿Ya cuentan con un convenio o propuesta reguladora que detalle vivienda, bienes, alimentos y demas efectos del divorcio?",
                    "Verificar el requisito de admisibilidad de la presentacion conjunta.",
                    "alta",
                    ("propuesta reguladora", "convenio regulador", "convenio"),
                ),
                (
                    "alimentos",
                    "¿Se pactaron alimentos entre conyuges o para los hijos, con monto, modalidad de pago y gastos extraordinarios?",
                    "Evitar omisiones en uno de los efectos esenciales del divorcio.",
                    "alta",
                    ("alimentos", "cuota alimentaria"),
                ),
                (
                    "compensacion_economica",
                    "¿Alguno de los conyuges reclama o renuncia expresamente a una compensacion economica?",
                    "Definir si corresponde incorporar o descartar ese punto en el acuerdo.",
                    "media",
                    ("compensacion economica", "desequilibrio"),
                ),
                (
                    "competencia_domicilio",
                    "¿Cual fue el ultimo domicilio conyugal y cual es el domicilio actual de cada parte para definir la competencia judicial?",
                    "Confirmar el juzgado competente antes de presentar la peticion.",
                    "alta",
                    ("domicilio", "competencia", "ultimo domicilio conyugal"),
                ),
            ],
        )
        return self._build_result(
            summary="Se generaron preguntas clave para completar un divorcio por mutuo acuerdo.",
            questions=questions,
            supported=True,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
        )

    def _build_divorcio_unilateral_questions(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> QuestionEngineResult:
        _ = classification
        questions = self._build_questions_for_categories(
            query=query,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            category_specs=[
                (
                    "domicilio_conyuge",
                    "¿Cual es el domicilio actual del otro conyuge y cual fue el ultimo domicilio conyugal?",
                    "Asegurar competencia y notificacion validas en el inicio del divorcio unilateral.",
                    "alta",
                    ("domicilio", "competencia", "notificacion"),
                ),
                (
                    "propuesta_reguladora",
                    "¿Que propuesta reguladora inicial se presentara sobre vivienda, bienes, alimentos y cuidado de hijos?",
                    "Evitar que la peticion unilateral sea observada por insuficiencia regulatoria.",
                    "alta",
                    ("propuesta reguladora", "convenio regulador", "efectos del divorcio"),
                ),
                (
                    "hijos_menores",
                    "¿Existen hijos menores o con capacidad restringida y que medida se propone sobre cuidado, comunicacion y alimentos?",
                    "Determinar si hay efectos familiares inmediatos que requieren regulacion especifica.",
                    "alta",
                    ("hijos", "menores", "parentalidad", "alimentos"),
                ),
                (
                    "vivienda_bienes",
                    "¿Como esta compuesta la vivienda familiar, los bienes gananciales y las deudas comunes?",
                    "Delimitar los puntos de conflicto patrimonial mas probables.",
                    "media",
                    ("vivienda", "bienes", "gananciales", "deudas"),
                ),
                (
                    "medidas_provisionales",
                    "¿Hace falta pedir medidas provisionales sobre vivienda, cuidado, comunicacion o alimentos mientras tramite el divorcio?",
                    "Detectar urgencias que no conviene postergar al momento del inicio.",
                    "media",
                    ("medidas provisionales", "urgencia", "alimentos provisorios"),
                ),
                (
                    "compensacion_economica",
                    "¿Alguno de los conyuges podria reclamar compensacion economica por desequilibrio derivado de la ruptura?",
                    "Anticipar un reclamo economico que suele judicializarse si no se define temprano.",
                    "media",
                    ("compensacion economica", "desequilibrio"),
                ),
            ],
        )
        return self._build_result(
            summary="Se generaron preguntas clave para completar un divorcio unilateral.",
            questions=questions,
            supported=True,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
        )

    def _build_alimentos_hijos_questions(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> QuestionEngineResult:
        _ = classification
        questions = self._build_questions_for_categories(
            query=query,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            category_specs=[
                (
                    "identificacion_hijo",
                    "¿Que edad tiene el hijo y con quien convive actualmente?",
                    "Definir legitimacion, necesidades alimentarias y modalidad de cuidado.",
                    "alta",
                    ("edad", "hijo", "convive", "cuidado"),
                ),
                (
                    "gastos_hijo",
                    "¿Que gastos concretos de salud, educacion, vivienda, alimentacion y cuidado tiene hoy el hijo?",
                    "Sostener el monto de la cuota alimentaria con base economica concreta.",
                    "alta",
                    ("gastos", "salud", "educacion", "vivienda", "cuidado"),
                ),
                (
                    "ingresos_demandado",
                    "¿Que datos existen sobre ingresos, trabajo, bienes o capacidad economica del progenitor incumplidor?",
                    "Fortalecer la cuantificacion de la cuota y eventuales medidas de aseguramiento.",
                    "alta",
                    ("ingresos", "capacidad economica", "trabajo", "bienes"),
                ),
                (
                    "deuda_retroactividad",
                    "¿Desde cuando no paga alimentos, hubo pagos parciales o intimaciones previas?",
                    "Evaluar deuda acumulada y posible retroactividad del reclamo.",
                    "alta",
                    ("retroactividad", "deuda", "intimacion", "pagos parciales"),
                ),
                (
                    "cuota_provisoria",
                    "¿La situacion requiere pedir una cuota alimentaria provisoria o medidas cautelares de cobro?",
                    "Detectar si la urgencia del caso exige tutela inmediata.",
                    "media",
                    ("cuota provisoria", "medidas de aseguramiento", "cautelar"),
                ),
                (
                    "acuerdos_previos",
                    "¿Existe algun acuerdo previo, sentencia o expediente anterior sobre alimentos o cuidado personal?",
                    "Evitar omitir antecedentes que cambian la estrategia y la prueba.",
                    "media",
                    ("acuerdo", "sentencia", "expediente", "antecedente"),
                ),
            ],
        )
        return self._build_result(
            summary="Se generaron preguntas clave para completar un reclamo de alimentos a favor de hijos.",
            questions=questions,
            supported=True,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
        )

    def _build_sucesion_ab_intestato_questions(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> QuestionEngineResult:
        _ = classification
        questions = self._build_questions_for_categories(
            query=query,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            category_specs=[
                (
                    "fallecimiento",
                    "¿Cual fue la fecha y lugar de fallecimiento del causante y ya cuentan con partida de defuncion?",
                    "Habilitar la apertura de la sucesion con documentacion basica suficiente.",
                    "alta",
                    ("fallecimiento", "defuncion", "partida"),
                ),
                (
                    "competencia_sucesoria",
                    "¿Cual fue el ultimo domicilio real del causante?",
                    "Definir competencia territorial del sucesorio.",
                    "alta",
                    ("domicilio", "competencia", "causante"),
                ),
                (
                    "herederos",
                    "¿Quienes son todos los herederos posibles y cual era el estado civil del causante al fallecer?",
                    "Evitar omisiones que demoren la declaratoria de herederos.",
                    "alta",
                    ("herederos", "conyuge", "estado civil"),
                ),
                (
                    "testamento",
                    "¿Saben si existe testamento, convenio sucesorio o algun acto de ultima voluntad relevante?",
                    "Confirmar que el tramite corresponde efectivamente como sucesion ab intestato.",
                    "media",
                    ("testamento", "ultima voluntad", "ab intestato"),
                ),
                (
                    "acervo_bienes",
                    "¿Que bienes, cuentas, inmuebles, automotores o deudas integran preliminarmente el acervo hereditario?",
                    "Ordenar la utilidad practica del proceso sucesorio desde su apertura.",
                    "media",
                    ("bienes", "inmuebles", "automotores", "cuentas", "deudas"),
                ),
                (
                    "documentacion_vinculo",
                    "¿Cuentan con partidas y documentos que acrediten el parentesco de cada heredero?",
                    "Reducir observaciones al pedir declaratoria de herederos.",
                    "alta",
                    ("partidas", "parentesco", "vinculo"),
                ),
            ],
        )
        return self._build_result(
            summary="Se generaron preguntas clave para completar una sucesion ab intestato.",
            questions=questions,
            supported=True,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
        )

    def _build_generic_questions(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> QuestionEngineResult:
        _ = query
        action_label = str(classification.get("action_label") or "consulta juridica")
        questions: list[QuestionItem] = []
        for item in self._collect_signal_items(case_structure, normative_reasoning, procedural_strategy)[:8]:
            questions.append(
                QuestionItem(
                    question=self._generic_question_from_issue(item["text"]),
                    purpose=item["purpose"],
                    priority=item["priority"],
                    category=item["category"],
                )
            )

        if not questions:
            questions = [
                QuestionItem(
                    question="¿Cuales son los hechos concretos, las fechas y las personas involucradas?",
                    purpose="Obtener una base factica util para encuadrar la consulta.",
                    priority="alta",
                    category="hechos_relevantes",
                ),
                QuestionItem(
                    question="¿Existe documentacion, expediente o actuacion previa vinculada al caso?",
                    purpose="Identificar respaldo documental y antecedentes.",
                    priority="media",
                    category="documentacion",
                ),
            ]

        return self._build_result(
            summary=f"Se aplico el fallback generico para {action_label.lower()}.",
            questions=questions,
            supported=False,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
        )

    def _build_questions_for_categories(
        self,
        query: str,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        category_specs: list[tuple[str, str, str, str, tuple[str, ...]]],
    ) -> list[QuestionItem]:
        combined_text = self._build_combined_text(query, case_structure, normative_reasoning, procedural_strategy)
        signals = self._collect_signals(case_structure, normative_reasoning, procedural_strategy)
        questions: list[QuestionItem] = []
        seen_categories: set[str] = set()

        for category, question, purpose, priority, terms in category_specs:
            should_add = _contains_any(signals, terms) or not _contains_any(combined_text, terms)
            self._add_question_if_needed(
                questions=questions,
                seen_categories=seen_categories,
                should_add=should_add,
                question=question,
                purpose=purpose,
                priority=priority,
                category=category,
            )

        for issue in normative_reasoning.get("unresolved_issues") or []:
            category = self._categorise_generic_issue(str(issue))
            if category in seen_categories:
                continue
            questions.append(
                QuestionItem(
                    question=self._generic_question_from_issue(str(issue)),
                    purpose="Resolver una cuestion detectada como pendiente en el analisis normativo.",
                    priority="media",
                    category=category,
                )
            )
            seen_categories.add(category)

        return self._sort_questions(questions)

    def _build_result(
        self,
        summary: str,
        questions: list[QuestionItem],
        supported: bool,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> QuestionEngineResult:
        ordered = self._sort_questions(questions)
        critical_questions = [item.question for item in ordered if item.priority == "alta"][:5]
        confidence_score = self._resolve_confidence(
            supported=supported,
            signal_count=len(self._collect_signal_items(case_structure, normative_reasoning, procedural_strategy)),
            question_count=len(ordered),
        )
        return QuestionEngineResult(
            summary=summary,
            questions=ordered,
            critical_questions=critical_questions,
            confidence_score=confidence_score,
        )

    def _build_divorcio_questions(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> QuestionEngineResult:
        _ = classification
        questions = self._build_questions_for_categories(
            query=query,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            category_specs=[
                (
                    "variante_divorcio",
                    "¿El otro conyuge esta de acuerdo con divorciarse o la peticion debera tramitarse unilateralmente?",
                    "Definir la variante procesal del divorcio y evitar un encuadre incompleto.",
                    "alta",
                    ("mutuo acuerdo", "presentacion conjunta", "unilateral", "otro conyuge"),
                ),
                (
                    "domicilio_competencia",
                    "¿Cual fue el ultimo domicilio conyugal y cuales son los domicilios actuales relevantes?",
                    "Determinar competencia y eventuales necesidades de notificacion.",
                    "alta",
                    ("domicilio", "competencia", "notificacion"),
                ),
                (
                    "hijos_menores",
                    "¿Existen hijos menores o con capacidad restringida y que cuestiones de cuidado, comunicacion y alimentos deben regularse?",
                    "Identificar si el divorcio involucra efectos parentales que deben ordenarse desde el inicio.",
                    "alta",
                    ("hijos", "menores", "alimentos", "cuidado"),
                ),
                (
                    "vivienda_patrimonio",
                    "¿Cual es la situacion de la vivienda familiar, los bienes gananciales, deudas comunes y eventual compensacion economica?",
                    "Delimitar los efectos patrimoniales del divorcio antes de elegir la via mas adecuada.",
                    "media",
                    ("vivienda", "bienes", "gananciales", "compensacion economica", "deudas"),
                ),
                (
                    "propuesta_reguladora",
                    "¿Ya existe una propuesta reguladora o al menos un esquema inicial sobre los efectos del divorcio?",
                    "Ordenar el contenido minimo exigible para la presentacion judicial.",
                    "alta",
                    ("propuesta reguladora", "convenio regulador", "efectos del divorcio"),
                ),
            ],
        )
        return self._build_result(
            summary="Se generaron preguntas clave para completar un divorcio sin variante procesal aun definida.",
            questions=questions,
            supported=True,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
        )

    def _collect_signals(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> str:
        values: list[str] = []
        for key in ("missing_information", "risks"):
            values.extend(str(item) for item in case_structure.get(key) or [])
        values.extend(str(item) for item in normative_reasoning.get("requirements") or [])
        values.extend(str(item) for item in normative_reasoning.get("unresolved_issues") or [])
        values.extend(str(item) for item in procedural_strategy.get("missing_information") or [])
        values.extend(str(item) for item in procedural_strategy.get("missing_info") or [])
        values.extend(str(item) for item in procedural_strategy.get("risks") or [])
        return _normalise(" ".join(values))

    def _collect_signal_items(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for text in case_structure.get("missing_information") or []:
            items.append(self._signal_item(str(text), "alta", "Completar informacion faltante del caso."))
        for text in normative_reasoning.get("requirements") or []:
            items.append(self._signal_item(str(text), "alta", "Cubrir un requisito juridico identificado por el analisis normativo."))
        for text in normative_reasoning.get("unresolved_issues") or []:
            items.append(self._signal_item(str(text), "media", "Resolver una cuestion aun no cerrada por el analisis normativo."))
        for text in case_structure.get("risks") or []:
            items.append(self._signal_item(str(text), "media", "Mitigar un riesgo detectado en la estructura del caso."))
        for text in procedural_strategy.get("missing_information") or procedural_strategy.get("missing_info") or []:
            items.append(self._signal_item(str(text), "media", "Completar datos necesarios para la estrategia procesal."))
        for text in procedural_strategy.get("risks") or []:
            items.append(self._signal_item(str(text), "baja", "Prevenir un riesgo operativo o procesal."))
        return items

    def _signal_item(self, text: str, priority: str, purpose: str) -> dict[str, str]:
        return {
            "text": text,
            "priority": priority,
            "purpose": purpose,
            "category": self._categorise_generic_issue(text),
        }

    def _build_combined_text(
        self,
        query: str,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
    ) -> str:
        parts = [query]
        for key in ("summary", "legal_issue", "main_claim", "suggested_strategy"):
            parts.append(str(case_structure.get(key) or ""))
        for key in ("facts", "missing_information", "risks"):
            parts.extend(str(item) for item in case_structure.get(key) or [])
        for key in ("summary", "requirements", "unresolved_issues"):
            value = normative_reasoning.get(key) or []
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            else:
                parts.append(str(value))
        for key in ("strategic_notes", "missing_information", "missing_info", "risks"):
            value = procedural_strategy.get(key) or []
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            else:
                parts.append(str(value))
        return _normalise(" ".join(parts))

    def _add_question_if_needed(
        self,
        questions: list[QuestionItem],
        seen_categories: set[str],
        should_add: bool,
        question: str,
        purpose: str,
        priority: str,
        category: str,
    ) -> None:
        if not should_add or category in seen_categories:
            return
        questions.append(
            QuestionItem(
                question=question,
                purpose=purpose,
                priority=priority,
                category=category,
            )
        )
        seen_categories.add(category)

    def _generic_question_from_issue(self, issue: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(issue or "")).strip(" .")
        lowered = cleaned[:1].lower() + cleaned[1:] if cleaned else cleaned
        if not lowered:
            return "¿Que dato adicional falta para completar el analisis?"
        return f"¿Podes precisar {lowered}?"

    def _categorise_generic_issue(self, issue: str) -> str:
        normalized = _normalise(issue)
        if _contains_any(normalized, ("hijos", "menores", "parentalidad", "cuidado")):
            return "hijos_menores"
        if _contains_any(normalized, ("bienes", "gananciales", "patrimonial", "vivienda", "acervo")):
            return "patrimonio"
        if _contains_any(normalized, ("alimentos", "cuota", "retroactividad")):
            return "alimentos"
        if _contains_any(normalized, ("compensacion economica", "desequilibrio")):
            return "compensacion_economica"
        if _contains_any(normalized, ("domicilio", "competencia", "juzgado")):
            return "competencia"
        if _contains_any(normalized, ("documentacion", "prueba", "partidas", "partida")):
            return "documentacion"
        if _contains_any(normalized, ("hechos", "fecha", "fallecimiento", "defuncion")):
            return "hechos_relevantes"
        if _contains_any(normalized, ("herederos", "testamento", "causante")):
            return "herederos"
        return "completitud_general"

    def _sort_questions(self, questions: list[QuestionItem]) -> list[QuestionItem]:
        return sorted(self._dedupe_questions(questions), key=lambda item: (_priority_order(item.priority), item.category, item.question))

    def _dedupe_questions(self, questions: list[QuestionItem]) -> list[QuestionItem]:
        seen: set[tuple[str, str]] = set()
        result: list[QuestionItem] = []
        for item in questions:
            key = (item.category, _normalise(item.question))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _resolve_confidence(self, supported: bool, signal_count: int, question_count: int) -> float:
        confidence = 0.72 if supported else 0.46
        confidence += min(signal_count * 0.02, 0.14)
        confidence -= min(max(question_count - 5, 0) * 0.015, 0.12)
        return round(max(0.15, min(0.95, confidence)), 4)

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
