"""
AILEX -- ProceduralStrategy

Design rationale:
  Converts a legal query + reasoning result into a structured procedural plan
  for Argentine civil/commercial practice, with a focus on Jujuy.

  Two complementary knowledge sources:
    1. Embedded knowledge base (PROCEDURAL_KB)
       A curated table of common Argentine procedural situations with known
       deadlines, steps, and risks.  Entirely static: no external calls,
       no LLM, completely deterministic.

    2. Context-driven inference
       When the reasoning result contains relevant normative grounds, the
       plan extracts actionable steps and risks from those articles.

  Design constraints:
    - NEVER affirm facts that are not provided.
    - NEVER invent deadlines that are not in the KB or context.
    - Prudent language: "verificar", "en principio", "consultar".
    - Missing information is flagged explicitly, not silently assumed.

  Output:
    ProceduralPlan -- steps, risks, missing_info, strategic_notes, warnings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from legal_engine.action_classifier import ActionClassification
from legal_engine.legal_reasoner import ReasoningResult
from legal_engine.output_cleanup import cleanup_text_list


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

URGENCY_IMMEDIATE = "immediate"
URGENCY_SOON      = "soon"
URGENCY_NORMAL    = "normal"
URGENCY_WHEN_AVBL = "when_available"


@dataclass
class ProceduralStep:
    """A single actionable step in a legal procedural plan."""
    order:         int
    action:        str
    deadline_hint: str | None    # e.g. "15 dias habiles desde notificacion"
    urgency:       str           # immediate / soon / normal / when_available
    notes:         str

    def to_dict(self) -> dict[str, Any]:
        return {
            "order":         self.order,
            "action":        self.action,
            "deadline_hint": self.deadline_hint,
            "urgency":       self.urgency,
            "notes":         self.notes,
        }


@dataclass
class ProceduralPlan:
    """
    Structured procedural guidance for a legal query.

    Attributes:
        query:             Original user query.
        domain:            Legal domain of the plan.
        jurisdiction:      Target jurisdiction.
        steps:             Ordered list of actionable steps.
        risks:             Procedural risks to flag to the lawyer.
        missing_info:      Information needed but not provided in the query.
        strategic_notes:   High-level strategic considerations.
        citations_used:    Normative citations that inform the plan.
        warnings:          Non-fatal issues.
    """
    query:           str
    domain:          str
    jurisdiction:    str
    steps:           list[ProceduralStep]
    risks:           list[str]
    missing_info:    list[str]
    strategic_notes: str
    citations_used:  list[str]
    warnings:        list[str]

    def to_dict(self) -> dict[str, Any]:
        next_steps = []
        for step in self.steps:
            rendered = step.action
            if step.deadline_hint:
                rendered = f"{rendered} ({step.deadline_hint})"
            next_steps.append(rendered)
        return {
            "query":           self.query,
            "domain":          self.domain,
            "jurisdiction":    self.jurisdiction,
            "steps":           [s.to_dict() for s in self.steps],
            "next_steps":      next_steps,
            "risks":           self.risks,
            "missing_info":    self.missing_info,
            "missing_information": self.missing_info,
            "strategic_notes": self.strategic_notes,
            "citations_used":  self.citations_used,
            "warnings":        self.warnings,
        }

    def has_immediate_steps(self) -> bool:
        return any(s.urgency == URGENCY_IMMEDIATE for s in self.steps)

    def is_empty(self) -> bool:
        return not self.steps


# ---------------------------------------------------------------------------
# Embedded procedural knowledge base
# ---------------------------------------------------------------------------
# Each entry maps a situation pattern to a template plan.
# Field "triggers" is a list of lowercase keywords/phrases to match.

_PROCEDURAL_KB: list[dict] = [

    # -- Traslado de demanda / contestacion ------------------------------------
    {
        "id": "contestacion_demanda",
        "triggers": ["contestar", "contestacion", "traslado", "demanda", "plazo contestar"],
        "domain": "procedural",
        "steps": [
            {
                "action": "Verificar fecha de notificacion y calcular plazo",
                "deadline_hint": "El plazo comienza a correr desde el dia siguiente a la notificacion.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "En CPCC Jujuy el plazo ordinario para contestar demanda es de 15 dias habiles. "
                         "Verificar si el proceso es sumarisimo (5 dias) u ordinario.",
            },
            {
                "action": "Preparar escrito de contestacion de demanda",
                "deadline_hint": "Antes del vencimiento del plazo de contestacion.",
                "urgency": URGENCY_SOON,
                "notes": "El escrito debe negar o reconocer los hechos, oponer excepciones si corresponde, "
                         "y ofrecer prueba.",
            },
            {
                "action": "Oponer excepciones previas si corresponde",
                "deadline_hint": "Junto con o antes de la contestacion, segun el tipo.",
                "urgency": URGENCY_SOON,
                "notes": "Excepciones de falta de personeria, incompetencia, prescripcion, etc.",
            },
            {
                "action": "Ofrecer prueba",
                "deadline_hint": "Con la contestacion de demanda.",
                "urgency": URGENCY_NORMAL,
                "notes": "Individualizar testigos, acompañar documental, solicitar pericias.",
            },
        ],
        "risks": [
            "Vencimiento del plazo: si se pierde, el demandado puede ser declarado en rebeldia.",
            "No oponer excepciones en tiempo: se pierde la oportunidad procesal.",
            "No ofrecer prueba en la contestacion: puede no haber otra oportunidad.",
        ],
        "missing_info": [
            "Fecha exacta de notificacion del traslado.",
            "Tipo de proceso (ordinario, sumarisimo, laboral).",
            "Fuero (civil, laboral, familia).",
        ],
        "strategic_notes": (
            "Priorizar la verificacion del plazo antes de cualquier otra accion. "
            "Un dia de diferencia puede ser determinante. "
            "Consultar el expediente digital o cedula de notificacion."
        ),
    },

    # -- Recurso de apelacion --------------------------------------------------
    {
        "id": "recurso_apelacion",
        "triggers": ["apelar", "apelacion", "recurrir", "recurso", "sentencia", "resolución"],
        "domain": "procedural",
        "steps": [
            {
                "action": "Verificar resolucion/sentencia y plazo de apelacion",
                "deadline_hint": "El plazo para apelar en CPCC Jujuy es de 5 dias habiles desde la notificacion.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "El plazo es perentorio. Verificar si la sentencia es definitiva o interlocutoria.",
            },
            {
                "action": "Interponer recurso de apelacion en tiempo y forma",
                "deadline_hint": "Dentro de los 5 dias habiles de notificada la sentencia/resolucion.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "Indicar los agravios al interponer o en la expresion de agravios, segun la norma local.",
            },
            {
                "action": "Expresar agravios ante la Camara",
                "deadline_hint": "El plazo lo fija la Camara o la norma procesal local.",
                "urgency": URGENCY_SOON,
                "notes": "Fundar el recurso con precision. Los agravios deben ser concretos y referidos a la sentencia.",
            },
        ],
        "risks": [
            "Consentimiento tacito: si no se apela en plazo, la sentencia queda firme.",
            "Desercion del recurso: si no se expresan agravios en tiempo, el recurso se tiene por desierto.",
        ],
        "missing_info": [
            "Fecha de notificacion de la sentencia/resolucion.",
            "Tipo de resolucion (interlocutoria, definitiva, providencia simple).",
        ],
        "strategic_notes": (
            "Interponer el recurso es prioritario incluso si los fundamentos no estan del todo elaborados. "
            "Se puede ampliar en la expresion de agravios."
        ),
    },

    # -- Notificacion ----------------------------------------------------------
    {
        "id": "notificacion",
        "triggers": ["notificacion", "notificar", "cedula", "emplazamiento"],
        "domain": "procedural",
        "steps": [
            {
                "action": "Verificar la forma de notificacion exigida",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Determinar si la notificacion debe ser por cedula, edictos, personalmente, etc.",
            },
            {
                "action": "Confeccionar la cedula o instrumento de notificacion",
                "deadline_hint": "Segun el plazo ordenado por el juez.",
                "urgency": URGENCY_NORMAL,
                "notes": "Incluir todos los datos requeridos: juzgado, expediente, objeto, domicilio.",
            },
            {
                "action": "Diligenciar la notificacion y agregar constancia al expediente",
                "deadline_hint": "Dentro del plazo fijado en la providencia.",
                "urgency": URGENCY_NORMAL,
                "notes": "La notificacion mal diligenciada puede ser nula.",
            },
        ],
        "risks": [
            "Nulidad de notificacion: si el domicilio o los datos son incorrectos.",
            "Incumplimiento del plazo fijado por el tribunal.",
        ],
        "missing_info": [
            "Tipo de notificacion ordenada.",
            "Domicilio del destinatario.",
            "Providencia que ordena la notificacion.",
        ],
        "strategic_notes": (
            "Verificar el domicilio antes de confeccionar la cedula. "
            "En Jujuy, confirmar si se puede notificar electronicamente."
        ),
    },

    # -- Caducidad de instancia -----------------------------------------------
    {
        "id": "caducidad_instancia",
        "triggers": ["caducidad", "caducar", "instancia", "perimir"],
        "domain": "procedural",
        "steps": [
            {
                "action": "Verificar fecha del ultimo acto impulsorio",
                "deadline_hint": "Caducidad opera si transcurren los plazos sin acto impulsorio.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "En proceso ordinario, el plazo tipico es de 6 meses (primera instancia). "
                         "Verificar plazo exacto en CPCC Jujuy.",
            },
            {
                "action": "Si el plazo no vencio: impulsar el proceso inmediatamente",
                "deadline_hint": "Antes del vencimiento del plazo de caducidad.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "Cualquier acto de impulso procesal interrumpe la caducidad.",
            },
            {
                "action": "Si el plazo vencio: evaluar si es posible oponer la caducidad",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "La caducidad puede ser declarada de oficio o a pedido de parte.",
            },
        ],
        "risks": [
            "Perda del proceso por falta de impulso.",
            "La caducidad extingue la instancia pero no el derecho de fondo (en principio).",
        ],
        "missing_info": [
            "Fecha del ultimo acto procesal en el expediente.",
            "Tipo de proceso y etapa procesal actual.",
        ],
        "strategic_notes": (
            "Revisar el expediente con urgencia para verificar el ultimo acto impulsorio. "
            "Si esta proximo el plazo, actuar inmediatamente."
        ),
    },

    # -- Medida cautelar -------------------------------------------------------
    {
        "id": "medida_cautelar",
        "triggers": ["cautelar", "embargo", "inhibicion", "medida", "preventiva"],
        "domain": "procedural",
        "steps": [
            {
                "action": "Evaluar procedencia y tipo de medida cautelar",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Verificar: peligro en la demora, verosimilitud del derecho, contracautela.",
            },
            {
                "action": "Redactar y presentar el pedido de medida cautelar",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Fundar en los presupuestos cautelares. Indicar el tipo de medida y bien a afectar.",
            },
            {
                "action": "Ofrecer contracautela si el juez lo exige",
                "deadline_hint": "Al momento de solicitar o al ser otorgada la medida.",
                "urgency": URGENCY_NORMAL,
                "notes": "Puede ser: juratoria, personal o real.",
            },
        ],
        "risks": [
            "Responsabilidad por abuso cautelar si la medida es excesiva.",
            "Levantamiento de la medida si no se cumple con la contracautela.",
        ],
        "missing_info": [
            "Existencia y estado de proceso principal.",
            "Bien o cuenta a cautelar.",
            "Acreditacion de verosimilitud del derecho.",
        ],
        "strategic_notes": (
            "Las medidas cautelares se resuelven inaudita parte. "
            "La urgencia y la verosimilitud son los factores clave para su otorgamiento."
        ),
    },
]

# ---------------------------------------------------------------------------
# Trigger index for fast lookup
# ---------------------------------------------------------------------------

def _build_trigger_index(kb: list[dict]) -> list[tuple[set[str], dict]]:
    return [(set(entry["triggers"]), entry) for entry in kb]


_KB_INDEX = _build_trigger_index(_PROCEDURAL_KB)

_CLASSIFIED_ACTION_PLANS: dict[str, dict[str, Any]] = {
    "divorcio_mutuo_acuerdo": {
        "domain": "family",
        "steps": [
            {
                "action": "Confirmar competencia del juzgado de familia en Jujuy y ultimo domicilio conyugal",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Verificar si corresponde presentacion conjunta conforme a la competencia prevista para divorcio.",
            },
            {
                "action": "Preparar peticion conjunta de divorcio con propuesta reguladora",
                "deadline_hint": "Presentar junto con la solicitud inicial.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La peticion debe acompanar la propuesta que regule los efectos del divorcio.",
            },
            {
                "action": "Definir contenido del convenio regulador",
                "deadline_hint": "Antes de la presentacion judicial.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "Revisar vivienda, bienes, compensaciones economicas, responsabilidad parental y alimentos si corresponde.",
            },
            {
                "action": "Reunir documentacion del matrimonio e informacion patrimonial y familiar relevante",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Adjuntar partida de matrimonio y datos necesarios para sostener la propuesta reguladora.",
            },
        ],
        "risks": [
            "La omision de la propuesta reguladora impide dar tramite a la peticion de divorcio.",
            "Un convenio regulador incompleto puede generar observaciones judiciales o litigios posteriores sobre sus efectos.",
            "Si existen hijos o bienes comunes, la falta de precision en alimentos, cuidado o atribucion de vivienda debilita la estrategia.",
        ],
        "missing_info": [
            "Fecha y lugar del matrimonio.",
            "Ultimo domicilio conyugal o domicilio actual de las partes.",
            "Existencia de hijos menores o con capacidad restringida.",
            "Bienes comunes, vivienda familiar y eventual compensacion economica.",
        ],
        "strategic_notes": (
            "En divorcio por mutuo acuerdo conviene presentar una propuesta reguladora completa y consistente. "
            "Si ya existe consenso sustancial, el foco debe ponerse en documentar adecuadamente vivienda, bienes, alimentos y cuidado personal."
        ),
    },
    "divorcio": {
        "domain": "family",
        "steps": [
            {
                "action": "Confirmar si el divorcio se promovera de modo conjunto o unilateral",
                "deadline_hint": "Antes de definir el escrito inicial.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La consulta ya encuadra en materia de divorcio, pero la variante procesal depende del nivel de acuerdo con el otro conyuge.",
            },
            {
                "action": "Reunir datos del matrimonio, domicilios y base de la propuesta reguladora",
                "deadline_hint": None,
                "urgency": URGENCY_IMMEDIATE,
                "notes": "Fecha del matrimonio, ultimo domicilio conyugal y efectos a regular son datos estructurales del caso.",
            },
            {
                "action": "Definir situacion de hijos, vivienda, bienes, alimentos y compensacion economica",
                "deadline_hint": "Antes de presentar la solicitud o peticion.",
                "urgency": URGENCY_SOON,
                "notes": "Estos puntos determinan si el divorcio tendra una salida mas consensual o mayor litigiosidad en sus efectos.",
            },
            {
                "action": "Preparar presentacion inicial de divorcio con encuadre y competencia correctos",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Una vez relevados los datos basicos, debe elegirse la via adecuada y ordenar la propuesta reguladora.",
            },
        ],
        "risks": [
            "Si no se define la variante procesal del divorcio, la preparacion del escrito inicial puede quedar incompleta.",
            "La falta de precision sobre hijos, vivienda o bienes puede desplazar el conflicto a los efectos del divorcio.",
            "Un error en competencia o domicilios relevantes puede retrasar el inicio del tramite.",
        ],
        "missing_info": [
            "Fecha y lugar del matrimonio.",
            "Ultimo domicilio conyugal y domicilios actuales relevantes.",
            "Si existe acuerdo del otro conyuge o si la via sera unilateral.",
            "Existencia de hijos menores, vivienda familiar y situacion patrimonial.",
        ],
        "strategic_notes": (
            "Ante una consulta nuclear de divorcio, el foco inicial es encuadrar el divorcio, definir su variante y ordenar los efectos familiares y patrimoniales."
        ),
    },
    "divorcio_unilateral": {
        "domain": "family",
        "steps": [
            {
                "action": "Verificar competencia del juzgado de familia y domicilio del otro conyuge",
                "deadline_hint": None,
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La presentacion unilateral exige una radicacion correcta y datos aptos para la notificacion.",
            },
            {
                "action": "Redactar peticion unilateral de divorcio con propuesta reguladora inicial",
                "deadline_hint": "Al promover la accion.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La falta de acuerdo del otro conyuge no impide el divorcio, pero la propuesta debe cubrir efectos relevantes.",
            },
            {
                "action": "Definir puntos potencialmente controvertidos sobre hijos, vivienda, bienes y alimentos",
                "deadline_hint": "Antes de la primera presentacion o junto con ella.",
                "urgency": URGENCY_SOON,
                "notes": "Conviene anticipar los aspectos que luego podrian judicializarse.",
            },
            {
                "action": "Evaluar medidas provisionales si existe urgencia familiar o patrimonial",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Puede ser necesario pedir atribucion de vivienda, cuidado o alimentos provisorios.",
            },
        ],
        "risks": [
            "La omision de la propuesta reguladora puede impedir dar tramite a la peticion inicial.",
            "Una notificacion defectuosa al otro conyuge retrasa el proceso y expone a nulidades.",
            "Si no se individualizan hijos, vivienda o bienes, los efectos del divorcio quedan mas expuestos a litigio posterior.",
        ],
        "missing_info": [
            "Ultimo domicilio conyugal y domicilio actual del otro conyuge.",
            "Existencia de hijos menores o con capacidad restringida.",
            "Situacion de la vivienda familiar, bienes y deudas comunes.",
            "Definicion sobre alimentos y compensacion economica.",
        ],
        "strategic_notes": (
            "El foco del divorcio unilateral no es probar causa, sino presentar una propuesta reguladora util y una base factica suficiente para sostener competencia, notificacion y eventuales medidas provisionales."
        ),
    },
    "alimentos_hijos": {
        "domain": "family",
        "steps": [
            {
                "action": "Reunir partida de nacimiento y prueba basica del vinculo filial",
                "deadline_hint": "Antes de iniciar la demanda.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La legitimacion y el parentesco deben acreditarse desde el inicio.",
            },
            {
                "action": "Documentar gastos del hijo e indicios de ingresos del progenitor incumplidor",
                "deadline_hint": None,
                "urgency": URGENCY_IMMEDIATE,
                "notes": "Comprobantes de salud, educacion, vivienda y gastos cotidianos fortalecen la cuantificacion de la cuota.",
            },
            {
                "action": "Promover demanda de alimentos con pedido de cuota provisoria",
                "deadline_hint": "Una vez reunida la documentacion minima.",
                "urgency": URGENCY_SOON,
                "notes": "Si la necesidad es actual, la cuota provisoria puede ser clave.",
            },
            {
                "action": "Evaluar intimacion previa y medidas de aseguramiento o retencion",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "La intimacion ayuda para retroactividad y las medidas cautelares sirven para asegurar cobro.",
            },
        ],
        "risks": [
            "Sin prueba minima de necesidades del hijo y capacidad economica del demandado, la cuota puede quedar subestimada.",
            "La falta de intimacion previa puede debilitar reclamos retroactivos anteriores a la demanda.",
            "Si no se explicita el regimen de convivencia o cuidado, la cuantificacion de la cuota puede quedar incompleta.",
        ],
        "missing_info": [
            "Edad del hijo y con quien convive actualmente.",
            "Detalle de gastos ordinarios y extraordinarios del hijo.",
            "Ingresos o indicios patrimoniales del progenitor incumplidor.",
            "Pagos parciales, deuda acumulada e intimaciones previas.",
        ],
        "strategic_notes": (
            "En alimentos de hijos conviene litigar con una base economica concreta: gastos demostrables, modalidad de cuidado y cualquier dato de ingresos del progenitor demandado."
        ),
    },
    "sucesion_ab_intestato": {
        "domain": "civil",
        "steps": [
            {
                "action": "Reunir partida de defuncion y documentacion que acredite parentesco",
                "deadline_hint": "Antes de iniciar la sucesion.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La apertura del proceso y la declaratoria requieren documentacion basica completa.",
            },
            {
                "action": "Determinar ultimo domicilio real del causante para fijar competencia",
                "deadline_hint": None,
                "urgency": URGENCY_IMMEDIATE,
                "notes": "Es un dato estructural del sucesorio y debe quedar documentado.",
            },
            {
                "action": "Preparar escrito de inicio de sucesion ab intestato y pedido de declaratoria de herederos",
                "deadline_hint": "Al contar con documentacion minima suficiente.",
                "urgency": URGENCY_SOON,
                "notes": "Conviene individualizar herederos, estado civil del causante y ausencia de testamento si se conoce.",
            },
            {
                "action": "Armar inventario preliminar de bienes, cuentas y deudas",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Facilita oficios registrales, administracion del acervo y pasos posteriores de particion.",
            },
        ],
        "risks": [
            "La falta de acreditacion del ultimo domicilio del causante puede generar cuestionamientos de competencia.",
            "La omision de herederos o del estado civil del causante demora la declaratoria.",
            "Sin individualizacion inicial de bienes y documentacion registral el tramite sucesorio pierde eficacia practica.",
        ],
        "missing_info": [
            "Ultimo domicilio real del causante.",
            "Identificacion completa de herederos y estado civil del causante.",
            "Existencia o no de testamento.",
            "Inventario preliminar de inmuebles, automotores, cuentas o deudas.",
        ],
        "strategic_notes": (
            "La apertura de la sucesion debe enfocarse en la documentacion habilitante y en un mapa inicial del acervo para obtener declaratoria de herederos sin observaciones evitables."
        ),
    },
}

_DOMAIN_PROCEDURAL_MAP: dict[str, dict[str, Any]] = {
    "conflicto_patrimonial": {
        "domain": "civil",
        "steps": [
            {
                "action": "Relevar titulo, asiento registral y origen del inmueble en disputa",
                "deadline_hint": "Antes de definir la via principal.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "Es necesario precisar si el bien es propio, ganancial o si hoy funciona como condominio.",
            },
            {
                "action": "Definir si la salida viable es convenio de adjudicacion, liquidacion de comunidad o division de condominio",
                "deadline_hint": "Con la informacion patrimonial basica ordenada.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La estrategia cambia segun exista acuerdo parcial, divorcio previo y origen del bien.",
            },
            {
                "action": "Reunir documentacion sobre divorcio, acuerdo previo y aportes o forma de adquisicion",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Conviene preparar la base documental antes de intimar, negociar o promover la accion patrimonial.",
            },
            {
                "action": "Evaluar presentacion patrimonial especifica una vez delimitado el conflicto",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "La salida judicial o negocial debe corresponder al encuadre real del inmueble y del vinculo entre las partes.",
            },
        ],
        "risks": [
            "Si no se define el origen del bien, puede elegirse una via patrimonial incorrecta.",
            "Pedir una renuncia sin acuerdo o sin encuadre previo puede volver inviable la estrategia.",
            "La falta de documentacion registral o del antecedente de divorcio debilita cualquier reclamo sobre adjudicacion o liquidacion.",
        ],
        "missing_info": [
            "Si el bien fue adquirido antes o durante el matrimonio.",
            "Si el inmueble proviene de compra, herencia o adjudicacion previa.",
            "Si existe divorcio firme, acuerdo patrimonial o conflicto abierto.",
            "Si la solucion buscada es adjudicacion, liquidacion o division del condominio.",
        ],
        "strategic_notes": (
            "Cuando hay cotitularidad o conflicto patrimonial claro, primero hay que fijar el encuadre del inmueble y recien despues elegir entre convenio, liquidacion o division."
        ),
    },
    "divorcio": _CLASSIFIED_ACTION_PLANS["divorcio"],
    "alimentos": _CLASSIFIED_ACTION_PLANS["alimentos_hijos"],
    "cuidado_personal": {
        "domain": "family",
        "steps": [
            {
                "action": "Precisar centro de vida, rutina y organizacion actual del cuidado del nino",
                "deadline_hint": "Antes de cualquier acuerdo o presentacion.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La estrategia depende de quien sostiene efectivamente el cuidado cotidiano y con que estabilidad.",
            },
            {
                "action": "Reunir constancias de escuela, salud, convivencia y referentes de cuidado",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Sirve para sostener una propuesta concreta de cuidado personal.",
            },
            {
                "action": "Definir si conviene una salida acordada o una peticion judicial focalizada en el cuidado",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "La via debe reflejar el grado de conflicto y la urgencia del nino.",
            },
        ],
        "risks": [
            "Sin prueba del centro de vida y de la rutina actual, la pretension sobre cuidado puede quedar abstracta.",
            "Una propuesta imprecisa sobre tiempos y responsabilidades puede derivar en mayor litigiosidad.",
        ],
        "missing_info": [
            "Con quien vive actualmente el nino.",
            "Como se distribuyen hoy las tareas de cuidado.",
            "Si existe acuerdo previo o conflicto activo entre los progenitores.",
        ],
        "strategic_notes": (
            "La prioridad es describir el cuidado real y el centro de vida antes de definir la salida procesal."
        ),
    },
    "regimen_comunicacional": {
        "domain": "family",
        "steps": [
            {
                "action": "Precisar si hay impedimento, incumplimiento o necesidad de fijar un cronograma de contacto",
                "deadline_hint": "Antes de cualquier reclamo formal.",
                "urgency": URGENCY_IMMEDIATE,
                "notes": "La estrategia depende de si se busca restablecer, ordenar o ejecutar la comunicacion.",
            },
            {
                "action": "Reunir mensajes, constancias de incumplimientos y propuesta concreta de dias y horarios",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "La evidencia de obstrucciones y una propuesta ejecutable fortalecen el planteo.",
            },
            {
                "action": "Evaluar via acordada o judicial para fijar o hacer cumplir el regimen comunicacional",
                "deadline_hint": None,
                "urgency": URGENCY_SOON,
                "notes": "Conviene evitar pedidos vagos y enfocarse en un esquema concreto y verificable.",
            },
        ],
        "risks": [
            "Sin cronograma concreto, la pretension sobre comunicacion puede quedar indeterminada.",
            "La falta de constancias de obstruccion o incumplimiento debilita el reclamo.",
        ],
        "missing_info": [
            "Edad del nino y rutina actual.",
            "Si existe acuerdo previo o resolucion judicial sobre comunicacion.",
            "Hechos concretos de incumplimiento u obstruccion.",
        ],
        "strategic_notes": (
            "El foco debe estar en un regimen claro y ejecutable, apoyado en constancias objetivas de contacto o de su obstruccion."
        ),
    },
}


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProceduralStrategy:
    """
    Generates structured procedural plans from a query and reasoning result.

    Usage::

        strategy = ProceduralStrategy()
        plan = strategy.generate(
            query="plazo para contestar demanda",
            reasoning_result=result,
            jurisdiction="jujuy",
        )
        for step in plan.steps:
            print(step.urgency, step.action)
    """

    def __init__(self, default_jurisdiction: str = "jujuy") -> None:
        self._default_jurisdiction = default_jurisdiction

    # ---- Public API -------------------------------------------------------

    def plan(
        self,
        query:        str       = "",
        reasoning=    None,
        jurisdiction: str | None = None,
        classification: ActionClassification | dict[str, Any] | None = None,
        normative_reasoning: dict[str, Any] | None = None,
        case_structure: dict[str, Any] | None = None,
        case_domain: str | None = None,
        **_kwargs: Any,
    ) -> "ProceduralPlan":
        """
        Pipeline adapter.  Called by AilexPipeline as ``plan(query, reasoning,
        jurisdiction, ...)``.  Reconstructs a minimal ReasoningResult from
        the reasoning dict and delegates to :meth:`generate`.
        """
        rr: ReasoningResult | None = None
        if isinstance(reasoning, dict):
            try:
                rr = ReasoningResult(
                    query=               reasoning.get("query", query),
                    query_type=          reasoning.get("query_type", "procedure_query"),
                    short_answer=        reasoning.get("short_answer", ""),
                    normative_grounds=   [],
                    applied_analysis=    reasoning.get("applied_analysis", ""),
                    limitations=         reasoning.get("limitations") or [],
                    citations_used=      reasoning.get("citations_used") or [],
                    confidence=          str(reasoning.get("confidence", "low")),
                    confidence_score=    float(reasoning.get("confidence_score", 0.3)),
                    evidence_sufficient= bool(reasoning.get("evidence_sufficient", False)),
                    domain=              reasoning.get("domain", "procedural"),
                    jurisdiction=        str(reasoning.get("jurisdiction", jurisdiction or "jujuy")),
                    warnings=            reasoning.get("warnings") or [],
                )
            except Exception:
                rr = None
        return self.generate(
            query=query or "",
            reasoning_result=rr,
            jurisdiction=jurisdiction,
            classification=classification,
            normative_reasoning=normative_reasoning,
            case_structure=case_structure,
            case_domain=case_domain,
        )

    def generate(
        self,
        query:            str,
        reasoning_result: ReasoningResult | None = None,
        jurisdiction:     str | None             = None,
        classification:   ActionClassification | dict[str, Any] | None = None,
        normative_reasoning: dict[str, Any] | None = None,
        case_structure:   dict[str, Any] | None = None,
        case_domain:      str | None             = None,
    ) -> ProceduralPlan:
        """
        Generate a procedural plan for the given query.

        Args:
            query:            User's legal query.
            reasoning_result: Output of LegalReasoner (optional but recommended).
            jurisdiction:     Override jurisdiction.

        Returns:
            ProceduralPlan -- always well-formed.
        """
        warnings:     list[str] = []
        query         = (query or "").strip()
        jurisdiction  = (jurisdiction or self._default_jurisdiction).strip().lower()
        classification_obj = self._coerce_classification(classification)
        resolved_case_domain = str(case_domain or "").strip()

        if not query:
            warnings.append("Empty query provided to ProceduralStrategy.")
            return self._empty_plan(query, jurisdiction, warnings)

        domain = resolved_case_domain
        if not domain and classification_obj and classification_obj.domain:
            domain = classification_obj.domain
        if not domain and reasoning_result:
            domain = reasoning_result.domain
        domain = domain or "procedural"

        # Match KB entries
        matched_entries = self._match_kb(query)

        # Build citation list from reasoning result
        citations: list[str] = []
        if reasoning_result:
            citations = reasoning_result.citations_used or []
            if not reasoning_result.evidence_sufficient:
                warnings.append(
                    "Evidencia normativa insuficiente en el analisis. "
                    "El plan procesal es orientativo y requiere verificacion."
                )

        # Build the plan -- prefer _CLASSIFIED_ACTION_PLANS when action_slug is known
        classified_entry = None
        domain_entry = None
        if resolved_case_domain and resolved_case_domain != "generic":
            domain_entry = _DOMAIN_PROCEDURAL_MAP.get(resolved_case_domain)
        if classification_obj:
            classified_entry = _CLASSIFIED_ACTION_PLANS.get(classification_obj.action_slug)
        if not classified_entry and isinstance(classification, dict):
            classified_entry = _CLASSIFIED_ACTION_PLANS.get(classification.get("action_slug", ""))

        if domain_entry:
            best_entry = domain_entry
            steps = self._build_steps(best_entry, 1)
            risks = list(best_entry.get("risks", []))
            missing_info = list(best_entry.get("missing_info", []))
            strategic = best_entry.get("strategic_notes", "")
        elif classified_entry:
            best_entry = classified_entry
            steps = self._build_steps(best_entry, 1)
            risks = list(best_entry.get("risks", []))
            missing_info = list(best_entry.get("missing_info", []))
            strategic = best_entry.get("strategic_notes", "")
        elif matched_entries:
            best_entry   = matched_entries[0]
            steps        = self._build_steps(best_entry, len(matched_entries))
            risks        = list(best_entry.get("risks", []))
            missing_info = list(best_entry.get("missing_info", []))
            strategic    = best_entry.get("strategic_notes", "")
        else:
            steps, risks, missing_info, strategic = self._generic_plan(query, domain)
            if not resolved_case_domain or resolved_case_domain == "generic":
                warnings.append(
                    f"No se encontro un patron procesal especifico para: '{query}'. "
                    "Se genera un plan procesal generico."
                )

        # Enrich with context from reasoning result
        if reasoning_result and reasoning_result.normative_grounds:
            extra_risk, extra_missing = self._extract_from_grounds(reasoning_result)
            risks        = self._merge_unique(risks, extra_risk)
            missing_info = self._merge_unique(missing_info, extra_missing)

        # Enrich with normative reasoning
        if isinstance(normative_reasoning, dict):
            nr_unresolved = normative_reasoning.get("unresolved_issues") or []
            missing_info = self._merge_unique(missing_info, nr_unresolved)

            nr_requirements = normative_reasoning.get("requirements") or []
            for req in nr_requirements:
                if req not in missing_info:
                    missing_info.append(req)

            nr_warnings = normative_reasoning.get("warnings") or []
            for w in nr_warnings:
                warning_text = str(w)
                lowered_warning = warning_text.lower()
                if resolved_case_domain and resolved_case_domain != "generic":
                    if "fallback generico" in lowered_warning or "handler especifico" in lowered_warning:
                        continue
                if warning_text not in warnings:
                    warnings.append(warning_text)

        # Enrich with case structure risks
        if isinstance(case_structure, dict):
            cs_risks = case_structure.get("risks") or []
            risks = self._merge_unique(risks, cs_risks)

        # Jurisdiction disclaimer if not jujuy
        if jurisdiction != "jujuy":
            warnings.append(
                f"Plan basado en normativa de Jujuy. "
                f"Para jurisdiccion '{jurisdiction}' verificar plazos locales."
            )

        risks = cleanup_text_list(risks, item_type="risk")
        missing_info = cleanup_text_list(missing_info, item_type="missing_info")
        warnings = cleanup_text_list(warnings, item_type="warning")

        return ProceduralPlan(
            query=           query,
            domain=          domain,
            jurisdiction=    jurisdiction,
            steps=           steps,
            risks=           risks,
            missing_info=    missing_info,
            strategic_notes= strategic,
            citations_used=  citations,
            warnings=        warnings,
        )

    @staticmethod
    def _coerce_classification(
        classification: ActionClassification | dict[str, Any] | None,
    ) -> ActionClassification | None:
        if classification is None:
            return None
        if isinstance(classification, ActionClassification):
            return classification
        if isinstance(classification, dict) and classification.get("action_slug"):
            return ActionClassification(
                query=str(classification.get("query", "")),
                normalized_query=str(classification.get("normalized_query", "")),
                legal_intent=str(classification.get("legal_intent", "")),
                action_slug=str(classification.get("action_slug", "")),
                action_label=str(classification.get("action_label", "")),
                forum=str(classification.get("forum", "")),
                jurisdiction=str(classification.get("jurisdiction", "")),
                process_type=str(classification.get("process_type", "")),
                domain=str(classification.get("domain", "")),
                confidence_score=float(classification.get("confidence_score", 0.0)),
                matched_patterns=list(classification.get("matched_patterns") or []),
                semantic_aliases=list(classification.get("semantic_aliases") or []),
                retrieval_queries=list(classification.get("retrieval_queries") or []),
                priority_articles=list(classification.get("priority_articles") or []),
                metadata=dict(classification.get("metadata") or {}),
            )
        return None

    # ---- KB matching -------------------------------------------------------

    @staticmethod
    def _match_kb(query: str) -> list[dict]:
        """
        Return KB entries matching the query, ordered by number of trigger hits.
        """
        norm_q = _normalise(query)
        q_tokens = set(norm_q.split())

        scored: list[tuple[int, dict]] = []
        for trigger_set, entry in _KB_INDEX:
            # Check phrase triggers
            hits = sum(1 for t in trigger_set if t in norm_q or t in q_tokens)
            if hits > 0:
                scored.append((hits, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored]

    # ---- Step building -----------------------------------------------------

    @staticmethod
    def _build_steps(entry: dict, n_matches: int) -> list[ProceduralStep]:
        """Build ordered ProceduralStep objects from a KB entry."""
        steps = []
        for i, raw in enumerate(entry.get("steps", []), 1):
            steps.append(ProceduralStep(
                order=         i,
                action=        raw["action"],
                deadline_hint= raw.get("deadline_hint"),
                urgency=       raw.get("urgency", URGENCY_NORMAL),
                notes=         raw.get("notes", ""),
            ))
        return steps

    # ---- Generic fallback plan ---------------------------------------------

    @staticmethod
    def _generic_plan(
        query:  str,
        domain: str,
    ) -> tuple[list[ProceduralStep], list[str], list[str], str]:
        """Fallback plan when no KB entry matches."""
        steps = [
            ProceduralStep(
                order=1,
                action="Verificar encuadre procesal de la situacion",
                deadline_hint=None,
                urgency=URGENCY_SOON,
                notes=(
                    f"Identificar el tipo de proceso, fuero y jurisdiccion aplicables "
                    f"a: {query[:100]}."
                ),
            ),
            ProceduralStep(
                order=2,
                action="Consultar el expediente o antecedentes del caso",
                deadline_hint=None,
                urgency=URGENCY_SOON,
                notes="Reunir toda la documentacion disponible antes de tomar acciones procesales.",
            ),
            ProceduralStep(
                order=3,
                action="Consultar abogado especializado en la materia",
                deadline_hint=None,
                urgency=URGENCY_NORMAL,
                notes=(
                    "AILEX proporciona orientacion basada en corpus normativo. "
                    "Para casos especificos, la asistencia de un profesional es indispensable."
                ),
            ),
        ]
        risks = [
            "La falta de encuadre correcto puede llevar a estrategias inadecuadas.",
            "Actuar sin verificar plazos puede generar perjuicio procesal irreparable.",
        ]
        missing_info = [
            "Tipo de proceso y etapa procesal.",
            "Fecha de los hechos relevantes.",
            "Antecedentes del expediente.",
        ]
        strategic = (
            "Antes de cualquier accion procesal, identificar correctamente el tipo de "
            "situacion, el fuero competente y los plazos vigentes."
        )
        return steps, risks, missing_info, strategic

    # ---- Enrichment from reasoning result ----------------------------------

    @staticmethod
    def _extract_from_grounds(result: ReasoningResult) -> tuple[list[str], list[str]]:
        """Extract additional risks and missing_info from reasoning grounds."""
        extra_risks: list[str] = []
        extra_missing: list[str] = []

        if not result.evidence_sufficient:
            extra_risks.append(
                "Evidencia normativa incompleta: el plan procesal puede no cubrir "
                "todos los aspectos relevantes de la consulta."
            )
            extra_missing.append(
                "Normativa adicional que pueda aplicar al caso concreto."
            )

        if result.confidence == "low":
            extra_risks.append(
                "Confianza baja en el analisis normativo: verificar independientemente "
                "la normativa aplicable."
            )

        for lim in result.limitations[:2]:  # cap at 2 to avoid verbosity
            if lim not in extra_missing:
                extra_missing.append(lim)

        return extra_risks, extra_missing

    # ---- Helpers ----------------------------------------------------------

    @staticmethod
    def _merge_unique(base: list[str], additions: list[str]) -> list[str]:
        """Append items from additions that are not already in base."""
        base_lower = {s.lower() for s in base}
        result = list(base)
        for item in additions:
            if item.lower() not in base_lower:
                result.append(item)
                base_lower.add(item.lower())
        return result

    @staticmethod
    def _empty_plan(
        query:        str,
        jurisdiction: str,
        warnings:     list[str],
    ) -> ProceduralPlan:
        return ProceduralPlan(
            query=           query,
            domain=          "unknown",
            jurisdiction=    jurisdiction,
            steps=           [],
            risks=           [],
            missing_info=    [],
            strategic_notes= "",
            citations_used=  [],
            warnings=        warnings,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    nfkd   = unicodedata.normalize("NFKD", text)
    no_acc = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return " ".join(no_acc.casefold().split())
