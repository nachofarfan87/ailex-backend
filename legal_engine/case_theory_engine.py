"""
AILEX -- CaseTheoryEngine

Construye una teoria inicial del caso util para litigacion o asesoramiento
preliminar. Usa la clasificacion, la estructura del caso, el razonamiento
normativo, la estrategia procesal y las preguntas pendientes para organizar
hipotesis, conflicto y necesidad probatoria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CaseTheoryResult:
    summary: str
    primary_theory: str
    alternative_theories: list[str] = field(default_factory=list)
    objective: str = ""
    key_facts_supporting: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    likely_points_of_conflict: list[str] = field(default_factory=list)
    evidentiary_needs: list[str] = field(default_factory=list)
    recommended_line_of_action: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "primary_theory": self.primary_theory,
            "alternative_theories": list(self.alternative_theories),
            "objective": self.objective,
            "key_facts_supporting": list(self.key_facts_supporting),
            "missing_facts": list(self.missing_facts),
            "likely_points_of_conflict": list(self.likely_points_of_conflict),
            "evidentiary_needs": list(self.evidentiary_needs),
            "recommended_line_of_action": list(self.recommended_line_of_action),
            "confidence_score": self.confidence_score,
            "warnings": list(self.warnings),
        }


_CaseTheoryHandler = Callable[
    [str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    CaseTheoryResult,
]


class CaseTheoryEngine:
    def __init__(self) -> None:
        self._registry: dict[str, _CaseTheoryHandler] = {
            "divorcio_mutuo_acuerdo": self._build_divorcio_mutuo_acuerdo,
            "divorcio": self._build_divorcio,
            "divorcio_unilateral": self._build_divorcio_unilateral,
            "alimentos_hijos": self._build_alimentos_hijos,
            "sucesion_ab_intestato": self._build_sucesion_ab_intestato,
        }
        self._domain_registry: dict[str, _CaseTheoryHandler] = {
            "divorcio": self._build_divorcio,
            "alimentos": self._build_alimentos_hijos,
            "conflicto_patrimonial": self._build_conflicto_patrimonial,
            "cuidado_personal": self._build_cuidado_personal,
            "regimen_comunicacional": self._build_regimen_comunicacional,
        }

    def build(
        self,
        query: str,
        classification: Any = None,
        case_structure: Any = None,
        normative_reasoning: Any = None,
        procedural_strategy: Any = None,
        question_engine_result: Any = None,
        case_domain: str | None = None,
    ) -> CaseTheoryResult:
        cls = self._coerce_dict(classification)
        case = self._coerce_dict(case_structure)
        normative = self._coerce_dict(normative_reasoning)
        strategy = self._coerce_dict(procedural_strategy)
        questions = self._coerce_dict(question_engine_result)
        domain = str(case_domain or "").strip()
        action_slug = str(cls.get("action_slug") or "generic")
        handler = self._resolve_handler(domain, action_slug)
        return handler(query, cls, case, normative, strategy, questions)

    analyze = build
    run = build

    def _build_divorcio_mutuo_acuerdo(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        _ = query
        key_facts = self._merge_unique(
            list(case_structure.get("facts") or []),
            [
                "Ambos conyuges manifiestan voluntad concurrente de divorciarse.",
                "La via adecuada es la presentacion conjunta con propuesta reguladora.",
            ],
        )
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        evidentiary_needs = self._merge_unique(
            [
                "Partida de matrimonio.",
                "Convenio o propuesta reguladora.",
                "Informacion sobre hijos menores y plan de parentalidad si corresponde.",
                "Detalle patrimonial sobre bienes, vivienda y deudas.",
            ],
            self._facts_to_evidence(missing_facts),
        )
        return self._result(
            summary="Teoria inicial para divorcio por mutuo acuerdo.",
            primary_theory="Existe voluntad concurrente de ambos conyuges para disolver el vinculo matrimonial mediante presentacion conjunta.",
            alternative_theories=[
                "Si el acuerdo regulador es incompleto, el conflicto puede desplazarse a los efectos patrimoniales o parentales del divorcio.",
            ],
            objective="Obtener sentencia de divorcio con homologacion o control judicial de la propuesta reguladora.",
            key_facts_supporting=key_facts,
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Hijos menores o con capacidad restringida.",
                "Distribucion de bienes gananciales y deudas comunes.",
                "Atribucion de la vivienda familiar.",
                "Compensacion economica entre conyuges.",
            ],
            evidentiary_needs=evidentiary_needs,
            recommended_line_of_action=self._recommended_actions(
                procedural_strategy,
                fallback=[
                    "Consolidar propuesta reguladora integral.",
                    "Confirmar competencia judicial y domicilios relevantes.",
                    "Documentar situacion familiar y patrimonial antes de presentar.",
                ],
            ),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.84),
            warnings=self._warnings(case_structure, normative_reasoning),
        )

    def _build_divorcio_unilateral(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        _ = query
        key_facts = self._merge_unique(
            list(case_structure.get("facts") or []),
            [
                "Uno de los conyuges busca disolver el vinculo matrimonial.",
                "La falta de conformidad del otro conyuge no impide la procedencia del divorcio.",
            ],
        )
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        evidentiary_needs = self._merge_unique(
            [
                "Partida de matrimonio.",
                "Domicilio actual del otro conyuge y ultimo domicilio conyugal.",
                "Informacion sobre hijos, vivienda, bienes y deudas.",
                "Soporte de la propuesta reguladora inicial.",
            ],
            self._facts_to_evidence(missing_facts),
        )
        return self._result(
            summary="Teoria inicial para divorcio unilateral.",
            primary_theory="Uno de los conyuges busca disolver unilateralmente el vinculo, siendo irrelevante la falta de conformidad del otro para la procedencia del divorcio.",
            alternative_theories=[
                "La controversia principal puede concentrarse en los efectos del divorcio y no en la disolucion misma.",
                "Si existe urgencia familiar o patrimonial, puede ser necesario articular medidas provisionales.",
            ],
            objective="Promover divorcio unilateral con propuesta reguladora y resolver judicialmente los efectos controvertidos.",
            key_facts_supporting=key_facts,
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Notificacion valida del otro conyuge.",
                "Cuidado y alimentos de hijos.",
                "Atribucion de la vivienda familiar.",
                "Bienes y deudas comunes.",
                "Compensacion economica.",
            ],
            evidentiary_needs=evidentiary_needs,
            recommended_line_of_action=self._recommended_actions(
                procedural_strategy,
                fallback=[
                    "Definir propuesta reguladora inicial suficiente.",
                    "Asegurar datos de competencia y notificacion.",
                    "Preparar prueba basica sobre conflicto familiar y patrimonial.",
                ],
            ),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.85),
            warnings=self._warnings(case_structure, normative_reasoning),
        )

    def _build_divorcio(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        _ = query
        key_facts = self._merge_unique(
            list(case_structure.get("facts") or []),
            [
                "Existe una voluntad clara de promover el divorcio.",
                "Todavia no esta determinada con precision la variante procesal del divorcio.",
            ],
        )
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        evidentiary_needs = self._merge_unique(
            [
                "Partida de matrimonio.",
                "Datos del ultimo domicilio conyugal y domicilios actuales relevantes.",
                "Informacion sobre hijos, vivienda, bienes y deudas.",
                "Base inicial para propuesta reguladora o definicion de efectos del divorcio.",
            ],
            self._facts_to_evidence(missing_facts),
        )
        return self._result(
            summary="Teoria inicial para divorcio con variante procesal aun no definida.",
            primary_theory="Existe una intencion clara de disolver el vinculo matrimonial y corresponde encuadrar el caso, como minimo, dentro del regimen juridico del divorcio.",
            alternative_theories=[
                "Si existe acuerdo suficiente con el otro conyuge, el caso puede reconducirse a una presentacion conjunta.",
                "Si no existe acuerdo o no puede lograrse, la via probable sera el divorcio unilateral con debate sobre sus efectos.",
            ],
            objective="Definir y promover la via de divorcio adecuada, ordenando desde el inicio sus efectos familiares y patrimoniales.",
            key_facts_supporting=key_facts,
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Definicion de la variante procesal: conjunta o unilateral.",
                "Competencia y domicilios relevantes.",
                "Hijos, alimentos y cuidado personal.",
                "Vivienda familiar, bienes y deudas comunes.",
                "Compensacion economica.",
            ],
            evidentiary_needs=evidentiary_needs,
            recommended_line_of_action=self._recommended_actions(
                procedural_strategy,
                fallback=[
                    "Confirmar si existe acuerdo con el otro conyuge.",
                    "Reunir documentacion del matrimonio y domicilios.",
                    "Ordenar efectos sobre hijos, vivienda y patrimonio antes de presentar.",
                ],
            ),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.81),
            warnings=self._warnings(case_structure, normative_reasoning),
        )

    def _build_alimentos_hijos(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        _ = query
        key_facts = self._merge_unique(
            list(case_structure.get("facts") or []),
            [
                "Existe un hijo que requiere sostenimiento alimentario.",
                "El progenitor demandado no cumple total o parcialmente con su obligacion.",
            ],
        )
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        evidentiary_needs = self._merge_unique(
            [
                "Partida de nacimiento del hijo.",
                "Detalle de gastos ordinarios y extraordinarios.",
                "Prueba o indicios de ingresos del progenitor incumplidor.",
                "Intimaciones, pagos parciales o constancias de incumplimiento.",
            ],
            self._facts_to_evidence(missing_facts),
        )
        return self._result(
            summary="Teoria inicial para alimentos a favor de hijos.",
            primary_theory="Existe incumplimiento de la obligacion alimentaria del progenitor no conviviente respecto del hijo.",
            alternative_theories=[
                "La controversia puede enfocarse en el monto de la cuota y la capacidad economica del obligado.",
                "Si hubo intimacion previa o deuda acumulada, puede ampliarse el reclamo a retroactividad o cobro de atrasados.",
            ],
            objective="Obtener fijacion y/o cobro judicial de cuota alimentaria.",
            key_facts_supporting=key_facts,
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Capacidad economica real del progenitor demandado.",
                "Monto y composicion de la cuota.",
                "Convivencia y distribucion de tareas de cuidado.",
                "Pagos parciales o cumplimiento informal.",
                "Retroactividad de la deuda alimentaria.",
            ],
            evidentiary_needs=evidentiary_needs,
            recommended_line_of_action=self._recommended_actions(
                procedural_strategy,
                fallback=[
                    "Reunir prueba del vinculo filial y de gastos del hijo.",
                    "Cuantificar deuda y evaluar cuota provisoria.",
                    "Identificar activos o ingresos para asegurar cumplimiento.",
                ],
            ),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.87),
            warnings=self._warnings(case_structure, normative_reasoning),
        )

    def _build_sucesion_ab_intestato(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        _ = query
        key_facts = self._merge_unique(
            list(case_structure.get("facts") or []),
            [
                "Se produjo el fallecimiento del causante.",
                "Los posibles herederos desean promover el sucesorio intestato.",
            ],
        )
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        evidentiary_needs = self._merge_unique(
            [
                "Partida de defuncion del causante.",
                "Partidas o documentos que acrediten parentesco.",
                "Datos sobre ultimo domicilio real del causante.",
                "Informacion inicial sobre bienes, deudas y posible existencia de testamento.",
            ],
            self._facts_to_evidence(missing_facts),
        )
        return self._result(
            summary="Teoria inicial para sucesion ab intestato.",
            primary_theory="El caso exige acreditar fallecimiento, vocacion hereditaria y competencia para abrir la sucesion y obtener la declaratoria de herederos.",
            alternative_theories=[
                "Si aparece un testamento o un heredero omitido, el encuadre del tramite puede complejizarse.",
                "Si el principal problema es la individualizacion del acervo, la estrategia puede concentrarse primero en relevar bienes y documentos registrales.",
            ],
            objective="Abrir el sucesorio y ordenar la documentacion necesaria para identificar herederos y acervo.",
            key_facts_supporting=key_facts,
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Acreditacion del parentesco y legitimacion hereditaria.",
                "Ultimo domicilio del causante y competencia.",
                "Existencia de testamento o herederos no contemplados.",
                "Determinacion del acervo hereditario.",
            ],
            evidentiary_needs=evidentiary_needs,
            recommended_line_of_action=self._recommended_actions(
                procedural_strategy,
                fallback=[
                    "Reunir partida de defuncion, parentesco y ultimo domicilio del causante.",
                    "Individualizar herederos y relevar bienes o cuentas conocidas.",
                    "Preparar apertura del sucesorio con base documental completa.",
                ],
            ),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.84),
            warnings=self._warnings(case_structure, normative_reasoning),
        )

    def _build_conflicto_patrimonial(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        _ = query, classification
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        evidentiary_needs = self._merge_unique(
            [
                "Titulo del inmueble y porcentaje de titularidad.",
                "Documentacion sobre fecha y modo de adquisicion del bien.",
                "Documentacion sobre divorcio previo, acuerdo o conflicto actual.",
                "Constancias sobre origen del bien: compra, herencia o adjudicacion previa.",
            ],
            self._facts_to_evidence(missing_facts),
        )
        return self._result(
            summary="Teoria inicial para conflicto patrimonial sobre bienes o cotitularidad.",
            primary_theory="El caso exige ordenar la situacion patrimonial del inmueble y definir si la via adecuada es adjudicacion, liquidacion o division segun el origen y la titularidad del bien.",
            alternative_theories=[
                "Si existe acuerdo suficiente, la salida puede canalizarse mediante convenio de adjudicacion.",
                "Si el bien integra una masa ganancial, la controversia puede desplazarse a la liquidacion de comunidad.",
                "Si la disputa es puramente dominial, puede corresponder una estrategia de division o condominio.",
            ],
            objective="Definir la via patrimonial adecuada sin asumir soluciones cerradas antes de precisar ganancialidad, origen del bien y estado del divorcio.",
            key_facts_supporting=self._merge_unique(
                list(case_structure.get("facts") or []),
                [
                    "Existe disputa patrimonial concreta sobre inmueble o titularidad.",
                    "La estrategia depende de identificar origen del bien, titularidad y nivel de acuerdo actual.",
                ],
            ),
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Ganancialidad o caracter propio del bien.",
                "Fecha y modo de adquisicion del inmueble.",
                "Existencia de acuerdo para adjudicacion o necesidad de division.",
                "Incidencia del divorcio o de la liquidacion de comunidad.",
            ],
            evidentiary_needs=evidentiary_needs,
            recommended_line_of_action=self._recommended_actions(
                procedural_strategy,
                fallback=[
                    "Reunir titulo, adquisicion y estado registral del inmueble.",
                    "Precisar si hubo divorcio, acuerdo parcial o conflicto abierto.",
                    "Comparar salida por adjudicacion, liquidacion o division segun la estructura del bien.",
                ],
            ),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.82),
            warnings=self._warnings(case_structure, normative_reasoning),
        )

    def _build_cuidado_personal(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        _ = query, classification
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        return self._result(
            summary="Teoria inicial para cuidado personal.",
            primary_theory="La controversia principal pasa por determinar el centro de vida del nino, la modalidad de cuidado y el interes superior aplicable al caso concreto.",
            alternative_theories=[
                "La solucion puede ser cuidado unilateral con regimen de comunicacion complementario.",
                "Si existen condiciones materiales y coordinacion suficiente, puede explorarse cuidado compartido.",
            ],
            objective="Definir una propuesta de cuidado personal sostenida en centro de vida, rutinas y aptitud de cada progenitor.",
            key_facts_supporting=self._merge_unique(list(case_structure.get("facts") or []), ["Existe disputa concreta sobre convivencia o cuidado cotidiano del nino."]),
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Centro de vida actual del nino.",
                "Rutina escolar, salud y red de apoyo.",
                "Disponibilidad y aptitud cotidiana de cada progenitor.",
            ],
            evidentiary_needs=self._merge_unique(["Prueba sobre convivencia actual, escolaridad y cuidados cotidianos."], self._facts_to_evidence(missing_facts)),
            recommended_line_of_action=self._recommended_actions(procedural_strategy, fallback=["Precisar centro de vida, rutina y propuesta concreta de cuidado."]),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.79),
            warnings=self._warnings(case_structure, normative_reasoning),
        )

    def _build_regimen_comunicacional(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        _ = query, classification
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        return self._result(
            summary="Teoria inicial para regimen comunicacional.",
            primary_theory="El caso exige restablecer o fijar un esquema de contacto compatible con el interes superior del nino y con la realidad actual de convivencia.",
            alternative_theories=[
                "Si existe obstruccion del contacto, puede ser necesario un pedido urgente.",
                "Si el conflicto es de organizacion, la via puede centrarse en un cronograma claro y verificable.",
            ],
            objective="Obtener un regimen comunicacional concreto, estable y ejecutable.",
            key_facts_supporting=self._merge_unique(list(case_structure.get("facts") or []), ["Existe disputa concreta sobre el contacto del progenitor con el nino."]),
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Frecuencia y modalidad del contacto.",
                "Existencia de impedimentos u obstrucciones previas.",
                "Articulacion con escuela, salud y rutina del nino.",
            ],
            evidentiary_needs=self._merge_unique(["Constancias de impedimentos de contacto, comunicaciones previas y rutina del nino."], self._facts_to_evidence(missing_facts)),
            recommended_line_of_action=self._recommended_actions(procedural_strategy, fallback=["Definir un cronograma de contacto concreto y prueba de impedimentos si existieron."]),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.8),
            warnings=self._warnings(case_structure, normative_reasoning),
        )
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        evidentiary_needs = self._merge_unique(
            [
                "Partida de defuncion del causante.",
                "Partidas o documentos que acrediten parentesco.",
                "Constancia del ultimo domicilio real del causante.",
                "Inventario preliminar de bienes y deudas.",
            ],
            self._facts_to_evidence(missing_facts),
        )
        return self._result(
            summary="Teoria inicial para sucesion ab intestato.",
            primary_theory="Se ha producido la apertura de la sucesion por fallecimiento del causante y corresponde iniciar el proceso sucesorio intestato.",
            alternative_theories=[
                "Si aparece testamento o un heredero omitido, el encuadre y el alcance del tramite pueden modificarse.",
            ],
            objective="Obtener apertura de sucesion y declaratoria de herederos.",
            key_facts_supporting=key_facts,
            missing_facts=missing_facts,
            likely_points_of_conflict=[
                "Competencia territorial por ultimo domicilio del causante.",
                "Herederos omitidos o mal identificados.",
                "Estado civil del causante y derechos del conyuge superstite.",
                "Existencia de testamento.",
                "Individualizacion del acervo hereditario.",
            ],
            evidentiary_needs=evidentiary_needs,
            recommended_line_of_action=self._recommended_actions(
                procedural_strategy,
                fallback=[
                    "Reunir documentacion habilitante del fallecimiento y parentesco.",
                    "Confirmar competencia territorial.",
                    "Armar inventario preliminar del acervo y herederos.",
                ],
            ),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.86),
            warnings=self._warnings(case_structure, normative_reasoning),
        )

    def _build_generic_case_theory(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        procedural_strategy: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> CaseTheoryResult:
        action_label = str(classification.get("action_label") or classification.get("action_slug") or "consulta juridica")
        missing_facts = self._build_missing_facts(case_structure, normative_reasoning, question_engine_result)
        return self._result(
            summary=f"Teoria inicial generica para {action_label.lower()}.",
            primary_theory=f"El caso requiere consolidar una hipotesis juridica mas precisa para {action_label.lower()}.",
            alternative_theories=["La accion o defensa puede variar segun hechos, prueba y objetivo final del consultante."],
            objective=f"Definir una estrategia juridica inicial para {action_label.lower()}.",
            key_facts_supporting=list(case_structure.get("facts") or []),
            missing_facts=missing_facts,
            likely_points_of_conflict=list(case_structure.get("risks") or [])[:5],
            evidentiary_needs=self._facts_to_evidence(missing_facts),
            recommended_line_of_action=self._recommended_actions(
                procedural_strategy,
                fallback=[
                    "Precisar hechos y cronologia del caso.",
                    "Reunir documentacion de respaldo.",
                    "Definir objetivo procesal o asesoramiento buscado.",
                ],
            ),
            confidence_score=self._resolve_confidence(classification, normative_reasoning, 0.56, cap=0.72),
            warnings=[f"No existe teoria especifica para {action_label.lower()}; se uso fallback generico."],
        )

    def _resolve_handler(self, case_domain: str, action_slug: str) -> _CaseTheoryHandler:
        if case_domain and case_domain != "generic" and case_domain in self._domain_registry:
            return self._domain_registry[case_domain]
        return self._registry.get(action_slug, self._build_generic_case_theory)

    def _build_missing_facts(
        self,
        case_structure: dict[str, Any],
        normative_reasoning: dict[str, Any],
        question_engine_result: dict[str, Any],
    ) -> list[str]:
        missing = list(case_structure.get("missing_information") or [])
        missing.extend(str(item) for item in normative_reasoning.get("unresolved_issues") or [])
        for item in question_engine_result.get("critical_questions") or []:
            missing.append(str(item))
        return self._merge_unique([], [item for item in missing if item])[:8]

    def _facts_to_evidence(self, facts: list[str]) -> list[str]:
        evidentiary_needs: list[str] = []
        mapping = (
            (("matrimonio",), "Partida de matrimonio o constancia equivalente."),
            (("domicilio", "competencia"), "Constancias del domicilio relevante."),
            (("hijos", "nacimiento"), "Partidas de nacimiento y documentacion del grupo familiar."),
            (("bienes", "vivienda", "deudas", "patrimonial", "acervo"), "Documentacion patrimonial, registral o inventario preliminar."),
            (("alimentos", "gastos", "cuota"), "Comprobantes de gastos, deuda y capacidad economica."),
            (("fallecimiento", "defuncion", "causante"), "Partida de defuncion y documentos del causante."),
            (("testamento",), "Informe o constancia sobre existencia de testamento."),
        )
        lowered = " ".join(item.lower() for item in facts)
        for terms, evidence in mapping:
            if any(term in lowered for term in terms):
                evidentiary_needs.append(evidence)
        return self._merge_unique([], evidentiary_needs)

    def _recommended_actions(self, procedural_strategy: dict[str, Any], fallback: list[str]) -> list[str]:
        next_steps = procedural_strategy.get("next_steps") or []
        rendered = [str(item) for item in next_steps if str(item).strip()]
        return self._merge_unique(rendered, fallback)[:6]

    def _warnings(self, case_structure: dict[str, Any], normative_reasoning: dict[str, Any]) -> list[str]:
        warnings = list(case_structure.get("warnings") or [])
        warnings.extend(str(item) for item in normative_reasoning.get("warnings") or [])
        return self._merge_unique([], warnings)[:5]

    def _result(
        self,
        summary: str,
        primary_theory: str,
        alternative_theories: list[str],
        objective: str,
        key_facts_supporting: list[str],
        missing_facts: list[str],
        likely_points_of_conflict: list[str],
        evidentiary_needs: list[str],
        recommended_line_of_action: list[str],
        confidence_score: float,
        warnings: list[str],
    ) -> CaseTheoryResult:
        return CaseTheoryResult(
            summary=summary,
            primary_theory=primary_theory,
            alternative_theories=self._merge_unique([], alternative_theories),
            objective=objective,
            key_facts_supporting=self._merge_unique([], key_facts_supporting)[:6],
            missing_facts=self._merge_unique([], missing_facts)[:8],
            likely_points_of_conflict=self._merge_unique([], likely_points_of_conflict)[:6],
            evidentiary_needs=self._merge_unique([], evidentiary_needs)[:8],
            recommended_line_of_action=self._merge_unique([], recommended_line_of_action)[:6],
            confidence_score=round(confidence_score, 4),
            warnings=self._merge_unique([], warnings),
        )

    def _resolve_confidence(
        self,
        classification: dict[str, Any],
        normative_reasoning: dict[str, Any],
        base: float,
        cap: float = 0.93,
    ) -> float:
        confidence = base
        confidence += min(float(classification.get("confidence_score") or 0.0) * 0.05, 0.04)
        confidence += min(len(normative_reasoning.get("applied_rules") or []) * 0.005, 0.03)
        confidence -= min(len(normative_reasoning.get("unresolved_issues") or []) * 0.01, 0.10)
        return max(0.25, min(cap, confidence))

    @staticmethod
    def _merge_unique(base: list[str], additions: list[str]) -> list[str]:
        seen = {item.casefold() for item in base}
        merged = list(base)
        for item in additions:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(text)
        return merged

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
