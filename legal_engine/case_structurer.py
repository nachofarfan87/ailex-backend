"""
AILEX -- CaseStructurer

Transforma una consulta juridica + ActionClassification en una estructura
del caso (CaseStructure) que organiza hechos, pretension, normativa
aplicable, informacion faltante y riesgos.

Cada action_slug puede tener un handler especializado.  Si no hay handler
registrado se aplica el fallback generico.

Uso:

    structurer = CaseStructurer()
    case = structurer.structure(query, classification)
    print(case.to_dict())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from legal_engine.output_cleanup import cleanup_text_list


# ---------------------------------------------------------------------------
# Dataclasses de salida
# ---------------------------------------------------------------------------

@dataclass
class ApplicableRule:
    """Regla normativa aplicable al caso."""
    source_id: str
    article: str
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "article": self.article,
            "description": self.description,
        }


@dataclass
class CaseStructure:
    """Estructura completa del caso juridico."""

    # Identidad
    action_slug: str
    action_label: str

    # Encuadre
    summary: str
    legal_issue: str
    main_claim: str

    # Contexto procesal
    forum: str
    process_type: str
    jurisdiction: str

    # Hechos inferidos de la consulta
    facts: List[str] = field(default_factory=list)

    # Normativa
    applicable_rules: List[ApplicableRule] = field(default_factory=list)

    # Gaps y riesgos
    missing_information: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)

    # Estrategia sugerida
    suggested_strategy: str = ""

    # Confianza
    confidence_score: float = 0.0

    # Warnings
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_slug": self.action_slug,
            "action_label": self.action_label,
            "summary": self.summary,
            "legal_issue": self.legal_issue,
            "main_claim": self.main_claim,
            "forum": self.forum,
            "process_type": self.process_type,
            "jurisdiction": self.jurisdiction,
            "facts": list(self.facts),
            "applicable_rules": [r.to_dict() for r in self.applicable_rules],
            "missing_information": list(self.missing_information),
            "risks": list(self.risks),
            "suggested_strategy": self.suggested_strategy,
            "confidence_score": self.confidence_score,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Registros de casos especificos
# ---------------------------------------------------------------------------

_CASE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "divorcio_mutuo_acuerdo": {
        "summary": (
            "Presentacion conjunta de divorcio por mutuo acuerdo de ambos conyuges, "
            "con propuesta reguladora de los efectos del divorcio."
        ),
        "legal_issue": (
            "Disolucion del vinculo matrimonial a peticion de ambos conyuges "
            "conforme al regimen del Codigo Civil y Comercial de la Nacion."
        ),
        "main_claim": (
            "Peticion conjunta de divorcio con propuesta reguladora "
            "que contemple los efectos patrimoniales y personales del divorcio."
        ),
        "facts": [
            "Ambos conyuges manifiestan voluntad de divorciarse.",
            "La peticion es conjunta (mutuo acuerdo).",
            "Se requiere propuesta reguladora de los efectos del divorcio.",
        ],
        "applicable_rules": [
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="435",
                description="Causas de disolucion del matrimonio.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="437",
                description="Legitimacion: divorcio a peticion de ambos o de uno de los conyuges.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="438",
                description="Requisitos y procedimiento del divorcio; propuesta reguladora obligatoria.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="439",
                description="Contenido minimo del convenio regulador.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="440",
                description="Eficacia y modificacion del convenio regulador.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="441",
                description="Compensacion economica entre conyuges.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="717",
                description="Competencia judicial en procesos de divorcio.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="721",
                description="Medidas provisionales durante el proceso de divorcio.",
            ),
        ],
        "missing_information": [
            "Fecha y lugar de celebracion del matrimonio.",
            "Ultimo domicilio conyugal.",
            "Existencia de hijos menores o con capacidad restringida.",
            "Bienes gananciales o propios en comun.",
            "Situacion de la vivienda familiar.",
            "Acuerdo sobre alimentos entre conyuges y para hijos, si los hubiere.",
            "Compensacion economica pactada o a reclamar.",
        ],
        "risks": [
            "La omision de la propuesta reguladora impide dar tramite a la peticion.",
            "Un convenio regulador incompleto puede generar observaciones judiciales.",
            "Si existen hijos, la falta de precision en cuidado y alimentos debilita la presentacion.",
            "La falta de acuerdo sobre la vivienda puede dilatar el proceso.",
        ],
        "suggested_strategy": (
            "Preparar presentacion conjunta acompanada de propuesta reguladora completa. "
            "Si hay hijos menores, incluir plan de parentalidad con regimen de cuidado, "
            "alimentos y comunicacion. Documentar situacion patrimonial y acordar "
            "atribucion de vivienda y compensacion economica si corresponde."
        ),
    },
    "divorcio": {
        "summary": (
            "Proceso de divorcio. Puede ser a peticion unilateral o conjunta "
            "conforme al Codigo Civil y Comercial de la Nacion."
        ),
        "legal_issue": (
            "Disolucion del vinculo matrimonial conforme al regimen vigente."
        ),
        "main_claim": (
            "Peticion de divorcio con propuesta reguladora de los efectos."
        ),
        "facts": [
            "Al menos uno de los conyuges manifiesta voluntad de divorciarse.",
            "Se requiere propuesta reguladora de los efectos del divorcio.",
        ],
        "applicable_rules": [
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="437",
                description="Legitimacion para peticionar el divorcio.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="438",
                description="Requisitos y procedimiento del divorcio.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="439",
                description="Contenido del convenio regulador.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="717",
                description="Competencia judicial en procesos de divorcio.",
            ),
        ],
        "missing_information": [
            "Fecha y lugar de celebracion del matrimonio.",
            "Ultimo domicilio conyugal.",
            "Si la peticion es unilateral o conjunta.",
            "Existencia de hijos menores.",
            "Situacion patrimonial.",
        ],
        "risks": [
            "La omision de la propuesta reguladora impide dar tramite a la peticion.",
            "Si la peticion es unilateral, la contraparte puede no adherir a la propuesta reguladora.",
        ],
        "suggested_strategy": (
            "Presentar peticion de divorcio con propuesta reguladora. "
            "Si es unilateral, preparar estrategia para eventual desacuerdo "
            "sobre los efectos del divorcio."
        ),
    },
    "divorcio_unilateral": {
        "summary": (
            "Peticion unilateral de divorcio cuando solo uno de los conyuges "
            "quiere disolver el vinculo matrimonial."
        ),
        "legal_issue": (
            "Procedencia del divorcio a peticion de uno solo de los conyuges "
            "y determinacion judicial de sus efectos si no hay acuerdo."
        ),
        "main_claim": (
            "Peticion unilateral de divorcio con propuesta reguladora y "
            "eventual tratamiento de desacuerdos sobre sus efectos."
        ),
        "facts": [
            "Uno de los conyuges manifiesta voluntad de divorciarse.",
            "La otra parte no presta conformidad inicial al divorcio.",
            "La presentacion debe incluir propuesta reguladora de efectos.",
        ],
        "applicable_rules": [
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="437",
                description="Legitimacion para peticionar el divorcio unilateralmente.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="438",
                description="Requisitos del divorcio y propuesta reguladora obligatoria.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="439",
                description="Contenido minimo del convenio o propuesta reguladora.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="440",
                description="Revision judicial y eficacia de los acuerdos sobre efectos.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="441",
                description="Compensacion economica en caso de desequilibrio manifiesto.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="717",
                description="Competencia judicial en materia de divorcio.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="721",
                description="Medidas provisionales posibles durante el proceso de divorcio.",
            ),
        ],
        "missing_information": [
            "Fecha y lugar de celebracion del matrimonio.",
            "Ultimo domicilio conyugal o domicilio actual del otro conyuge.",
            "Existencia de hijos menores o con capacidad restringida.",
            "Bienes gananciales, vivienda familiar y deudas comunes.",
            "Propuesta reguladora sobre alimentos, cuidado y atribucion de vivienda.",
            "Existencia de compensacion economica a reclamar o descartar.",
        ],
        "risks": [
            "La omision de la propuesta reguladora impide dar tramite a la peticion.",
            "La falta de precision sobre hijos, vivienda o bienes puede judicializar mas intensamente los efectos del divorcio.",
            "Un error en la competencia o en el domicilio del otro conyuge puede demorar el inicio del tramite.",
        ],
        "suggested_strategy": (
            "Presentar la peticion unilateral con propuesta reguladora completa, "
            "documentar con precision el domicilio relevante y anticipar los puntos "
            "de probable controversia sobre hijos, alimentos, vivienda y patrimonio."
        ),
    },
    "alimentos_hijos": {
        "summary": (
            "Reclamo de alimentos a favor de hijo o hijos contra progenitor que "
            "incumple la obligacion alimentaria."
        ),
        "legal_issue": (
            "Determinacion de la obligacion alimentaria del progenitor incumplidor, "
            "su legitimacion pasiva, alcance, retroactividad y prueba del incumplimiento."
        ),
        "main_claim": (
            "Demanda de alimentos a favor del hijo con fijacion de cuota, "
            "eventual retroactividad y medidas para asegurar el cumplimiento."
        ),
        "facts": [
            "Existe un hijo o hija cuyo sostenimiento depende de uno o ambos progenitores.",
            "Uno de los progenitores no cumple total o parcialmente con los alimentos.",
            "El progenitor conviviente o representante legal evalua iniciar reclamo judicial.",
        ],
        "applicable_rules": [
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="658",
                description="Regla general sobre la obligacion alimentaria derivada de la responsabilidad parental.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="659",
                description="Contenido y extension de los alimentos debidos al hijo.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="660",
                description="Valor economico de las tareas cotidianas del progenitor conviviente.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="661",
                description="Legitimacion para demandar al progenitor incumplidor.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="662",
                description="Facultades judiciales para fijar cuota y modalidad de pago.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="663",
                description="Medidas para asegurar el cumplimiento de la cuota alimentaria.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="664",
                description="Alimentos y gastos del hijo no conviviente o regimen de cuidado.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="669",
                description="Alimentos impagos y retroactividad desde demanda o interpelacion fehaciente.",
            ),
        ],
        "missing_information": [
            "Edad del hijo o hijos y vinculo filial acreditable.",
            "Con quien convive actualmente el hijo y cual es el regimen de cuidado.",
            "Ingresos estimados del progenitor incumplidor y necesidades concretas del hijo.",
            "Pagos parciales previos, deuda acumulada e intimaciones realizadas.",
            "Gastos ordinarios y extraordinarios de salud, educacion, vivienda y cuidado.",
        ],
        "risks": [
            "Sin prueba minima de ingresos, necesidades o incumplimiento la cuota puede fijarse con informacion incompleta.",
            "La falta de interpelacion fehaciente puede limitar reclamos retroactivos previos a la demanda.",
            "Si no se individualizan gastos y modalidad de cuidado, la pretension puede quedar subfundada.",
        ],
        "suggested_strategy": (
            "Reunir partidas, constancias de convivencia, comprobantes de gastos e "
            "indicios de ingresos del progenitor demandado para promover demanda "
            "de alimentos con pedido de cuota provisoria y medidas de aseguramiento si corresponden."
        ),
    },
    "sucesion_ab_intestato": {
        "summary": (
            "Inicio de sucesion intestada para obtener declaratoria de herederos "
            "y habilitar la administracion y transmision del acervo hereditario."
        ),
        "legal_issue": (
            "Apertura de la sucesion por fallecimiento del causante, acreditacion "
            "del vinculo hereditario y tramite de declaratoria de herederos."
        ),
        "main_claim": (
            "Promocion de sucesion ab intestato con apertura del proceso "
            "y dictado de declaratoria de herederos."
        ),
        "facts": [
            "Ha fallecido una persona cuyo patrimonio requiere sucesion judicial.",
            "Los familiares desean iniciar el tramite sucesorio.",
            "En principio no se informa la existencia de testamento.",
        ],
        "applicable_rules": [
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="2277",
                description="Apertura de la sucesion y transmision hereditaria por causa de muerte.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="2280",
                description="Personas legitimadas para promover la sucesion.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="2288",
                description="Aceptacion o renuncia de la herencia y situacion de los herederos.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="2335",
                description="Objeto del proceso sucesorio y administracion del acervo.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="2336",
                description="Competencia territorial del proceso sucesorio.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="2340",
                description="Investidura de pleno derecho y alcance practico frente a terceros.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="2424",
                description="Orden sucesorio de descendientes y concurrencia hereditaria.",
            ),
            ApplicableRule(
                source_id="codigo_civil_comercial",
                article="2431",
                description="Derechos hereditarios del conyuge superstite.",
            ),
        ],
        "missing_information": [
            "Fecha y lugar de fallecimiento del causante.",
            "Ultimo domicilio real del causante para fijar competencia.",
            "Existencia o no de testamento.",
            "Identificacion completa de herederos forzosos y estado civil del causante.",
            "Bienes registrables, cuentas, inmuebles o deudas que integren el acervo.",
        ],
        "risks": [
            "Si no se acredita correctamente el ultimo domicilio del causante puede cuestionarse la competencia.",
            "La omision de herederos o del estado civil del causante puede demorar la declaratoria.",
            "La falta de documentacion basica impide avanzar con apertura de sucesion y oficios registrales.",
        ],
        "suggested_strategy": (
            "Reunir partida de defuncion, partidas que acrediten vinculos, datos del "
            "ultimo domicilio y un inventario preliminar de bienes para promover "
            "la sucesion ab intestato y solicitar declaratoria de herederos."
        ),
    },
}


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class CaseStructurer:
    """
    Transforma query + classification en CaseStructure.

    Metodos publicos:
      - structure(query, classification) -> CaseStructure
    """

    def __init__(self, default_jurisdiction: str = "jujuy") -> None:
        self._default_jurisdiction = default_jurisdiction

    # ---- Public API -------------------------------------------------------

    def structure(
        self,
        query: str,
        classification: Any = None,
        jurisdiction: Optional[str] = None,
        forum: Optional[str] = None,
        **kwargs: Any,
    ) -> CaseStructure:
        """Construye CaseStructure a partir de la consulta y clasificacion."""
        cls_dict = self._coerce_classification(classification)

        action_slug = cls_dict.get("action_slug", "generic")
        action_label = cls_dict.get("action_label", "Consulta juridica")
        resolved_forum = forum or cls_dict.get("forum", "civil")
        resolved_jurisdiction = (
            jurisdiction
            or cls_dict.get("jurisdiction")
            or self._default_jurisdiction
        )
        process_type = cls_dict.get("process_type", "ordinario")
        confidence = cls_dict.get("confidence_score", 0.0)

        definition = _CASE_DEFINITIONS.get(action_slug)

        if definition:
            return self._from_definition(
                definition=definition,
                action_slug=action_slug,
                action_label=action_label,
                forum=resolved_forum,
                process_type=process_type,
                jurisdiction=resolved_jurisdiction,
                confidence=confidence,
                query=query,
            )

        return self._generic_structure(
            query=query,
            action_slug=action_slug,
            action_label=action_label,
            forum=resolved_forum,
            process_type=process_type,
            jurisdiction=resolved_jurisdiction,
            confidence=confidence,
            cls_dict=cls_dict,
        )

    # ---- Internal ---------------------------------------------------------

    def _from_definition(
        self,
        definition: Dict[str, Any],
        action_slug: str,
        action_label: str,
        forum: str,
        process_type: str,
        jurisdiction: str,
        confidence: float,
        query: str,
    ) -> CaseStructure:
        rules = definition.get("applicable_rules", [])
        if rules and isinstance(rules[0], dict):
            rules = [ApplicableRule(**r) for r in rules]

        return CaseStructure(
            action_slug=action_slug,
            action_label=action_label,
            summary=definition["summary"],
            legal_issue=definition["legal_issue"],
            main_claim=definition["main_claim"],
            forum=forum,
            process_type=process_type,
            jurisdiction=jurisdiction,
            facts=list(definition.get("facts", [])),
            applicable_rules=list(rules),
            missing_information=cleanup_text_list(definition.get("missing_information", []), item_type="missing_info"),
            risks=cleanup_text_list(definition.get("risks", []), item_type="risk"),
            suggested_strategy=definition.get("suggested_strategy", ""),
            confidence_score=confidence,
        )

    def _generic_structure(
        self,
        query: str,
        action_slug: str,
        action_label: str,
        forum: str,
        process_type: str,
        jurisdiction: str,
        confidence: float,
        cls_dict: Dict[str, Any],
    ) -> CaseStructure:
        priority_articles = cls_dict.get("priority_articles", [])
        rules = [
            ApplicableRule(
                source_id=art.get("source_id", "desconocido"),
                article=str(art.get("article", "")),
                description=f"Articulo {art.get('article', '?')} — referenciado por la clasificacion.",
            )
            for art in priority_articles
            if isinstance(art, dict)
        ]

        return CaseStructure(
            action_slug=action_slug,
            action_label=action_label,
            summary=f"Consulta juridica: {query[:120]}",
            legal_issue=f"Cuestion juridica vinculada a {action_label.lower()} en fuero {forum}.",
            main_claim=f"Pretension relacionada con {action_label.lower()}.",
            forum=forum,
            process_type=process_type,
            jurisdiction=jurisdiction,
            facts=[f"El consultante plantea: {query[:200]}"],
            applicable_rules=rules,
            missing_information=cleanup_text_list([
                "Hechos relevantes del caso.",
                "Documentacion de respaldo.",
                "Partes involucradas y sus roles procesales.",
            ], item_type="missing_info"),
            risks=cleanup_text_list([
                "Sin informacion suficiente para evaluar riesgos especificos.",
            ], item_type="risk"),
            suggested_strategy=(
                "Relevar hechos completos del caso y documentacion antes de "
                "definir estrategia procesal."
            ),
            confidence_score=confidence,
            warnings=[
                "No se encontro un patron de caso especifico para esta consulta. "
                "La estructura generada es generica.",
            ],
        )

    @staticmethod
    def _coerce_classification(classification: Any) -> Dict[str, Any]:
        if classification is None:
            return {}
        if isinstance(classification, dict):
            return classification
        if hasattr(classification, "to_dict") and callable(classification.to_dict):
            return classification.to_dict()
        if hasattr(classification, "__dict__"):
            return vars(classification)
        return {}
