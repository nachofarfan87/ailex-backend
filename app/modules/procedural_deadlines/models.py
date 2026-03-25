"""
AILEX — Modelos básicos para detección de plazos procesales.
"""

from dataclasses import dataclass, field


@dataclass
class DeadlineDetection:
    """Resultado básico de detección y cálculo prudente de plazos."""

    tipo_actuacion: str | None
    plazo_dias: int | None
    unidad: str | None
    frase_detectada: str
    requiere_calculo: bool
    fecha_notificacion: str | None = None
    fecha_vencimiento: str | None = None
    advertencias: list[str] = field(default_factory=list)
    confianza: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tipo_actuacion": self.tipo_actuacion,
            "plazo_dias": self.plazo_dias,
            "unidad": self.unidad,
            "frase_detectada": self.frase_detectada,
            "requiere_calculo": self.requiere_calculo,
            "fecha_notificacion": self.fecha_notificacion,
            "fecha_vencimiento": self.fecha_vencimiento,
            "advertencias": list(self.advertencias),
            "confianza": self.confianza,
        }
