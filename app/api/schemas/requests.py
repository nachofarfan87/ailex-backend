"""
AILEX — Esquemas de request para los endpoints jurídicos.

Todos los endpoints que producen JuridicalResponse
reciben un body tipado con estos schemas.
"""

from pydantic import BaseModel, Field
from typing import Optional


class AnalysisRequest(BaseModel):
    """Request para análisis de texto jurídico."""
    text: str = Field(
        description="Texto jurídico a analizar (notificación, resolución, contrato, etc.)"
    )
    doc_type: Optional[str] = Field(
        default=None,
        description="Tipo de documento si ya es conocido (notificacion, sentencia, demanda, etc.)"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="ID de sesión para trazabilidad"
    )
    fuero: Optional[str] = Field(
        default=None,
        description="Fuero judicial (civil, penal, laboral, etc.)"
    )


class NotificationRequest(BaseModel):
    """Request para análisis de notificaciones judiciales."""
    text: str = Field(
        description="Texto de la notificación judicial"
    )
    expediente: Optional[str] = Field(
        default=None,
        description="Número de expediente si ya se conoce"
    )
    fecha_notificacion: Optional[str] = Field(
        default=None,
        description="Fecha de notificación para cómputo de plazos (ISO 8601)"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="ID de sesión para trazabilidad"
    )


class GenerationRequest(BaseModel):
    """Request para generación de escritos jurídicos."""
    fuero: str = Field(description="Fuero judicial (civil, penal, laboral, etc.)")
    materia: str = Field(description="Materia (daños, sucesiones, laboral, etc.)")
    tipo_escrito: str = Field(
        description="Tipo de escrito (demanda, contestacion, recurso, medida_cautelar, etc.)"
    )
    variante: str = Field(
        default="estandar",
        description="Variante: conservador | estandar | firme | agresivo_prudente (aliases aceptados: conservadora→conservador, agresiva_prudente→agresivo_prudente)"
    )
    hechos: Optional[str] = Field(
        default=None,
        description="Relato de hechos del caso (si disponible)"
    )
    datos: Optional[dict] = Field(
        default=None,
        description="Datos conocidos para pre-completar el escrito (nombre, DNI, domicilio, etc.)"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="ID de sesión para trazabilidad"
    )


class AuditRequest(BaseModel):
    """Request para revisión/auditoría de escritos."""
    text: str = Field(description="Texto del escrito a revisar")
    tipo_escrito: Optional[str] = Field(
        default=None,
        description="Tipo de escrito para contextualizar la revisión"
    )
    demanda_original: Optional[str] = Field(
        default=None,
        description="Demanda original, para contrastar en contestaciones"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="ID de sesión para trazabilidad"
    )


class StrategyRequest(BaseModel):
    """Request para evaluación de estrategia procesal."""

    text: str = Field(
        default="",
        description="Texto libre del caso, situación procesal o pieza relevante",
    )
    tipo_proceso: Optional[str] = Field(
        default=None,
        description="Tipo de proceso si se conoce (civil, laboral, amparo, etc.)",
    )
    etapa_procesal: Optional[str] = Field(
        default=None,
        description="Etapa procesal conocida (traslado, prueba, recurso, ejecución, etc.)",
    )
    objetivo_abogado: Optional[str] = Field(
        default=None,
        description="Objetivo táctico inmediato del abogado",
    )
    fuentes_recuperadas: Optional[list[dict]] = Field(
        default=None,
        description="Fuentes o citas recuperadas previamente si ya existen",
    )
    actuaciones_detectadas: Optional[list[dict]] = Field(
        default=None,
        description="Actuaciones detectadas por otros módulos si ya están disponibles",
    )
    plazos_detectados: Optional[list[dict]] = Field(
        default=None,
        description="Plazos detectados por otros módulos si ya están disponibles",
    )
    hallazgos_revision: Optional[list[str]] = Field(
        default=None,
        description="Hallazgos relevantes provenientes de revisión o auditoría",
    )
    tipo_escrito_generado: Optional[str] = Field(
        default=None,
        description="Tipo de escrito generado si el contexto proviene del generador",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="ID de sesión para trazabilidad",
    )
