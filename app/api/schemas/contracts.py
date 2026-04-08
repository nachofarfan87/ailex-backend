"""
AILEX - Contrato comun de respuesta juridica.

Todas las salidas de analisis, generacion, revision y estrategia
deben cumplir con esta estructura para garantizar consistencia
y trazabilidad.

FORMATO OBLIGATORIO DE SALIDA - 8 secciones canonicas:
  resumen_ejecutivo | hechos_relevantes | encuadre_preliminar
  acciones_sugeridas | riesgos_observaciones | fuentes_respaldo
  datos_faltantes | nivel_confianza
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """
    Tipo de fuente documental.
    Determina el peso relativo, uso en argumentacion y jerarquia juridica.

    Vinculante (mayor peso): codigo, ley, reglamento, acordada
    Referencial: jurisprudencia, doctrina
    Interno (sin peso formal): escritos_estudio, plantillas
    """

    CODIGO = "codigo"
    LEY = "ley"
    REGLAMENTO = "reglamento"
    ACORDADA = "acordada"
    JURISPRUDENCIA = "jurisprudencia"
    DOCTRINA = "doctrina"
    ESCRITOS_ESTUDIO = "escritos_estudio"
    PLANTILLAS = "plantillas"


class SourceHierarchy(str, Enum):
    """
    Jerarquia de fuentes documentales.
    Diferencia el peso argumental de cada tipo de fuente.
    """

    NORMATIVA = "normativa"
    JURISPRUDENCIA = "jurisprudencia"
    DOCTRINA = "doctrina"
    INTERNO = "interno"


class ConfidenceLevel(str, Enum):
    """Niveles de confianza categorizados."""

    ALTO = "alto"
    MEDIO = "medio"
    BAJO = "bajo"
    SIN_RESPALDO = "sin_respaldo"


class InformationType(str, Enum):
    """
    Clasificacion de cada dato en la respuesta.
    Obligatorio diferenciar para cumplir principios del sistema.
    """

    EXTRAIDO = "extraido"
    INFERENCIA = "inferencia"
    SUGERENCIA = "sugerencia"


class SourceCitationSchema(BaseModel):
    """Cita puntual a una fuente documental."""

    document_id: Optional[str] = None
    document_title: str
    source_hierarchy: SourceHierarchy
    fragment: str = Field(description="Fragmento textual relevante de la fuente")
    page_or_section: Optional[str] = None
    relevance_score: float = Field(ge=0.0, le=1.0, description="Relevancia 0-1")


class TaggedFact(BaseModel):
    """Hecho con clasificacion de tipo de informacion."""

    content: str
    info_type: InformationType
    source: Optional[SourceCitationSchema] = None


class SuggestedAction(BaseModel):
    """Accion sugerida con clasificacion y riesgos."""

    action: str
    info_type: InformationType = InformationType.SUGERENCIA
    priority: Optional[str] = None
    risk: Optional[str] = None


class MissingData(BaseModel):
    """Dato faltante detectado."""

    description: str
    impact: str = Field(description="Impacto de la ausencia de este dato")
    required_for: Optional[str] = None


class CaseWorkspaceFactItem(BaseModel):
    key: str
    label: str = ""
    value: Any | None = None
    source: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    category: str = ""
    priority: str = ""
    purpose: str = ""


class CaseWorkspaceConflictItem(BaseModel):
    key: str
    label: str = ""
    prev_value: Any | None = None
    new_value: Any | None = None
    detected_at: int | None = None


class CaseWorkspaceStrategySnapshot(BaseModel):
    strategy_mode: str = ""
    response_goal: str = ""
    reason: str = ""
    output_mode: str = ""
    recommended_tone: str = ""
    recommended_structure: str = ""
    allow_followup: bool = False
    prioritize_action: bool = False


class CaseWorkspacePrimaryFocus(BaseModel):
    type: str = ""
    label: str = ""
    reason: str = ""


class CaseWorkspaceActionItem(BaseModel):
    id: str
    step_id: str = ""
    title: str
    description: str = ""
    priority: str = "medium"
    status: str = "pending"
    is_primary: bool = False
    phase: str = ""
    phase_label: str = ""
    blocked_by_missing_info: bool = False
    why_now: str = ""
    depends_on: list[str] = Field(default_factory=list)
    why_it_matters: str = ""
    source_hint: Optional[str] = None


class CaseWorkspaceEvidenceItem(BaseModel):
    key: str
    label: str
    description: str = ""
    reason: str = ""
    missing_level: str = "recommended"
    priority_rank: int = 0
    evidence_role: str = ""
    why_it_matters: str = ""
    resolves: list[str] = Field(default_factory=list)
    supports_step: str = ""


class CaseWorkspaceEvidenceChecklist(BaseModel):
    critical: list[CaseWorkspaceEvidenceItem] = Field(default_factory=list)
    recommended: list[CaseWorkspaceEvidenceItem] = Field(default_factory=list)
    optional: list[CaseWorkspaceEvidenceItem] = Field(default_factory=list)


class CaseWorkspaceRiskAlert(BaseModel):
    type: str
    severity: str = "medium"
    message: str
    source: str = ""


class ProfessionalHandoff(BaseModel):
    ready_for_professional_review: bool = False
    status: str = ""
    review_readiness: str = ""
    handoff_reason: str = ""
    primary_friction: str = ""
    recommended_professional_focus: str = ""
    professional_entry_point: str = ""
    suggested_focus: str = ""
    open_items: list[str] = Field(default_factory=list)
    next_question: str = ""
    summary_for_professional: str = ""


class CaseWorkspace(BaseModel):
    case_id: str
    workspace_version: str
    case_status: str
    case_status_label: str = ""
    case_status_helper: str = ""
    operating_phase: str = ""
    recommended_phase: str = ""
    recommended_phase_label: str = ""
    operating_phase_reason: str = ""
    primary_focus: CaseWorkspacePrimaryFocus = Field(default_factory=CaseWorkspacePrimaryFocus)
    case_summary: str
    facts_confirmed: list[CaseWorkspaceFactItem] = Field(default_factory=list)
    facts_missing: list[CaseWorkspaceFactItem] = Field(default_factory=list)
    facts_conflicting: list[CaseWorkspaceConflictItem] = Field(default_factory=list)
    strategy_snapshot: CaseWorkspaceStrategySnapshot = Field(default_factory=CaseWorkspaceStrategySnapshot)
    action_plan: list[CaseWorkspaceActionItem] = Field(default_factory=list)
    evidence_checklist: CaseWorkspaceEvidenceChecklist = Field(default_factory=CaseWorkspaceEvidenceChecklist)
    risk_alerts: list[CaseWorkspaceRiskAlert] = Field(default_factory=list)
    recommended_next_question: str = ""
    professional_handoff: ProfessionalHandoff = Field(default_factory=ProfessionalHandoff)
    last_updated_at: str


class JuridicalResponse(BaseModel):
    """
    Contrato comun de respuesta juridica.

    Toda salida de los modulos de analisis, generacion,
    revision y estrategia DEBE seguir esta estructura.

    Las 8 secciones canonicas son obligatorias (pueden estar vacias
    con justificacion, pero deben estar presentes).
    """

    resumen_ejecutivo: str = Field(description="Resumen ejecutivo de la respuesta")
    hechos_relevantes: list[TaggedFact] = Field(default_factory=list)
    encuadre_preliminar: list[str] = Field(default_factory=list)
    acciones_sugeridas: list[SuggestedAction] = Field(default_factory=list)
    riesgos_observaciones: list[str] = Field(default_factory=list)
    fuentes_respaldo: list[SourceCitationSchema] = Field(default_factory=list)
    datos_faltantes: list[MissingData] = Field(default_factory=list)
    nivel_confianza: ConfidenceLevel = ConfidenceLevel.SIN_RESPALDO
    confianza_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Score numerico de confianza (0-1). Derivado automaticamente.",
    )
    modulo_origen: str = Field(description="Modulo que genero esta respuesta")
    session_id: Optional[str] = None
    advertencia_general: Optional[str] = Field(
        default=(
            "Esta respuesta es asistencia profesional orientativa. "
            "No sustituye el criterio del abogado. "
            "Verifique todas las fuentes citadas antes de actuar."
        ),
        description="Disclaimer obligatorio",
    )
