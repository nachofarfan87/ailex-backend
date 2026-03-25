"""
AILEX -- NormativeReasoner

Construye una capa de razonamiento normativo orientada a acciones juridicas
especificas del pipeline. Toma la clasificacion, la estructura del caso y los
chunks recuperados para producir reglas aplicadas, inferencias, requisitos,
cuestiones pendientes y warnings serializables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from legal_engine.jurisprudence_index import JurisprudenceIndex
from legal_engine.output_cleanup import cleanup_text_list


@dataclass
class AppliedRule:
    source: str
    article: str
    title: str | None
    relevance: str
    effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "article": self.article,
            "title": self.title,
            "relevance": self.relevance,
            "effect": self.effect,
        }


@dataclass
class NormativeReasoningResult:
    summary: str
    legal_basis: list[str] = field(default_factory=list)
    applied_rules: list[AppliedRule] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unresolved_issues: list[str] = field(default_factory=list)
    confidence_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "legal_basis": list(self.legal_basis),
            "applied_rules": [rule.to_dict() for rule in self.applied_rules],
            "inferences": list(self.inferences),
            "requirements": list(self.requirements),
            "warnings": list(self.warnings),
            "unresolved_issues": list(self.unresolved_issues),
            "confidence_score": self.confidence_score,
        }


_ReasoningHandler = Callable[
    [str, dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    NormativeReasoningResult,
]


class NormativeReasoner:
    # Slugs alternativos que deben redirigir al handler de alimentos_hijos
    _ALIMENTOS_SLUG_ALIASES = frozenset({
        "alimentos",
        "cuota_alimentaria",
        "cuota_alimentaria_provisoria",
        "alimentos_provisorios",
        "alimento_provisorio",
        "aumento_de_cuota",
        "reduccion_de_cuota",
    })

    def __init__(self) -> None:
        self._registry: dict[str, _ReasoningHandler] = {
            "divorcio_mutuo_acuerdo": self._reason_divorcio_mutuo_acuerdo,
            "divorcio": self._reason_divorcio,
            "divorcio_unilateral": self._reason_divorcio_unilateral,
            "alimentos_hijos": self._reason_alimentos_hijos,
            "sucesion_ab_intestato": self._reason_sucesion_ab_intestato,
        }
        # Registrar aliases de alimentos apuntando al mismo handler
        for alias in self._ALIMENTOS_SLUG_ALIASES:
            self._registry.setdefault(alias, self._reason_alimentos_hijos)

    # Patrones de query que fuerzan el handler de alimentos cuando el slug es
    # genérico o vacío (safety net si el clasificador no alcanza el umbral).
    _ALIMENTOS_QUERY_PATTERNS = (
        "alimentos",
        "cuota alimentaria",
        "cuota alimentaria provisoria",
        "alimentos provisorios",
        "aumento de cuota",
        "reduccion de cuota",
    )

    def reason(
        self,
        query: str,
        classification: Any = None,
        case_structure: Any = None,
        retrieved_chunks: Any = None,
    ) -> NormativeReasoningResult:
        cls = self._coerce_dict(classification)
        case = self._coerce_dict(case_structure)
        chunks = self._coerce_chunks(retrieved_chunks)
        action_slug = JurisprudenceIndex.normalize_action_slug(str(cls.get("action_slug") or "generic"))

        # Safety net: si el slug quedó genérico pero la query es claramente de
        # alimentos, forzar el handler correcto.
        if action_slug in ("generic", "") and query:
            query_lower = query.lower()
            if any(pat in query_lower for pat in self._ALIMENTOS_QUERY_PATTERNS):
                action_slug = "alimentos_hijos"

        cls["action_slug"] = action_slug
        handler = self._registry.get(action_slug, self._reason_generic)
        return handler(query, cls, case, chunks)

    analyze = reason
    run = reason

    def integrate_jurisprudence(
        self,
        normative_reasoning: Any,
        jurisprudence_analysis: Any = None,
    ) -> NormativeReasoningResult:
        result = self._coerce_reasoning_result(normative_reasoning)
        jurisprudence = self._coerce_dict(jurisprudence_analysis)
        if not jurisprudence:
            return result

        trend = str(jurisprudence.get("precedent_trend") or "neutral").strip().lower()
        confidence_delta = float(jurisprudence.get("confidence_delta") or 0.0)
        directive = str(jurisprudence.get("reasoning_directive") or "").strip()

        summary = result.summary
        inferences = list(result.inferences)
        warnings = list(result.warnings)

        if trend == "favorable":
            inference = directive or "La linea jurisprudencial recuperada acompana el encuadre normativo principal."
            if inference not in inferences:
                inferences.append(inference)
            summary = f"{summary} La orientacion jurisprudencial recuperada resulta favorable al planteo."
        elif trend == "adverse":
            caution = directive or "La linea jurisprudencial disponible impone cautela sobre el alcance del planteo."
            if caution not in warnings:
                warnings.append(caution)
            summary = f"{summary} La orientacion jurisprudencial recuperada introduce una cautela leve sobre el planteo."
        elif directive and directive not in inferences:
            inferences.append(directive)

        return NormativeReasoningResult(
            summary=summary.strip(),
            legal_basis=list(result.legal_basis),
            applied_rules=list(result.applied_rules),
            inferences=self._dedupe_texts(inferences),
            requirements=list(result.requirements),
            warnings=self._dedupe_texts(warnings),
            unresolved_issues=list(result.unresolved_issues),
            confidence_score=self._clamp_confidence(result.confidence_score + confidence_delta),
        )

    def _reason_divorcio_mutuo_acuerdo(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
    ) -> NormativeReasoningResult:
        _ = query
        rules = self._collect_rules(
            classification=classification,
            case_structure=case_structure,
            retrieved_chunks=retrieved_chunks,
            fallback_rules=[
                self._rule("CCyC", "435", "Disolucion del matrimonio", "Base del encuadre del divorcio.", "Ubica la disolucion del vinculo dentro del regimen general."),
                self._rule("CCyC", "437", "Legitimacion", "Habilita la peticion de divorcio por ambos conyuges.", "Permite la presentacion conjunta sin invocar causa."),
                self._rule("CCyC", "438", "Procedimiento", "Exige propuesta reguladora con la solicitud.", "La omision de la propuesta reguladora compromete la admisibilidad."),
                self._rule("CCyC", "439", "Convenio regulador", "Delimita el contenido minimo del acuerdo.", "Ordena regular hijos, bienes, vivienda y alimentos."),
                self._rule("CCyC", "440", "Eficacia del convenio", "Permite control judicial y modificacion.", "El acuerdo debe ser consistente y susceptible de homologacion."),
                self._rule("CCyC", "441", "Compensacion economica", "Abre la via para compensacion por desequilibrio.", "Obliga a definir si se reclama o renuncia."),
                self._rule("CCyC", "717", "Competencia", "Determina la competencia en divorcio.", "La eleccion del juzgado depende del domicilio relevante."),
            ],
        )

        inferences = [
            "El divorcio es incausado y, si ambas partes estan de acuerdo, puede tramitarse por presentacion conjunta.",
            "La propuesta reguladora es un presupuesto central del tramite y debe cubrir los efectos personales y patrimoniales del divorcio.",
            "Si existen hijos menores, el acuerdo debe contemplar cuidado personal, comunicacion y alimentos.",
            "La competencia judicial se vincula con el ultimo domicilio conyugal o el domicilio de las partes segun el encuadre del caso.",
        ]
        requirements = cleanup_text_list([
            "Partida o datos basicos del matrimonio.",
            "Propuesta reguladora sobre vivienda, bienes, alimentos y cuidado personal.",
            "Determinacion de hijos menores o con capacidad restringida.",
            "Informacion patrimonial y eventual compensacion economica.",
            "Domicilio relevante para definir competencia.",
        ], item_type="missing_info")
        unresolved = self._derive_unresolved(
            case_structure,
            extra_items=[
                "No se precisa si existen hijos menores o con capacidad restringida.",
                "No se informa sobre bienes gananciales, vivienda familiar o deudas comunes.",
                "Falta determinar si existen alimentos entre conyuges o cuota alimentaria.",
                "Falta definir si existe compensacion economica o renuncia expresa.",
            ],
        )
        warnings = self._warnings_from_unresolved(unresolved)

        return NormativeReasoningResult(
            summary="Razonamiento normativo especifico para divorcio por mutuo acuerdo.",
            legal_basis=[f"Art. {rule.article} {rule.source}" for rule in rules],
            applied_rules=rules,
            inferences=inferences,
            requirements=requirements,
            warnings=warnings,
            unresolved_issues=unresolved,
            confidence_score=self._confidence_score(classification, 0.82, len(rules), len(unresolved)),
        )

    def _reason_divorcio_unilateral(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
    ) -> NormativeReasoningResult:
        _ = query
        rules = self._collect_rules(
            classification=classification,
            case_structure=case_structure,
            retrieved_chunks=retrieved_chunks,
            fallback_rules=[
                self._rule("CCyC", "437", "Legitimacion", "Permite el divorcio a peticion de uno de los conyuges.", "La falta de acuerdo del otro conyuge no bloquea la accion."),
                self._rule("CCyC", "438", "Procedimiento", "Impone presentar propuesta reguladora con la peticion.", "El conflicto se desplaza a los efectos del divorcio, no a su procedencia."),
                self._rule("CCyC", "439", "Propuesta reguladora", "Ordena los contenidos minimos de la propuesta.", "Es necesario individualizar vivienda, bienes, alimentos y cuidado parental si corresponde."),
                self._rule("CCyC", "441", "Compensacion economica", "Permite reclamar compensacion por desequilibrio.", "Debe definirse si se reclama, se negocia o se descarta."),
                self._rule("CCyC", "717", "Competencia", "Fija competencia territorial en divorcio.", "Un error sobre domicilio o competencia puede demorar la radicacion."),
                self._rule("CCyC", "721", "Medidas provisionales", "Habilita medidas personales o patrimoniales provisorias.", "Puede ser necesario pedir medidas urgentes mientras se resuelven efectos controvertidos."),
            ],
        )

        inferences = [
            "El divorcio es incausado y puede ser promovido unilateralmente aunque el otro conyuge no quiera divorciarse.",
            "La oposicion del otro conyuge no impide la disolucion del vinculo, pero puede volver contenciosos los efectos del divorcio.",
            "La peticion inicial debe acompanar una propuesta reguladora suficiente sobre hijos, alimentos, vivienda y bienes.",
            "Si existen puntos sensibles sobre convivencia, cuota o atribucion de vivienda, puede ser conveniente evaluar medidas provisionales.",
        ]
        requirements = cleanup_text_list([
            "Datos del matrimonio y ultimo domicilio conyugal.",
            "Domicilio actual del otro conyuge para notificacion.",
            "Propuesta reguladora inicial suficientemente detallada.",
            "Informacion sobre hijos menores, alimentos y vivienda familiar.",
            "Definicion sobre compensacion economica y situacion patrimonial.",
        ], item_type="missing_info")
        unresolved = self._derive_unresolved(
            case_structure,
            extra_items=[
                "No se informa el domicilio actual del otro conyuge ni el ultimo domicilio conyugal.",
                "Falta precisar si existen hijos menores y como se propone regular su cuidado y alimentos.",
                "No se determina la situacion patrimonial ni la atribucion de la vivienda familiar.",
            ],
        )
        warnings = self._warnings_from_unresolved(unresolved)

        return NormativeReasoningResult(
            summary="Razonamiento normativo especifico para divorcio unilateral.",
            legal_basis=[f"Art. {rule.article} {rule.source}" for rule in rules],
            applied_rules=rules,
            inferences=inferences,
            requirements=requirements,
            warnings=warnings,
            unresolved_issues=unresolved,
            confidence_score=self._confidence_score(classification, 0.84, len(rules), len(unresolved)),
        )

    def _reason_divorcio(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
    ) -> NormativeReasoningResult:
        _ = query
        rules = self._collect_rules(
            classification=classification,
            case_structure=case_structure,
            retrieved_chunks=retrieved_chunks,
            fallback_rules=[
                self._rule("CCyC", "437", "Legitimacion", "Permite peticionar el divorcio por ambos o por uno de los conyuges.", "El sistema debe encuadrar la consulta como divorcio aun sin definir su variante especifica."),
                self._rule("CCyC", "438", "Procedimiento", "Exige presentar propuesta reguladora con la solicitud de divorcio.", "La accion requiere una base regulatoria minima sobre sus efectos."),
                self._rule("CCyC", "439", "Convenio regulador", "Establece el contenido basico de los efectos del divorcio.", "Hijos, vivienda, bienes y alimentos deben quedar contemplados."),
                self._rule("CCyC", "441", "Compensacion economica", "Permite canalizar reclamos por desequilibrio economico.", "Es un punto a definir aunque la variante del divorcio aun no este cerrada."),
                self._rule("CCyC", "717", "Competencia", "Determina la competencia territorial en divorcio.", "El ultimo domicilio conyugal y los domicilios actuales siguen siendo datos estructurales."),
                self._rule("CCyC", "721", "Medidas provisionales", "Preve medidas cautelares o personales durante el proceso.", "Si hay urgencia familiar o patrimonial, pueden articularse aun antes de definir todos los efectos."),
            ],
        )

        inferences = [
            "La consulta revela una intencion clara de disolver el vinculo matrimonial y debe encuadrarse como divorcio en fuero de familia.",
            "Aunque todavia no se determine si el divorcio sera conjunto o unilateral, la estructura normativa aplicable es la propia del divorcio incausado.",
            "La propuesta reguladora sigue siendo necesaria para ordenar los efectos del divorcio sobre hijos, alimentos, vivienda y patrimonio.",
            "La variante procesal concreta depende de si existe acuerdo o conflicto con el otro conyuge sobre el inicio o sobre sus efectos.",
        ]
        requirements = cleanup_text_list([
            "Datos del matrimonio y del ultimo domicilio conyugal.",
            "Informacion para definir si la via sera conjunta o unilateral.",
            "Existencia de hijos menores o con capacidad restringida.",
            "Situacion patrimonial, vivienda familiar y eventuales alimentos.",
            "Definicion preliminar sobre propuesta reguladora y compensacion economica.",
        ], item_type="missing_info")
        unresolved = self._derive_unresolved(
            case_structure,
            extra_items=[
                "Falta determinar si el divorcio sera por presentacion conjunta o a peticion unilateral.",
                "No se informa si existen hijos menores o con capacidad restringida.",
                "No se precisa la situacion de vivienda, bienes, deudas o compensacion economica.",
                "No se identifica aun el domicilio relevante para competencia y notificacion.",
            ],
        )
        warnings = self._warnings_from_unresolved(unresolved)

        return NormativeReasoningResult(
            summary="Razonamiento normativo especifico para divorcio sin variante procesal aun definida.",
            legal_basis=[f"Art. {rule.article} {rule.source}" for rule in rules],
            applied_rules=rules,
            inferences=inferences,
            requirements=requirements,
            warnings=warnings,
            unresolved_issues=unresolved,
            confidence_score=self._confidence_score(classification, 0.8, len(rules), len(unresolved)),
        )

    def _reason_alimentos_hijos(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
    ) -> NormativeReasoningResult:
        _ = query
        allowed_articles = {"658", "659", "660", "661", "662", "663", "664", "669"}
        rules = self._collect_rules(
            classification=classification,
            case_structure=case_structure,
            retrieved_chunks=self._filter_chunks_by_priority(retrieved_chunks, self._allowed_priority_rules(classification)),
            fallback_rules=[
                self._rule("CCyC", "658", "Regla general", "Ubica la obligacion alimentaria dentro de la responsabilidad parental.", "El progenitor obligado debe contribuir a la manutencion del hijo."),
                self._rule("CCyC", "659", "Contenido", "Delimita el alcance material de los alimentos.", "La cuota debe cubrir manutencion, educacion, salud y esparcimiento."),
                self._rule("CCyC", "660", "Tareas de cuidado", "Reconoce valor economico al cuidado cotidiano.", "El aporte del progenitor conviviente incide al cuantificar la cuota."),
                self._rule("CCyC", "661", "Legitimacion", "Precisa quien puede reclamar alimentos a favor del hijo.", "Permite accionar al progenitor conviviente o representante legal."),
                self._rule("CCyC", "662", "Fijacion judicial", "Habilita al juez a determinar monto y modalidad.", "La cuota puede fijarse aun con prueba inicial incompleta si hay verosimilitud."),
                self._rule("CCyC", "663", "Aseguramiento", "Permite medidas para garantizar el pago.", "Puede pedirse retencion, embargo u otras medidas de aseguramiento."),
                self._rule("CCyC", "664", "Cuidado y convivencia", "Relaciona alimentos con modalidad de convivencia.", "El esquema de cuidado impacta en el monto y distribucion de cargas."),
                self._rule("CCyC", "669", "Retroactividad", "Regula alimentos atrasados y retroactividad.", "La interpelacion o la demanda pueden marcar el inicio del credito reclamable."),
            ],
        )

        inferences = [
            "El incumplimiento alimentario del progenitor habilita una accion especifica en fuero de familia.",
            "La legitimacion activa corresponde, en principio, al progenitor conviviente o al representante legal del hijo.",
            "La cuantificacion de la cuota debe considerar necesidades del hijo, capacidad economica del demandado y valor de las tareas de cuidado.",
            "Si existen pagos omitidos o intimaciones previas, puede analizarse retroactividad y medidas de aseguramiento.",
        ]
        requirements = cleanup_text_list([
            "Partida de nacimiento u otra acreditacion del vinculo filial.",
            "Edad del hijo y regimen de cuidado o convivencia.",
            "Detalle de gastos ordinarios y extraordinarios del hijo.",
            "Indicadores de ingresos o capacidad economica del progenitor demandado.",
            "Antecedentes de intimaciones, pagos parciales o deuda acumulada.",
        ], item_type="missing_info")
        unresolved = self._derive_unresolved(
            case_structure,
            extra_items=[
                "No se precisa la edad del hijo ni con quien convive actualmente.",
                "Falta informacion sobre ingresos del progenitor incumplidor o indicios patrimoniales.",
                "No se detallan gastos concretos del hijo ni deuda alimentaria acumulada.",
                "No se indica si hubo intimacion previa que sostenga un reclamo retroactivo.",
            ],
        )
        warnings = self._warnings_from_unresolved(unresolved)

        return NormativeReasoningResult(
            summary="Razonamiento normativo especifico para alimentos a favor de hijos.",
            legal_basis=[f"Art. {rule.article} {rule.source}" for rule in rules],
            applied_rules=rules,
            inferences=inferences,
            requirements=requirements,
            warnings=warnings,
            unresolved_issues=unresolved,
            confidence_score=self._confidence_score(classification, 0.86, len(rules), len(unresolved)),
        )

    def _reason_sucesion_ab_intestato(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
    ) -> NormativeReasoningResult:
        _ = query
        allowed_articles = {"2277", "2280", "2288", "2335", "2336", "2340", "2424", "2431"}
        rules = self._collect_rules(
            classification=classification,
            case_structure=case_structure,
            retrieved_chunks=self._filter_chunks_by_priority(retrieved_chunks, self._allowed_priority_rules(classification)),
            fallback_rules=[
                self._rule("CCyC", "2277", "Apertura", "Ubica la apertura sucesoria en el fallecimiento del causante.", "La muerte produce la transmision hereditaria y justifica iniciar el proceso."),
                self._rule("CCyC", "2280", "Legitimacion", "Determina quienes pueden promover la sucesion.", "Los herederos o interesados legitimados pueden impulsar la apertura."),
                self._rule("CCyC", "2288", "Aceptacion o renuncia", "Situa la posicion juridica inicial del heredero.", "Conviene identificar si existe aceptacion tacita o necesidad de reserva."),
                self._rule("CCyC", "2335", "Objeto del proceso", "Ordena la finalidad del proceso sucesorio.", "La sucesion sirve para individualizar herederos, administrar y partir el acervo."),
                self._rule("CCyC", "2336", "Competencia", "Fija competencia por el ultimo domicilio del causante.", "La radicacion correcta depende de acreditar ese domicilio."),
                self._rule("CCyC", "2340", "Investidura", "Aclara el alcance practico de la investidura hereditaria.", "La declaratoria sigue siendo necesaria para operar frente a terceros y registros."),
                self._rule("CCyC", "2424", "Descendientes", "Regula el orden sucesorio de descendientes.", "Es clave si heredan hijos o nietos del causante."),
                self._rule("CCyC", "2431", "Conyuge superstite", "Delimita derechos del conyuge superviviente.", "Debe verificarse el estado civil del causante y la concurrencia hereditaria."),
            ],
        )

        inferences = [
            "La muerte del causante habilita la apertura de la sucesion y el pedido de declaratoria de herederos.",
            "La competencia se define, en principio, por el ultimo domicilio real del causante.",
            "Para avanzar con la declaratoria se debe acreditar parentesco, estado civil y eventual inexistencia de testamento.",
            "La utilidad practica del proceso sucesorio depende de individualizar bienes, deudas y herederos con precision suficiente.",
        ]
        requirements = cleanup_text_list([
            "Partida de defuncion del causante.",
            "Documentacion que acredite el vinculo de los herederos.",
            "Ultimo domicilio real del causante.",
            "Informacion sobre existencia o inexistencia de testamento.",
            "Inventario preliminar de bienes, cuentas, inmuebles o deudas.",
        ], item_type="missing_info")
        unresolved = self._derive_unresolved(
            case_structure,
            extra_items=[
                "No se informa con precision el ultimo domicilio real del causante.",
                "Falta identificar si existen otros herederos forzosos o conyuge superstite.",
                "No se detalla si existe testamento ni el inventario preliminar del acervo.",
            ],
        )
        warnings = self._warnings_from_unresolved(unresolved)

        return NormativeReasoningResult(
            summary="Razonamiento normativo especifico para sucesion ab intestato.",
            legal_basis=[f"Art. {rule.article} {rule.source}" for rule in rules],
            applied_rules=rules,
            inferences=inferences,
            requirements=requirements,
            warnings=warnings,
            unresolved_issues=unresolved,
            confidence_score=self._confidence_score(classification, 0.85, len(rules), len(unresolved)),
        )

    def _reason_generic(
        self,
        query: str,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
    ) -> NormativeReasoningResult:
        action_label = str(classification.get("action_label") or classification.get("action_slug") or "consulta juridica")
        rules = self._collect_rules(
            classification=classification,
            case_structure=case_structure,
            retrieved_chunks=retrieved_chunks,
            fallback_rules=[],
        )
        missing = list(case_structure.get("missing_information") or [])
        unresolved = cleanup_text_list(
            missing or [
                "Hechos relevantes del caso.",
                "Documentacion de respaldo.",
            ],
            item_type="missing_info",
        )
        summary = f"Se aplico razonamiento normativo generico para {action_label.lower()}."
        warnings = [f"No existe handler normativo especifico para {action_label.lower()}; se uso fallback generico."]
        inferences = [
            "El encuadre normativo requiere complementar hechos y documentacion antes de profundizar el analisis."
        ]
        requirements = cleanup_text_list(missing, item_type="missing_info")

        return NormativeReasoningResult(
            summary=summary,
            legal_basis=[f"Art. {rule.article} {rule.source}" for rule in rules],
            applied_rules=rules,
            inferences=inferences,
            requirements=requirements,
            warnings=warnings,
            unresolved_issues=unresolved,
            confidence_score=self._confidence_score(classification, 0.52, len(rules), len(unresolved), cap=0.7),
        )

    def _collect_rules(
        self,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
        fallback_rules: list[AppliedRule],
    ) -> list[AppliedRule]:
        collected: list[AppliedRule] = []
        seen: set[tuple[str, str]] = set()
        allowed_priority = self._allowed_priority_rules(classification)

        for item in fallback_rules:
            key = (item.source, item.article)
            if key not in seen:
                seen.add(key)
                collected.append(item)

        for rule in case_structure.get("applicable_rules") or []:
            normalized = self._rule_from_case_structure(rule, allowed_priority=allowed_priority)
            if normalized is None:
                continue
            key = (normalized.source, normalized.article)
            if key not in seen:
                seen.add(key)
                collected.append(normalized)

        for chunk in retrieved_chunks:
            normalized = self._rule_from_chunk(chunk, allowed_priority=allowed_priority)
            if normalized is None:
                continue
            key = (normalized.source, normalized.article)
            if key not in seen:
                seen.add(key)
                collected.append(normalized)

        return collected

    def _derive_unresolved(
        self,
        case_structure: dict[str, Any],
        extra_items: list[str],
    ) -> list[str]:
        base = list(case_structure.get("missing_information") or [])
        unresolved = cleanup_text_list([*base, *extra_items], item_type="missing_info")
        return unresolved[:8]

    def _warnings_from_unresolved(self, unresolved: list[str]) -> list[str]:
        if not unresolved:
            return []
        return cleanup_text_list(
            [f"Persisten cuestiones relevantes a completar: {item}" for item in unresolved[:3]],
            item_type="warning",
        )

    def _confidence_score(
        self,
        classification: dict[str, Any],
        base: float,
        rule_count: int,
        unresolved_count: int,
        cap: float = 0.92,
    ) -> float:
        confidence = base
        confidence += min(rule_count * 0.01, 0.06)
        confidence -= min(unresolved_count * 0.015, 0.12)
        cls_score = float(classification.get("confidence_score") or 0.0)
        confidence += min(cls_score * 0.04, 0.03)
        return round(max(0.25, min(cap, confidence)), 4)

    def _filter_chunks_by_priority(
        self,
        chunks: list[dict[str, Any]],
        allowed_priority: set[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        if not allowed_priority:
            return list(chunks)
        filtered: list[dict[str, Any]] = []
        for chunk in chunks:
            normalized = self._normalize_rule_identity(chunk)
            if normalized is None or normalized not in allowed_priority:
                continue
            filtered.append(chunk)
        return filtered

    def _rule_from_case_structure(
        self,
        item: Any,
        *,
        allowed_priority: set[tuple[str, str]] | None = None,
    ) -> AppliedRule | None:
        rule = self._coerce_dict(item)
        article = str(rule.get("article") or "").strip()
        if not article:
            return None
        source_id = str(rule.get("source_id") or rule.get("source") or "norma").strip()
        if allowed_priority:
            normalized = self._normalize_rule_identity({"source_id": source_id, "article": article})
            if normalized is None or normalized not in allowed_priority:
                return None
        description = str(rule.get("description") or "").strip()
        source = self._label_source(source_id)
        return AppliedRule(
            source=source,
            article=article,
            title=description or None,
            relevance=description or "Regla aplicable identificada en la estructura del caso.",
            effect=description or "Aporta encuadre normativo al caso.",
        )

    def _rule_from_chunk(
        self,
        item: dict[str, Any],
        *,
        allowed_priority: set[tuple[str, str]] | None = None,
    ) -> AppliedRule | None:
        article = str(item.get("article") or "").strip()
        if not article:
            return None
        if allowed_priority:
            normalized = self._normalize_rule_identity(item)
            if normalized is None or normalized not in allowed_priority:
                return None
        source = self._label_source(str(item.get("source_id") or item.get("source") or item.get("norma") or "norma"))
        title = str(item.get("titulo") or item.get("title") or item.get("label") or "").strip() or None
        text = str(item.get("texto") or item.get("text") or "").strip()
        relevance = title or "Norma recuperada por el motor de busqueda."
        effect = text[:180].strip() if text else "La norma recuperada puede aportar sustento adicional."
        return AppliedRule(
            source=source,
            article=article,
            title=title,
            relevance=relevance,
            effect=effect,
        )

    def _rule(
        self,
        source: str,
        article: str,
        title: str,
        relevance: str,
        effect: str,
    ) -> AppliedRule:
        return AppliedRule(
            source=source,
            article=article,
            title=title,
            relevance=relevance,
            effect=effect,
        )

    def _allowed_priority_rules(self, classification: dict[str, Any]) -> set[tuple[str, str]]:
        allowed: set[tuple[str, str]] = set()
        for item in classification.get("priority_articles") or []:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_rule_identity(item)
            if normalized is not None:
                allowed.add(normalized)
        return allowed

    @staticmethod
    def _normalize_rule_identity(item: dict[str, Any]) -> tuple[str, str] | None:
        source_id = str(item.get("source_id") or item.get("source") or item.get("norma") or "").strip().lower()
        article = str(item.get("article") or "").strip()
        if not source_id or not article:
            return None
        source_map = {
            "codigo civil y comercial de la nacion": "codigo_civil_comercial",
            "codigo civil y comercial": "codigo_civil_comercial",
            "ccyc": "codigo_civil_comercial",
            "codigo_civil_comercial": "codigo_civil_comercial",
            "cpcc jujuy": "cpcc_jujuy",
            "cpcc_jujuy": "cpcc_jujuy",
            "constitucion jujuy": "constitucion_jujuy",
            "constitucion_jujuy": "constitucion_jujuy",
        }
        return source_map.get(source_id, source_id), article

    @staticmethod
    def _label_source(source_id: str) -> str:
        normalized = str(source_id or "").strip().lower()
        labels = {
            "codigo_civil_comercial": "CCyC",
            "codigo civil y comercial": "CCyC",
            "codigo civil y comercial de la nacion": "CCyC",
            "ccyc": "CCyC",
            "cpcc_jujuy": "CPCC Jujuy",
            "constitucion_nacional": "CN",
            "constitucion_jujuy": "Const. Jujuy",
            "lct_20744": "LCT",
        }
        return labels.get(normalized, source_id or "Norma")

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

    def _coerce_chunks(self, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._coerce_dict(item) for item in value if self._coerce_dict(item)]
        if isinstance(value, dict) and isinstance(value.get("results"), list):
            return [self._coerce_dict(item) for item in value.get("results") or [] if self._coerce_dict(item)]
        coerced = self._coerce_dict(value)
        return [coerced] if coerced else []

    def _coerce_reasoning_result(self, value: Any) -> NormativeReasoningResult:
        if isinstance(value, NormativeReasoningResult):
            return value
        data = self._coerce_dict(value)
        applied_rules = []
        for item in data.get("applied_rules") or []:
            if isinstance(item, AppliedRule):
                applied_rules.append(item)
                continue
            rule = self._coerce_dict(item)
            if not rule:
                continue
            applied_rules.append(
                AppliedRule(
                    source=str(rule.get("source") or ""),
                    article=str(rule.get("article") or ""),
                    title=str(rule.get("title")) if rule.get("title") is not None else None,
                    relevance=str(rule.get("relevance") or ""),
                    effect=str(rule.get("effect") or ""),
                )
            )
        return NormativeReasoningResult(
            summary=str(data.get("summary") or ""),
            legal_basis=[str(item) for item in (data.get("legal_basis") or []) if str(item).strip()],
            applied_rules=applied_rules,
            inferences=[str(item) for item in (data.get("inferences") or []) if str(item).strip()],
            requirements=[str(item) for item in (data.get("requirements") or []) if str(item).strip()],
            warnings=[str(item) for item in (data.get("warnings") or []) if str(item).strip()],
            unresolved_issues=[str(item) for item in (data.get("unresolved_issues") or []) if str(item).strip()],
            confidence_score=float(data.get("confidence_score") or 0.0),
        )

    @staticmethod
    def _dedupe_texts(items: list[str]) -> list[str]:
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
    def _clamp_confidence(value: float) -> float:
        return round(max(0.25, min(0.95, float(value))), 4)
