"""
AILEX — Módulo de Trazabilidad.

Registro de todas las sesiones de análisis, fuentes consultadas,
confianza calculada y guardrails aplicados.
"""


class TraceabilityService:
    """
    Servicio de trazabilidad de respuestas.

    Registra cada interacción que produce una JuridicalResponse,
    incluyendo fuentes usadas, confianza y reglas aplicadas.
    """

    async def record_session(
        self,
        module: str,
        input_text: str,
        response: dict,
        sources_used: list,
        guardrails_applied: list = None,
    ) -> str:
        """
        Registrar una sesión de análisis.

        TODO: Persistir en AnalysisSession.
        """
        # TODO: Guardar en base de datos
        return "session_placeholder_id"

    async def get_session(self, session_id: str) -> dict:
        """Obtener detalles de una sesión registrada."""
        return {"status": "not_found"}

    async def list_sessions(
        self, module: str = None, limit: int = 20
    ) -> list[dict]:
        """Listar sesiones recientes."""
        return []
