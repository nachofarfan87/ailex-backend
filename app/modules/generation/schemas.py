"""
AILEX — Schemas del módulo de generación de escritos.

Define:
- TemplateMetadata: estructura de una plantilla jurídica versionable.
- GenerationResponse: extiende JuridicalResponse con campos propios
  del generador (borrador, checklist, riesgos de plantilla, variante).
"""

from pydantic import BaseModel, Field
from typing import Optional
from app.api.schemas.contracts import JuridicalResponse


class TemplateMetadata(BaseModel):
    """
    Metadatos de una plantilla de escrito jurídico versionable.

    Cada plantilla describe la estructura esperada, los placeholders
    requeridos y opcionales, el checklist previo a la presentación
    y los riesgos habituales del tipo de escrito.
    """
    id: str = Field(description="Identificador único de la plantilla")
    nombre: str = Field(description="Nombre legible del tipo de escrito")
    fuero: str = Field(
        description="Fuero principal: general | civil | laboral | penal | familia | etc."
    )
    materia: str = Field(
        description="Materia principal: general | daños | sucesiones | laboral | etc."
    )
    tipo_escrito: str = Field(description="Clave canónica del tipo de escrito")
    version: str = Field(description="Versión de la plantilla (semver simple: 1.0, 1.1, …)")
    variantes_permitidas: list[str] = Field(
        description="Variantes de redacción habilitadas para esta plantilla"
    )
    estructura_base: list[str] = Field(
        description="Secciones del escrito en orden (encabezado, hechos, petitorio, …)"
    )
    placeholders_requeridos: list[str] = Field(
        description="Placeholders obligatorios — el borrador no debe presentarse sin ellos"
    )
    placeholders_opcionales: list[str] = Field(
        default_factory=list,
        description="Placeholders opcionales que mejoran la calidad si se proveen"
    )
    checklist_previo: list[str] = Field(
        description="Verificaciones que el abogado debe realizar antes de presentar"
    )
    riesgos_habituales: list[str] = Field(
        description="Observaciones de riesgo típicas para este tipo de escrito"
    )


class GenerationResponse(JuridicalResponse):
    """
    Respuesta del generador de escritos forenses.

    Extiende JuridicalResponse (contrato común) con campos
    específicos del módulo de generación.

    Compatibilidad: JuridicalResponse sigue presente en todos sus campos.
    Los campos adicionales son propios del generador y no afectan al contrato base.
    """
    borrador: str = Field(
        default="",
        description=(
            "Texto completo del borrador del escrito. "
            "Los datos no provistos aparecen como {{PLACEHOLDER}}. "
            "No presentar con placeholders sin completar."
        ),
    )
    tipo_escrito: str = Field(
        default="",
        description="Tipo de escrito generado",
    )
    variante_aplicada: str = Field(
        default="estandar",
        description="Variante de redacción aplicada: conservador | estandar | firme | agresivo_prudente",
    )
    placeholders_detectados: list[str] = Field(
        default_factory=list,
        description="Lista de {{PLACEHOLDER}} encontrados en el borrador sin completar",
    )
    checklist_previo: list[str] = Field(
        default_factory=list,
        description="Verificaciones previas a la presentación del escrito (de la plantilla)",
    )
    riesgos_habituales: list[str] = Field(
        default_factory=list,
        description="Riesgos típicos del tipo de escrito (de la plantilla, no del caso específico)",
    )
