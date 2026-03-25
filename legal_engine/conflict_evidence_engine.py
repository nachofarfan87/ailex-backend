"""
AILEX -- ConflictEvidenceEngine

Analiza el caso desde una perspectiva litigiosa y probatoria. No crea hechos
ni prueba nueva; organiza lo ya disponible y marca lo que falta para robustecer
la posicion del caso.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Palabras clave que delatan razonamiento jurídico (NO evidencia)
# ---------------------------------------------------------------------------
_JURIDICAL_KEYWORDS = (
    "norma",
    "articulo",
    "regla",
    "encuadre",
    "sustento normativo",
    "base normativa",
    "fundamento juridico",
    "regimen legal",
    "marco normativo",
)

# Palabras interrogativas en español (sin tildes para comparar normalizado)
_QUESTION_STARTERS = (
    "quien",
    "cual",
    "cuales",
    "cuanto",
    "cuantos",
    "cuanta",
    "cuantas",
    "donde",
    "cuando",
    "como",
    "por que",
    "que",
)


@dataclass
class ConflictEvidenceResult:
    core_dispute: str
    strongest_point: str
    most_vulnerable_point: str
    critical_evidence_available: list[str] = field(default_factory=list)
    key_evidence_missing: list[str] = field(default_factory=list)
    probable_counterarguments: list[str] = field(default_factory=list)
    recommended_evidence_actions: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "core_dispute": self.core_dispute,
            "strongest_point": self.strongest_point,
            "most_vulnerable_point": self.most_vulnerable_point,
            "critical_evidence_available": list(self.critical_evidence_available),
            "key_evidence_missing": list(self.key_evidence_missing),
            "probable_counterarguments": list(self.probable_counterarguments),
            "recommended_evidence_actions": list(self.recommended_evidence_actions),
            "confidence_score": self.confidence_score,
            "warnings": list(self.warnings),
        }


_ConflictHandler = Callable[
    [str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    ConflictEvidenceResult,
]


class ConflictEvidenceEngine:
    def __init__(self) -> None:
        self._registry: dict[str, _ConflictHandler] = {
            "divorcio_mutuo_acuerdo": self._build_divorcio_mutuo_acuerdo,
            "divorcio_unilateral": self._build_divorcio_unilateral,
            "divorcio": self._build_divorcio,
            "alimentos_hijos": self._build_alimentos_hijos,
            "sucesion_ab_intestato": self._build_sucesion_ab_intestato,
        }
        self._domain_registry: dict[str, _ConflictHandler] = {
            "divorcio": self._build_divorcio,
            "alimentos": self._build_alimentos_hijos,
            "conflicto_patrimonial": self._build_conflicto_patrimonial,
            "cuidado_personal": self._build_cuidado_personal,
            "regimen_comunicacional": self._build_regimen_comunicacional,
        }

    def analyze(
        self,
        query: str,
        classification: Any = None,
        case_structure: Any = None,
        normative_reasoning: Any = None,
        procedural_strategy: Any = None,
        question_engine_result: Any = None,
        case_theory: Any = None,
        case_evaluation: Any = None,
        case_domain: str | None = None,
    ) -> ConflictEvidenceResult:
        cls = self._coerce_dict(classification)
        case = self._coerce_dict(case_structure)
        normative = self._coerce_dict(normative_reasoning)
        strategy = self._coerce_dict(procedural_strategy)
        questions = self._coerce_dict(question_engine_result)
        theory = self._coerce_dict(case_theory)
        evaluation = self._coerce_dict(case_evaluation)

        action_slug = str(cls.get("action_slug") or "generic")
        resolved_domain = str(case_domain or "").strip()
        handler = self._resolve_handler(resolved_domain, action_slug)
        return handler(query, cls, case, normative, strategy, questions, theory, evaluation)

    build = analyze
    run = analyze

    # ------------------------------------------------------------------
    # Handlers por tipo de acción
    # ------------------------------------------------------------------

    def _build_divorcio_mutuo_acuerdo(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        available = self._available_evidence(
            case_structure,
            case_theory,
            defaults=[
                "Voluntad concurrente de ambas partes para disolver el vinculo.",
                "Existencia del vinculo matrimonial entre las partes.",
            ],
        )
        missing = self._key_evidence_missing(
            case_structure,
            normative_reasoning,
            question_engine_result,
            case_theory,
            case_evaluation,
            hints=[
                "Partida de matrimonio.",
                "Convenio regulador completo.",
                "Datos sobre hijos menores o plan de parentalidad.",
                "Datos sobre bienes, vivienda y deudas comunes.",
            ],
        )
        counterarguments = self._build_counterarguments(
            case_theory,
            defaults=[
                "El convenio regulador presentado es incompleto respecto de hijos o bienes.",
                "No se ha acreditado que el convenio resguarde adecuadamente los intereses de los hijos menores.",
                "La informacion patrimonial aportada no permite evaluar la equidad de la distribucion propuesta.",
            ],
        )
        actions = self._recommended_actions(
            procedural_strategy,
            missing,
            hints=[
                "Reunir convenio regulador completo y consistente.",
                "Documentar situacion patrimonial y eventual atribucion de vivienda.",
                "Acreditar datos de hijos, alimentos y esquema de cuidado si corresponde.",
            ],
        )
        return self._result(
            core_dispute="Determinacion adecuada de los efectos personales y patrimoniales del divorcio presentado en forma conjunta.",
            strongest_point="La voluntad concurrente de divorciarse reduce el conflicto sobre la disolucion del vinculo.",
            most_vulnerable_point=self._enrich_vulnerable_point(
                case_theory,
                default="La insuficiencia del convenio regulador sobre hijos, bienes o vivienda puede generar observaciones judiciales.",
            ),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=counterarguments,
            recommended_evidence_actions=actions,
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
        )

    def _build_divorcio_unilateral(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        available = self._available_evidence(
            case_structure,
            case_theory,
            defaults=[
                "Existencia de voluntad unilateral de promover el divorcio.",
                "Existencia del vinculo matrimonial.",
            ],
        )
        missing = self._key_evidence_missing(
            case_structure,
            normative_reasoning,
            question_engine_result,
            case_theory,
            case_evaluation,
            hints=[
                "Acreditacion del ultimo domicilio conyugal y domicilio actual del otro conyuge.",
                "Propuesta reguladora suficientemente detallada.",
                "Datos sobre hijos, vivienda y bienes comunes.",
                "Base documental sobre eventual compensacion economica.",
            ],
        )
        counterarguments = self._build_counterarguments(
            case_theory,
            defaults=[
                "No se ha acreditado el domicilio del demandado, lo que podria invalidar la notificacion.",
                "No existen elementos suficientes para justificar la compensacion economica solicitada.",
                "La propuesta reguladora presentada no resguarda adecuadamente los derechos de los hijos.",
                "Podria alegarse incompetencia territorial del juzgado elegido.",
            ],
        )
        actions = self._recommended_actions(
            procedural_strategy,
            missing,
            hints=[
                "Acreditar domicilio y datos utiles para notificacion valida.",
                "Fortalecer la propuesta reguladora con soporte familiar y patrimonial.",
                "Documentar situacion de hijos, vivienda y bienes antes de presentar.",
            ],
        )
        return self._result(
            core_dispute="Disolucion del vinculo sin acuerdo del otro conyuge y definicion judicial de sus efectos.",
            strongest_point="La falta de acuerdo del otro conyuge no impide juridicamente el divorcio.",
            most_vulnerable_point=self._enrich_vulnerable_point(
                case_theory,
                default="La debilidad suele estar en la notificacion y en la propuesta reguladora insuficiente.",
            ),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=counterarguments,
            recommended_evidence_actions=actions,
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
        )

    def _build_divorcio(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        available = self._available_evidence(
            case_structure,
            case_theory,
            defaults=[
                "Intencion clara de promover la disolucion del vinculo matrimonial.",
                "Existencia del vinculo matrimonial.",
            ],
        )
        missing = self._key_evidence_missing(
            case_structure,
            normative_reasoning,
            question_engine_result,
            case_theory,
            case_evaluation,
            hints=[
                "Definicion de si la via sera conjunta o unilateral.",
                "Datos sobre hijos menores, vivienda y bienes.",
                "Acreditacion del ultimo domicilio conyugal y domicilios actuales.",
            ],
        )
        counterarguments = self._build_counterarguments(
            case_theory,
            defaults=[
                "No se ha definido la via procesal, lo que podria generar una presentacion inadecuada.",
                "No se ha acreditado informacion sobre hijos, vivienda, bienes o compensacion economica.",
                "Podria alegarse incompetencia territorial por falta de acreditacion de domicilios.",
            ],
        )
        actions = self._recommended_actions(
            procedural_strategy,
            missing,
            hints=[
                "Definir la variante procesal con base en el grado de acuerdo existente.",
                "Ordenar la informacion familiar y patrimonial antes del escrito inicial.",
                "Reunir documentacion del matrimonio y domicilios relevantes.",
            ],
        )
        return self._result(
            core_dispute="Definicion de la via adecuada de divorcio y de sus efectos familiares y patrimoniales.",
            strongest_point="La intencion clara de divorciarse ya permite encuadrar juridicamente la consulta.",
            most_vulnerable_point=self._enrich_vulnerable_point(
                case_theory,
                default="No esta determinada todavia la variante procesal ni los efectos concretos del divorcio.",
            ),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=counterarguments,
            recommended_evidence_actions=actions,
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
        )

    def _build_alimentos_hijos(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        available = self._available_evidence(
            case_structure,
            case_theory,
            defaults=[
                "Existencia de obligacion alimentaria respecto del hijo.",
                "Vinculo filial invocado como base del reclamo.",
            ],
        )
        missing = self._key_evidence_missing(
            case_structure,
            normative_reasoning,
            question_engine_result,
            case_theory,
            case_evaluation,
            hints=[
                "Partida de nacimiento o acreditacion del vinculo filial.",
                "Comprobantes de gastos del hijo.",
                "Datos de ingresos, trabajo o bienes del obligado.",
                "Acreditacion de convivencia o esquema de cuidado.",
                "Documentacion de intimaciones previas y pagos parciales.",
            ],
        )
        counterarguments = self._build_counterarguments(
            case_theory,
            defaults=[
                "Los ingresos del demandado no han sido acreditados adecuadamente.",
                "Podria alegarse que ya se realizaron pagos parciales o aportes informales a favor del hijo.",
                "No existe prueba suficiente de que el monto reclamado sea proporcional a las necesidades acreditadas.",
                "No se ha acreditado el regimen de convivencia ni el aporte cotidiano del progenitor conviviente.",
            ],
        )
        actions = self._recommended_actions(
            procedural_strategy,
            missing,
            hints=[
                "Reunir comprobantes de gastos ordinarios y extraordinarios del hijo.",
                "Identificar ingresos, actividad o bienes del demandado.",
                "Acreditar convivencia y distribucion de tareas de cuidado.",
                "Documentar intimaciones previas, deuda y pagos parciales.",
            ],
        )
        return self._result(
            core_dispute="Incumplimiento de la obligacion alimentaria y determinacion de una cuota adecuada.",
            strongest_point="La obligacion alimentaria hacia el hijo tiene fuerte sustento legal.",
            most_vulnerable_point=self._enrich_vulnerable_point(
                case_theory,
                default="La debilidad suele estar en la prueba de gastos y en la acreditacion de ingresos del obligado.",
            ),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=counterarguments,
            recommended_evidence_actions=actions,
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
        )

    def _build_sucesion_ab_intestato(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        available = self._available_evidence(
            case_structure,
            case_theory,
            defaults=[
                "Fallecimiento del causante como hecho habilitante del sucesorio.",
                "Vinculo de parentesco invocado por los peticionantes.",
            ],
        )
        missing = self._key_evidence_missing(
            case_structure,
            normative_reasoning,
            question_engine_result,
            case_theory,
            case_evaluation,
            hints=[
                "Partida de defuncion del causante.",
                "Partidas o documentos de parentesco de los herederos.",
                "Acreditacion del ultimo domicilio real del causante.",
                "Informacion sobre existencia o inexistencia de testamento.",
                "Inventario preliminar de bienes, cuentas y deudas.",
            ],
        )
        counterarguments = self._build_counterarguments(
            case_theory,
            defaults=[
                "Podria alegarse la existencia de herederos no incluidos en la peticion inicial.",
                "No se ha acreditado el ultimo domicilio del causante, lo que podria invalidar la competencia territorial.",
                "Podria alegarse la existencia de testamento o acto de ultima voluntad no informado.",
                "No se ha acreditado suficientemente el vinculo hereditario de todos los presentados.",
            ],
        )
        actions = self._recommended_actions(
            procedural_strategy,
            missing,
            hints=[
                "Reunir partida de defuncion del causante.",
                "Reunir partidas de parentesco y documentacion del estado civil.",
                "Acreditar el ultimo domicilio real del causante.",
                "Armar inventario preliminar del acervo hereditario.",
            ],
        )
        return self._result(
            core_dispute="Apertura del sucesorio, identificacion de herederos y determinacion del acervo hereditario.",
            strongest_point="El fallecimiento del causante habilita la apertura de la sucesion.",
            most_vulnerable_point=self._enrich_vulnerable_point(
                case_theory,
                default="La debilidad suele estar en documentacion incompleta sobre parentesco, domicilio o bienes.",
            ),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=counterarguments,
            recommended_evidence_actions=actions,
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
        )

    def _build_conflicto_patrimonial(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        _ = query, classification
        available = self._available_evidence(
            case_structure,
            case_theory,
            defaults=[
                "Existe conflicto patrimonial concreto sobre titularidad o adjudicacion del inmueble.",
                "Hay una controversia actual sobre el origen del bien o la forma de salida patrimonial.",
            ],
        )
        missing = self._key_evidence_missing(
            case_structure,
            normative_reasoning,
            question_engine_result,
            case_theory,
            case_evaluation,
            hints=[
                "Titulo del inmueble y constancias registrales.",
                "Fecha y modo de adquisicion del bien.",
                "Documentacion sobre divorcio, acuerdo o conflicto actual.",
                "Informacion sobre herencia, compra, adjudicacion o liquidacion previa.",
            ],
        )
        counterarguments = self._build_counterarguments(
            case_theory,
            defaults=[
                "No se ha acreditado si el bien es ganancial o propio.",
                "Podria discutirse que la via elegida no corresponde sin definir origen y titularidad del inmueble.",
                "No existe base suficiente para imponer una renuncia sin acuerdo o marco patrimonial adecuado.",
            ],
        )
        actions = self._recommended_actions(
            procedural_strategy,
            missing,
            hints=[
                "Reunir titulo y estado registral del inmueble.",
                "Precisar si la salida viable es adjudicacion, liquidacion o division.",
                "Acreditar si existe acuerdo parcial o conflicto abierto con el ex conyuge.",
            ],
        )
        return self._result(
            core_dispute="Definir el encuadre patrimonial correcto del inmueble y la via adecuada para resolver la cotitularidad o adjudicacion.",
            strongest_point="La controversia patrimonial esta claramente delimitada y requiere un encuadre patrimonial especifico.",
            most_vulnerable_point=self._enrich_vulnerable_point(
                case_theory,
                default="La principal debilidad es no haber precisado aun si el bien es ganancial, propio o sujeto a reglas de condominio.",
            ),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=counterarguments,
            recommended_evidence_actions=actions,
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
        )

    def _build_cuidado_personal(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        _ = query, classification
        available = self._available_evidence(case_structure, case_theory, defaults=["Existe conflicto concreto sobre cuidado cotidiano del nino."])
        missing = self._key_evidence_missing(case_structure, normative_reasoning, question_engine_result, case_theory, case_evaluation, hints=["Constancias sobre centro de vida, rutina y cuidado actual del nino."])
        return self._result(
            core_dispute="Determinar con quien y bajo que modalidad debe quedar el cuidado personal del nino.",
            strongest_point="El conflicto principal puede delimitarse a partir del centro de vida y la organizacion actual del cuidado.",
            most_vulnerable_point=self._enrich_vulnerable_point(case_theory, default="La principal debilidad es la falta de prueba concreta sobre rutina, estabilidad y cuidados cotidianos."),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=self._build_counterarguments(case_theory, defaults=["No se ha acreditado suficientemente el centro de vida actual del nino."]),
            recommended_evidence_actions=self._recommended_actions(procedural_strategy, missing, hints=["Reunir prueba sobre escuela, salud, convivencia y tareas de cuidado."]),
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
        )

    def _build_regimen_comunicacional(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        _ = query, classification
        available = self._available_evidence(case_structure, case_theory, defaults=["Existe conflicto concreto sobre contacto o comunicacion con el nino."])
        missing = self._key_evidence_missing(case_structure, normative_reasoning, question_engine_result, case_theory, case_evaluation, hints=["Constancias de impedimentos, comunicaciones previas y rutina del nino."])
        return self._result(
            core_dispute="Restablecer o fijar un regimen comunicacional concreto y ejecutable.",
            strongest_point="La controversia sobre el contacto esta claramente delimitada y admite prueba inmediata sobre obstrucciones o rutina.",
            most_vulnerable_point=self._enrich_vulnerable_point(case_theory, default="La principal debilidad es no haber precisado frecuencia, modalidad y antecedentes del impedimento de contacto."),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=self._build_counterarguments(case_theory, defaults=["No se ha acreditado suficientemente el impedimento u obstruccion del contacto."]),
            recommended_evidence_actions=self._recommended_actions(procedural_strategy, missing, hints=["Reunir mensajes, constancias y propuesta concreta de cronograma."]),
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
        )

    def _build_generic(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
    ) -> ConflictEvidenceResult:
        action_label = str(classification.get("action_label") or classification.get("action_slug") or "la consulta")
        available = self._available_evidence(
            case_structure,
            case_theory,
            defaults=[f"Elementos facticos basicos mencionados en la consulta sobre {action_label.lower()}."],
        )
        missing = self._key_evidence_missing(
            case_structure,
            normative_reasoning,
            question_engine_result,
            case_theory,
            case_evaluation,
            hints=[
                "Hechos clave todavia no documentados.",
                "Documentacion principal de respaldo.",
                "Definicion mas precisa del objetivo juridico buscado.",
            ],
        )
        counterarguments = self._build_counterarguments(
            case_theory,
            defaults=[
                "Los hechos invocados no estan suficientemente acreditados.",
                "No existe prueba suficiente para sostener la pretension o defensa.",
                "Podria alegarse que la delimitacion del conflicto central es imprecisa.",
            ],
        )
        actions = self._recommended_actions(
            procedural_strategy,
            missing,
            hints=[
                "Ordenar cronologia, hechos y documentos disponibles.",
                "Definir que hechos pueden probarse inmediatamente y cuales requieren refuerzo.",
                "Preparar respuesta frente a objeciones previsibles sobre prueba insuficiente.",
            ],
        )
        return self._result(
            core_dispute=f"Conflicto juridico central a precisar para {action_label.lower()}.",
            strongest_point="Existe una hipotesis juridica inicial que permite orientar el analisis del caso.",
            most_vulnerable_point=self._enrich_vulnerable_point(
                case_theory,
                default="Persisten faltantes facticos y probatorios que pueden debilitar cualquier posicion definitiva.",
            ),
            critical_evidence_available=available,
            key_evidence_missing=missing,
            probable_counterarguments=counterarguments,
            recommended_evidence_actions=actions,
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
            warnings=["Se aplico handler generico de conflicto y prueba."],
        )

    def _resolve_handler(self, case_domain: str, action_slug: str) -> _ConflictHandler:
        if case_domain and case_domain != "generic" and case_domain in self._domain_registry:
            return self._domain_registry[case_domain]
        return self._registry.get(action_slug, self._build_generic)

    # ------------------------------------------------------------------
    # A. Evidencia disponible — SOLO hechos, NO razonamiento jurídico
    # ------------------------------------------------------------------

    def _available_evidence(
        self,
        case_structure: dict[str, Any],
        case_theory: dict[str, Any],
        defaults: list[str],
    ) -> list[str]:
        items: list[str] = []

        # Solo hechos detectados de case_structure
        facts = [str(item) for item in case_structure.get("facts") or []]
        factual_items = [f for f in facts if not self._is_juridical(f)]
        for fact in factual_items[:4]:
            items.append(fact)

        # key_facts_supporting del case_theory (son fácticos, no jurídicos)
        supporting = [str(item) for item in case_theory.get("key_facts_supporting") or []]
        for item in supporting[:2]:
            if not self._is_juridical(item):
                items.append(item)

        # Si no se encontró ninguna evidencia fáctica, usar defaults
        if not items:
            items.extend(defaults[:2])

        # Fallback mínimo
        if not items:
            items.append("Elementos facticos basicos mencionados en la consulta.")

        return self._dedupe_preserve_order(items)[:6]

    @staticmethod
    def _is_juridical(text: str) -> bool:
        """Devuelve True si el texto parece razonamiento jurídico, no evidencia."""
        lowered = text.lower()
        return any(kw in lowered for kw in _JURIDICAL_KEYWORDS)

    # ------------------------------------------------------------------
    # B. Evidencia faltante — normalizada, sin preguntas
    # ------------------------------------------------------------------

    def _key_evidence_missing(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        question_engine_result: dict[str, Any],
        case_theory: dict[str, Any],
        case_evaluation: dict[str, Any],
        hints: list[str],
    ) -> list[str]:
        items: list[str] = []

        # Fuentes de información faltante
        for item in case_structure.get("missing_information") or []:
            items.append(self._normalize_evidence_item(str(item)))
        for item in normative_reasoning.get("unresolved_issues") or []:
            items.append(self._normalize_evidence_item(str(item)))
        for item in question_engine_result.get("critical_questions") or []:
            items.append(self._normalize_evidence_item(str(item)))
        for item in case_theory.get("evidentiary_needs") or []:
            items.append(self._normalize_evidence_item(str(item)))

        # Transformar items de case_evaluation en acciones probatorias
        # (evitar repetir literal lo que ya dice case_evaluation)
        eval_missing = case_evaluation.get("missing_information") or case_evaluation.get("key_gaps") or []
        for item in eval_missing:
            transformed = self._transform_to_evidentiary_action(str(item))
            if transformed:
                items.append(transformed)

        items.extend(hints)
        return self._dedupe_preserve_order(items)[:8]

    @staticmethod
    def _normalize_evidence_item(text: str) -> str:
        """Convierte preguntas en formato declarativo probatorio."""
        text = text.strip()
        if not text:
            return text

        # Detectar si es una pregunta
        is_question = (
            text.startswith("¿")
            or text.endswith("?")
            or any(
                text.lower().lstrip("¿").startswith(starter)
                for starter in _QUESTION_STARTERS
            )
        )

        if not is_question:
            return text

        # Quitar signos de interrogación
        cleaned = text.replace("¿", "").replace("?", "").strip()
        cleaned = cleaned.rstrip(".")

        # Normalizar para comparación (quitar tildes comunes)
        lower = cleaned.lower()
        # Normalizar tildes para matching de patrones
        norm = lower
        for orig, repl in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")]:
            norm = norm.replace(orig, repl)

        # Patrones de transformación (sobre texto sin tildes)
        patterns = [
            (r"^(?:cual(?:es)?|que)\s+(?:es|son|fue|fueron)\s+(.+)", "Acreditacion de"),
            (r"^(?:cual(?:es)?|que)\s+(.+)", "Acreditacion de"),
            (r"^(?:cuanto|cuantos|cuanta|cuantas)\s+(.+)", "Acreditacion de"),
            (r"^(?:donde|en donde)\s+(.+)", "Acreditacion de"),
            (r"^(?:quien|quienes)\s+(.+)", "Identificacion de"),
            (r"^(?:existen?|hay)\s+(.+)", "Informacion acreditada sobre existencia de"),
            (r"^(?:se (?:ha|han))\s+(.+)", "Acreditacion de si se"),
            (r"^(?:tiene|tienen)\s+(.+)", "Acreditacion de"),
        ]

        for pattern, prefix in patterns:
            match = re.match(pattern, norm)
            if match:
                captured = match.group(match.lastindex)
                return f"{prefix} {captured}."

        # Fallback: si no matchea ningún patrón, envolver genéricamente
        return f"Acreditacion de: {lower}."

    @staticmethod
    def _transform_to_evidentiary_action(text: str) -> str:
        """Transforma un item de evaluación en acción probatoria si no es redundante."""
        text = text.strip()
        if not text:
            return ""
        lower = text.lower()
        # Evitar repetir frases genéricas de evaluación
        skip_phrases = (
            "informacion faltante significativa",
            "datos insuficientes",
            "falta de informacion",
            "informacion incompleta",
        )
        if any(phrase in lower for phrase in skip_phrases):
            return ""
        return text

    # ------------------------------------------------------------------
    # C. Contraargumentos — objeciones reales, no descripciones
    # ------------------------------------------------------------------

    def _build_counterarguments(
        self,
        case_theory: dict[str, Any],
        defaults: list[str],
    ) -> list[str]:
        """Construye contraargumentos priorizando likely_points_of_conflict."""
        items: list[str] = []

        # D. Priorizar likely_points_of_conflict del CaseTheoryEngine
        conflict_points = case_theory.get("likely_points_of_conflict") or []
        for point in conflict_points:
            objection = self._conflict_point_to_objection(str(point))
            if objection:
                items.append(objection)

        # Completar con defaults si faltan
        items.extend(defaults)

        return self._dedupe_preserve_order(items)[:6]

    @staticmethod
    def _conflict_point_to_objection(point: str) -> str:
        """Convierte un punto de conflicto en una objeción procesal real."""
        point = point.strip()
        if not point:
            return ""

        lower = point.lower()

        # Si ya suena como objeción (tiene verbos de impugnación), dejarlo
        objection_verbs = (
            "no se ha acreditado",
            "podria alegarse",
            "no existe prueba",
            "no se acredito",
            "no hay constancia",
            "resulta insuficiente",
            "no se demostro",
        )
        if any(verb in lower for verb in objection_verbs):
            return point

        # Transformar descripciones genéricas en objeciones
        if lower.startswith("conflicto sobre ") or lower.startswith("conflicto por "):
            subject = point.split(" ", 2)[-1].rstrip(".")
            return f"No se ha acreditado adecuadamente la situacion relativa a {subject.lower()}."

        if lower.startswith("discusion sobre ") or lower.startswith("discusion por "):
            subject = point.split(" ", 2)[-1].rstrip(".")
            return f"Podria alegarse que {subject.lower()} no esta suficientemente probado."

        if lower.startswith("riesgo de ") or lower.startswith("riesgo por "):
            subject = point.split(" ", 2)[-1].rstrip(".")
            return f"Podria alegarse {subject.lower()}."

        # Si es una frase corta descriptiva, envolverla como objeción
        if len(point.split()) <= 5:
            return f"Podria alegarse que {point[0].lower()}{point[1:].rstrip('.')}."

        return point

    # ------------------------------------------------------------------
    # D. Enriquecer most_vulnerable_point con likely_points_of_conflict
    # ------------------------------------------------------------------

    @staticmethod
    def _enrich_vulnerable_point(case_theory: dict[str, Any], default: str) -> str:
        """Usa el primer punto de conflicto relevante si existe."""
        conflict_points = case_theory.get("likely_points_of_conflict") or []
        if conflict_points:
            first = str(conflict_points[0]).strip()
            if first and len(first) > 10:
                return f"{default} En particular: {first.lower().rstrip('.')}."
        return default

    # ------------------------------------------------------------------
    # F. Acciones probatorias recomendadas
    # ------------------------------------------------------------------

    def _recommended_actions(
        self,
        procedural_strategy: dict[str, Any],
        key_evidence_missing: list[str],
        hints: list[str],
    ) -> list[str]:
        actions: list[str] = []
        actions.extend(str(item) for item in procedural_strategy.get("next_steps") or [])
        actions.extend(hints)

        lowered_missing = " ".join(item.lower() for item in key_evidence_missing)
        if any(term in lowered_missing for term in ("partida", "vinculo", "parentesco", "matrimonio", "nacimiento", "defuncion")):
            actions.append("Reunir partidas y documentacion registral que acrediten los vinculos invocados.")
        if any(term in lowered_missing for term in ("ingresos", "gastos", "bienes", "vivienda", "patrimonial", "inventario")):
            actions.append("Reunir comprobantes de ingresos, gastos, bienes o situacion patrimonial.")
        if any(term in lowered_missing for term in ("domicilio", "competencia", "notificacion")):
            actions.append("Acreditar domicilios con constancias objetivas antes de presentar.")

        return self._dedupe_preserve_order(actions)[:6]

    # ------------------------------------------------------------------
    # Resultado final
    # ------------------------------------------------------------------

    def _result(
        self,
        core_dispute: str,
        strongest_point: str,
        most_vulnerable_point: str,
        critical_evidence_available: list[str],
        key_evidence_missing: list[str],
        probable_counterarguments: list[str],
        recommended_evidence_actions: list[str],
        case_evaluation: dict[str, Any],
        normative_reasoning: dict[str, Any],
        warnings: list[str] | None = None,
    ) -> ConflictEvidenceResult:
        warnings_list = list(warnings or [])
        confidence = self._confidence_score(
            case_evaluation=case_evaluation,
            normative_reasoning=normative_reasoning,
            key_evidence_missing=key_evidence_missing,
        )
        if len(key_evidence_missing) > 5:
            warnings_list.append("La prueba faltante relevante todavia es amplia.")
        if len(normative_reasoning.get("unresolved_issues") or []) > 3:
            warnings_list.append("Persisten cuestiones normativas sin resolver que pueden impactar la prueba.")

        return ConflictEvidenceResult(
            core_dispute=core_dispute,
            strongest_point=strongest_point,
            most_vulnerable_point=most_vulnerable_point,
            critical_evidence_available=self._dedupe_preserve_order(critical_evidence_available)[:6],
            key_evidence_missing=self._dedupe_preserve_order(key_evidence_missing)[:8],
            probable_counterarguments=self._dedupe_preserve_order(probable_counterarguments)[:6],
            recommended_evidence_actions=self._dedupe_preserve_order(recommended_evidence_actions)[:6],
            confidence_score=round(confidence, 4),
            warnings=self._dedupe_preserve_order(warnings_list),
        )

    def _confidence_score(
        self,
        case_evaluation: dict[str, Any],
        normative_reasoning: dict[str, Any],
        key_evidence_missing: list[str],
    ) -> float:
        score = 0.72
        if str(case_evaluation.get("case_strength") or "").strip().lower() == "fuerte":
            score += 0.05
        if len(normative_reasoning.get("applied_rules") or []) > 4:
            score += 0.03
        if len(normative_reasoning.get("unresolved_issues") or []) > 3:
            score -= 0.05
        if len(key_evidence_missing) > 5:
            score -= 0.05
        return max(0.25, min(0.95, score))

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
