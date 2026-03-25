"""
AILEX — Schemas del módulo de auditoría y revisión de escritos.

Define:
- Hallazgo: hallazgo individual de la revisión con tipo, severidad y carácter.
- AuditResponse: extiende JuridicalResponse con campos propios de la auditoría.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional
from app.api.schemas.contracts import JuridicalResponse


class TipoHallazgo(str, Enum):
    """Categoría del hallazgo."""
    ESTRUCTURA      = "estructura"       # Falta de sección, encabezado, partes
    REDACCION       = "redaccion"        # Negativa genérica, vaguedad, ambigüedad
    ARGUMENTAL      = "argumental"       # Debilidad de fondo, norma sospechosa
    RIESGO_PROCESAL = "riesgo_procesal"  # Consecuencia procesal concreta
    GUARDRAIL       = "guardrail"        # Violación de reglas del sistema


class Severidad(str, Enum):
    """Nivel de gravedad del hallazgo."""
    GRAVE    = "grave"     # Defecto que puede invalidar o debilitar decisivamente el escrito
    MODERADA = "moderada"  # Debilidad que debe corregirse antes de presentar
    LEVE     = "leve"      # Mejora de calidad recomendada


class SeveridadGeneral(str, Enum):
    """Diagnóstico global del escrito."""
    GRAVE         = "grave"          # Al menos un hallazgo grave
    MODERADA      = "moderada"       # Al menos un hallazgo moderado, ninguno grave
    LEVE          = "leve"           # Solo hallazgos leves
    SIN_PROBLEMAS = "sin_problemas"  # Sin hallazgos detectados


class CaracterHallazgo(str, Enum):
    """Origen epistemológico del hallazgo (trazabilidad)."""
    EXTRAIDO  = "extraido"   # Detectado directamente en el texto
    INFERIDO  = "inferido"   # Inferido del contexto o la ausencia
    SUGERENCIA = "sugerencia"  # Mejora sugerida sin problema objetivo


class Hallazgo(BaseModel):
    """
    Hallazgo individual de la revisión de un escrito.

    Cada hallazgo es atómico: describe un único problema o debilidad
    detectado en el texto, con su categoría, severidad, origen y sugerencia.
    """
    tipo: TipoHallazgo = Field(description="Categoría del hallazgo")
    severidad: Severidad = Field(description="Nivel de gravedad")
    caracter: CaracterHallazgo = Field(
        description="Origen: extraido del texto | inferido del contexto | sugerencia de mejora"
    )
    seccion: Optional[str] = Field(
        default=None,
        description="Sección del escrito donde se detectó (encabezado, objeto, hechos, etc.)"
    )
    texto_detectado: Optional[str] = Field(
        default=None,
        description="Fragmento del texto original que originó el hallazgo"
    )
    observacion: str = Field(
        description="Descripción clara del problema detectado"
    )
    mejora_sugerida: Optional[str] = Field(
        default=None,
        description="Acción concreta de mejora (sin inventar hechos ni normativa)"
    )


class AuditResponse(JuridicalResponse):
    """
    Respuesta del revisor de escritos forenses.

    Extiende JuridicalResponse (contrato común) con campos propios
    de la auditoría: hallazgos estructurados, versión sugerida y diagnóstico.

    Compatibilidad: todos los campos de JuridicalResponse están presentes.
    Los campos adicionales son propios del módulo de auditoría.
    """
    diagnostico_general: str = Field(
        default="",
        description=(
            "Diagnóstico global del escrito: descripción breve del estado general "
            "de calidad formal y argumental."
        ),
    )
    severidad_general: SeveridadGeneral = Field(
        default=SeveridadGeneral.SIN_PROBLEMAS,
        description="Nivel de severidad global del escrito revisado",
    )
    hallazgos: list[Hallazgo] = Field(
        default_factory=list,
        description="Lista estructurada de hallazgos individuales detectados",
    )
    fortalezas: list[str] = Field(
        default_factory=list,
        description="Aspectos formales y argumentales positivos detectados en el escrito",
    )
    debilidades: list[str] = Field(
        default_factory=list,
        description="Debilidades generales (resumen de hallazgos, no repetición)",
    )
    mejoras_sugeridas: list[str] = Field(
        default_factory=list,
        description="Lista consolidada de acciones de mejora recomendadas",
    )
    version_sugerida: Optional[str] = Field(
        default=None,
        description=(
            "Versión mejorada del escrito con correcciones prudentes. "
            "No inventa hechos ni normativa. "
            "Mantiene {{PLACEHOLDER}} para datos faltantes. "
            "Puede estar ausente si el escrito no lo requiere o si el texto es muy breve."
        ),
    )
    cambios_aplicados: list[str] = Field(
        default_factory=list,
        description="Lista de cambios aplicados para generar la versión sugerida",
    )
    tipo_escrito_detectado: Optional[str] = Field(
        default=None,
        description="Tipo de escrito detectado automáticamente (si no fue indicado)",
    )
