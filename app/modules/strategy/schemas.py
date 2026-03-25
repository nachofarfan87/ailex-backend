"""
AILEX — Schemas del módulo de estrategia procesal.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.api.schemas.contracts import JuridicalResponse


class StrategyCharacter(str, Enum):
    EXTRAIDO = "extraido"
    INFERIDO = "inferido"
    SUGERENCIA = "sugerencia"


class StrategySolidity(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


class StrategyOption(BaseModel):
    nombre: str = Field(description="Nombre breve de la opción táctica")
    caracter: StrategyCharacter = Field(description="Origen: extraído, inferido o sugerido")
    justificacion_breve: str = Field(description="Fundamento prudente y breve")
    requisitos: list[str] = Field(default_factory=list)
    ventajas: list[str] = Field(default_factory=list)
    riesgos: list[str] = Field(default_factory=list)
    respaldo_disponible: list[str] = Field(default_factory=list)
    nivel_solidez: StrategySolidity = Field(default=StrategySolidity.BAJA)


class StrategyComparison(BaseModel):
    perfil: str = Field(description="Perfil comparativo: conservadora, estándar, etc.")
    opciones_priorizadas: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    nota_prudencia: str = Field(default="")


class StrategyResponse(JuridicalResponse):
    problema_central: str = Field(default="")
    opciones_estrategicas: list[StrategyOption] = Field(default_factory=list)
    comparacion_opciones: list[StrategyComparison] = Field(default_factory=list)
    requisitos_por_opcion: dict[str, list[str]] = Field(default_factory=dict)
    ventajas_por_opcion: dict[str, list[str]] = Field(default_factory=dict)
    riesgos_por_opcion: dict[str, list[str]] = Field(default_factory=dict)
    recomendacion_prudente: str = Field(default="")
    version_corta_para_abogado: str = Field(default="")


class StrategyContext(BaseModel):
    text: str = ""
    text_clean: str = ""
    doc_type: Optional[str] = None
    tipo_proceso: Optional[str] = None
    etapa_procesal: Optional[str] = None
    objetivo_abogado: Optional[str] = None
    actuaciones_detectadas: list[dict] = Field(default_factory=list)
    plazos_detectados: list[dict] = Field(default_factory=list)
    hallazgos_revision: list[str] = Field(default_factory=list)
    tipo_escrito_generado: Optional[str] = None
    fuentes_recuperadas: list = Field(default_factory=list)
    notification_structure: Optional[dict] = None
