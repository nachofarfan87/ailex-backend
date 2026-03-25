"""
AILEX — Política de razonamiento jurídico.

Orquestador central del pipeline de análisis.
Toda respuesta jurídica pasa por este módulo, que garantiza:

1. Diferenciación explícita: EXTRAÍDO / INFERENCIA / SUGERENCIA
2. Marcado de datos faltantes antes de emitir conclusiones
3. Cálculo coherente de confianza según fuentes disponibles
4. Validación completa antes de la entrega
5. Trazabilidad de toda afirmación sensible

No existe "respuesta directa". Todo pasa por el pipeline.
"""

from app.api.schemas.contracts import (
    JuridicalResponse,
    ConfidenceLevel,
    TaggedFact,
    SuggestedAction,
    MissingData,
    SourceCitationSchema,
    InformationType,
)
from app.policies.validators import OutputValidator, ValidationResult
from app.policies.confidence_policy import ConfidencePolicy
from app.policies.response_policy import ResponsePolicy


# ─── Tipos de módulo reconocidos ────────────────────────
VALID_MODULES = {
    "notificaciones",
    "analisis",
    "generacion",
    "auditoria",
    "estrategia",
    "revision",
}


class ReasoningPipeline:
    """
    Pipeline de razonamiento jurídico prudente.

    Stages:
      1. build_response()   — construir JuridicalResponse desde los componentes
      2. validate()         — aplicar guardrails + coherencia + tono
      3. finalize()         — inyectar disclaimer, marcar metadata
      4. run()              — ejecutar el pipeline completo

    Uso típico desde un servicio:

        pipeline = ReasoningPipeline(modulo="analisis")
        response = pipeline.run(
            resumen_ejecutivo="...",
            hechos_relevantes=[...],
            encuadre_preliminar=[...],
            acciones_sugeridas=[...],
            riesgos_observaciones=[...],
            fuentes_respaldo=[...],
            datos_faltantes=[...],
        )
    """

    def __init__(self, modulo: str, session_id: str = None):
        if modulo not in VALID_MODULES:
            raise ValueError(
                f"Módulo desconocido: '{modulo}'. "
                f"Válidos: {sorted(VALID_MODULES)}"
            )
        self.modulo = modulo
        self.session_id = session_id

    def build_response(
        self,
        resumen_ejecutivo: str,
        hechos_relevantes: list[TaggedFact] = None,
        encuadre_preliminar: list[str] = None,
        acciones_sugeridas: list[SuggestedAction] = None,
        riesgos_observaciones: list[str] = None,
        fuentes_respaldo: list[SourceCitationSchema] = None,
        datos_faltantes: list[MissingData] = None,
    ) -> JuridicalResponse:
        """
        Construir el objeto JuridicalResponse desde sus componentes.
        Calcula nivel de confianza automáticamente desde las fuentes.
        """
        fuentes = fuentes_respaldo or []

        # Calcular confianza desde fuentes reales
        sources_as_dicts = [
            s.model_dump() if hasattr(s, "model_dump") else s
            for s in fuentes
        ]
        # Mapear source_hierarchy → hierarchy para el cálculo
        for s in sources_as_dicts:
            if "source_hierarchy" in s and "hierarchy" not in s:
                s["hierarchy"] = s["source_hierarchy"]

        score, nivel = ConfidencePolicy.calculate(sources_as_dicts)

        return JuridicalResponse(
            resumen_ejecutivo=resumen_ejecutivo,
            hechos_relevantes=hechos_relevantes or [],
            encuadre_preliminar=encuadre_preliminar or [],
            acciones_sugeridas=acciones_sugeridas or [],
            riesgos_observaciones=riesgos_observaciones or [],
            fuentes_respaldo=fuentes,
            datos_faltantes=datos_faltantes or [],
            nivel_confianza=nivel,
            confianza_score=score,
            modulo_origen=self.modulo,
            session_id=self.session_id,
        )

    def validate(
        self,
        response: JuridicalResponse,
        available_source_ids: list = None,
    ) -> tuple[JuridicalResponse, ValidationResult]:
        """
        Aplicar el pipeline de validación completo.
        Retorna (respuesta_corregida, resultado).
        """
        response_dict = response.model_dump()
        corrected_dict, result = OutputValidator.validate_and_correct(
            response_dict,
            available_sources=available_source_ids or [],
        )
        # Reconstruir el objeto desde el dict corregido
        # (el validador puede haber ajustado score/nivel)
        corrected = JuridicalResponse(**{
            k: v for k, v in corrected_dict.items()
            if k != "_validation"
        })
        corrected_dict_clean = corrected.model_dump()
        # Preservar metadata de validación
        corrected_dict_clean["_validation"] = corrected_dict.get("_validation", {})
        return corrected, result

    def run(
        self,
        resumen_ejecutivo: str,
        hechos_relevantes: list[TaggedFact] = None,
        encuadre_preliminar: list[str] = None,
        acciones_sugeridas: list[SuggestedAction] = None,
        riesgos_observaciones: list[str] = None,
        fuentes_respaldo: list[SourceCitationSchema] = None,
        datos_faltantes: list[MissingData] = None,
        available_source_ids: list = None,
    ) -> tuple[JuridicalResponse, ValidationResult]:
        """
        Ejecutar el pipeline completo: build → validate → finalize.

        Retorna (JuridicalResponse validada, ValidationResult).
        El caller puede inspeccionar el ValidationResult para loguear
        warnings o errores sin bloquear al usuario.
        """
        response = self.build_response(
            resumen_ejecutivo=resumen_ejecutivo,
            hechos_relevantes=hechos_relevantes,
            encuadre_preliminar=encuadre_preliminar,
            acciones_sugeridas=acciones_sugeridas,
            riesgos_observaciones=riesgos_observaciones,
            fuentes_respaldo=fuentes_respaldo,
            datos_faltantes=datos_faltantes,
        )
        return self.validate(response, available_source_ids=available_source_ids)

    @staticmethod
    def make_response_with_error(
        modulo: str,
        error_description: str,
    ) -> JuridicalResponse:
        """
        Respuesta de error estructurada.
        Usada cuando el pipeline no puede ejecutarse correctamente.
        No inventa datos — indica el problema explícitamente.
        """
        return JuridicalResponse(
            resumen_ejecutivo=(
                "Sin respaldo documental — no es posible emitir análisis. "
                f"Motivo: {error_description}"
            ),
            nivel_confianza=ConfidenceLevel.SIN_RESPALDO,
            confianza_score=0.0,
            modulo_origen=modulo,
            datos_faltantes=[
                MissingData(
                    description=error_description,
                    impact="No es posible emitir análisis sin esta información",
                )
            ],
        )

    @staticmethod
    def tag_extracted(content: str, source: SourceCitationSchema = None) -> TaggedFact:
        """Helper: crear un hecho EXTRAÍDO."""
        return TaggedFact(
            content=content,
            info_type=InformationType.EXTRAIDO,
            source=source,
        )

    @staticmethod
    def tag_inference(content: str) -> TaggedFact:
        """Helper: crear un hecho INFERENCIA (sin fuente directa)."""
        return TaggedFact(
            content=content,
            info_type=InformationType.INFERENCIA,
            source=None,
        )

    @staticmethod
    def suggest(content: str, priority: str = "media", risk: str = None) -> SuggestedAction:
        """Helper: crear una acción SUGERIDA."""
        return SuggestedAction(
            action=content,
            info_type=InformationType.SUGERENCIA,
            priority=priority,
            risk=risk,
        )

    @staticmethod
    def missing(description: str, impact: str, required_for: str = None) -> MissingData:
        """Helper: registrar un dato faltante."""
        return MissingData(
            description=description,
            impact=impact,
            required_for=required_for,
        )
