"""
AILEX — Contrato común de respuesta jurídica.

Todas las salidas de análisis, generación, revisión y estrategia
deben cumplir con esta estructura para garantizar consistencia
y trazabilidad.

FORMATO OBLIGATORIO DE SALIDA — 8 secciones canónicas:
  resumen_ejecutivo | hechos_relevantes | encuadre_preliminar
  acciones_sugeridas | riesgos_observaciones | fuentes_respaldo
  datos_faltantes | nivel_confianza
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class SourceType(str, Enum):
    """
    Tipo de fuente documental.
    Determina el peso relativo, uso en argumentación y jerarquía jurídica.

    Vinculante (mayor peso): codigo, ley, reglamento, acordada
    Referencial: jurisprudencia, doctrina
    Interno (sin peso formal): escritos_estudio, plantillas
    """
    CODIGO           = "codigo"            # Códigos procesales y de fondo
    LEY              = "ley"               # Leyes nacionales y provinciales
    REGLAMENTO       = "reglamento"        # Decretos reglamentarios
    ACORDADA         = "acordada"          # Acordadas del STJ y Cámaras
    JURISPRUDENCIA   = "jurisprudencia"    # Fallos y sentencias
    DOCTRINA         = "doctrina"          # Comentarios doctrinarios, tratados
    ESCRITOS_ESTUDIO = "escritos_estudio"  # Escritos históricos del estudio
    PLANTILLAS       = "plantillas"        # Modelos base de escritos


class SourceHierarchy(str, Enum):
    """
    Jerarquía de fuentes documentales.
    Diferencia el peso argumental de cada tipo de fuente.
    """
    NORMATIVA = "normativa"            # Códigos, leyes, resoluciones — peso máximo
    JURISPRUDENCIA = "jurisprudencia"  # Fallos, sentencias — peso alto
    DOCTRINA = "doctrina"              # Tratados, artículos académicos — peso medio, no vinculante
    INTERNO = "interno"                # Material del estudio — uso práctico, sin peso formal


class ConfidenceLevel(str, Enum):
    """Niveles de confianza categorizados."""
    ALTO = "alto"        # Múltiples fuentes normativas/jurisprudenciales respaldan
    MEDIO = "medio"      # Algún respaldo documental, pero incompleto
    BAJO = "bajo"        # Inferencia razonable sin fuente directa
    SIN_RESPALDO = "sin_respaldo"  # No hay sustento documental


class InformationType(str, Enum):
    """
    Clasificación de cada dato en la respuesta.
    Obligatorio diferenciar para cumplir principios del sistema.
    """
    EXTRAIDO = "extraido"          # Dato extraído directamente de una fuente
    INFERENCIA = "inferencia"      # Inferencia razonable a partir de fuentes
    SUGERENCIA = "sugerencia"      # Sugerencia estratégica del sistema


class SourceCitationSchema(BaseModel):
    """Cita puntual a una fuente documental."""
    document_id: Optional[str] = None
    document_title: str
    source_hierarchy: SourceHierarchy
    fragment: str = Field(description="Fragmento textual relevante de la fuente")
    page_or_section: Optional[str] = None
    relevance_score: float = Field(ge=0.0, le=1.0, description="Relevancia 0-1")


class TaggedFact(BaseModel):
    """Hecho con clasificación de tipo de información."""
    content: str
    info_type: InformationType
    source: Optional[SourceCitationSchema] = None


class SuggestedAction(BaseModel):
    """Acción sugerida con clasificación y riesgos."""
    action: str
    info_type: InformationType = InformationType.SUGERENCIA
    priority: Optional[str] = None  # alta / media / baja
    risk: Optional[str] = None


class MissingData(BaseModel):
    """Dato faltante detectado."""
    description: str
    impact: str = Field(description="Impacto de la ausencia de este dato")
    required_for: Optional[str] = None


class JuridicalResponse(BaseModel):
    """
    Contrato común de respuesta jurídica.

    Toda salida de los módulos de análisis, generación,
    revisión y estrategia DEBE seguir esta estructura.

    Las 8 secciones canónicas son obligatorias (pueden estar vacías
    con justificación, pero deben estar presentes).
    """
    # 1. Resumen ejecutivo
    resumen_ejecutivo: str = Field(description="Resumen ejecutivo de la respuesta")

    # 2. Hechos relevantes (con clasificación de tipo)
    hechos_relevantes: list[TaggedFact] = Field(default_factory=list)

    # 3. Encuadre procesal o jurídico preliminar
    encuadre_preliminar: list[str] = Field(default_factory=list)

    # 4. Acciones sugeridas
    acciones_sugeridas: list[SuggestedAction] = Field(default_factory=list)

    # 5. Riesgos / observaciones
    riesgos_observaciones: list[str] = Field(default_factory=list)

    # 6. Fuentes y respaldo
    fuentes_respaldo: list[SourceCitationSchema] = Field(default_factory=list)

    # 7. Datos faltantes
    datos_faltantes: list[MissingData] = Field(default_factory=list)

    # 8. Nivel de confianza (categórico)
    nivel_confianza: ConfidenceLevel = ConfidenceLevel.SIN_RESPALDO

    # Score numérico (interno — 0.0 a 1.0)
    confianza_score: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Score numérico de confianza (0-1). Derivado automáticamente."
    )

    # Metadata
    modulo_origen: str = Field(description="Módulo que generó esta respuesta")
    session_id: Optional[str] = None
    advertencia_general: Optional[str] = Field(
        default=(
            "Esta respuesta es asistencia profesional orientativa. "
            "No sustituye el criterio del abogado. "
            "Verifique todas las fuentes citadas antes de actuar."
        ),
        description="Disclaimer obligatorio"
    )
