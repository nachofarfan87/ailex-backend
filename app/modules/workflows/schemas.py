"""
AILEX — Schemas del workflow jurídico integrado.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.api.schemas.contracts import ConfidenceLevel, MissingData, SourceCitationSchema
from app.modules.strategy.schemas import StrategyComparison, StrategyOption


class NormativeReference(BaseModel):
    """Una referencia normativa sugerida automáticamente."""

    source: str
    article: str
    label: str
    purpose: str
    match_type: str = ""       # "direct" | "inferred"
    confidence_score: float = 0.0


class WorkflowNotificationRequest(BaseModel):
    """Entrada del workflow integrado de respuesta a notificaciones."""

    texto: str = Field(description="Texto de la notificación o situación procesal")
    datos_caso: Optional[dict] = Field(
        default=None,
        description="Datos opcionales del caso para enriquecer generación y revisión",
    )
    fuero: Optional[str] = Field(default=None, description="Fuero si se conoce")
    materia: Optional[str] = Field(default=None, description="Materia si se conoce")
    tipo_proceso: Optional[str] = Field(
        default=None,
        description="Tipo de proceso o encuadre procesal si se conoce",
    )
    etapa_procesal: Optional[str] = Field(
        default=None,
        description="Etapa procesal si se conoce",
    )
    objetivo_usuario: Optional[str] = Field(
        default=None,
        description="Objetivo táctico o práctico del abogado",
    )
    generar_borrador: bool = Field(
        default=True,
        description="Si True, intenta generar un borrador cuando exista sugerencia compatible",
    )
    variante_borrador: str = Field(
        default="estandar",
        description="Variante del generador si se habilita borrador",
    )
    session_id: Optional[str] = Field(default=None, description="ID de sesión")


class SuggestedDocumentInfo(BaseModel):
    tipo_escrito: Optional[str] = None
    razon: str = ""
    disponible_en_generador: bool = False
    borrador_generado: bool = False
    motivo_no_generado: Optional[str] = None


class ReviewSummary(BaseModel):
    diagnostico_general: Optional[str] = None
    severidad_general: Optional[str] = None
    hallazgos_clave: list[str] = Field(default_factory=list)
    mejoras_sugeridas: list[str] = Field(default_factory=list)
    version_sugerida: Optional[str] = None


class WorkflowNotificationResponse(BaseModel):
    document_detected: str = ""
    court: str = ""
    case_number: str = ""
    notification_date: str = ""
    procedural_action: str = ""
    deadline: str = ""
    critical_date: str = ""
    procedural_risks: list[str] = Field(default_factory=list)
    recommended_next_step: str = ""
    observations: str = ""
    relevant_sources: list[SourceCitationSchema] = Field(default_factory=list)
    confidence: str = "low"
    resumen_caso: str
    datos_extraidos: dict = Field(default_factory=dict)
    actuacion_detectada: Optional[str] = None
    plazo_detectado: Optional[str] = None
    vencimiento_estimado: Optional[str] = None
    # V1 deadline calculation fields
    estimated_due_date: str = ""
    deadline_type: str = ""
    deadline_basis: str = ""
    deadline_warning: str = ""
    riesgos_inmediatos: list[str] = Field(default_factory=list)
    opciones_estrategicas_resumidas: list[StrategyOption] = Field(default_factory=list)
    comparacion_opciones: list[StrategyComparison] = Field(default_factory=list)
    tipo_escrito_sugerido: SuggestedDocumentInfo
    borrador_inicial: Optional[str] = None
    observaciones_revision: ReviewSummary = Field(default_factory=ReviewSummary)
    fuentes_respaldo: list[SourceCitationSchema] = Field(default_factory=list)
    datos_faltantes: list[MissingData] = Field(default_factory=list)
    nivel_confianza_global: ConfidenceLevel = ConfidenceLevel.SIN_RESPALDO
    confianza_score_global: float = Field(default=0.0, ge=0.0, le=1.0)
    # Normative citation fields
    normative_references: list[NormativeReference] = Field(default_factory=list)
    normative_confidence: Optional[str] = None
    normative_warning: Optional[str] = None
    normative_summary: Optional[str] = None
