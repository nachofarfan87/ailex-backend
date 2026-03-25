"""
AILEX — Módulo de Generación de Escritos Forenses.

Genera borradores de escritos jurídicos usando plantillas estructuradas
con marcadores {{PLACEHOLDER}} para todo dato no provisto.

REGLAS FUNDAMENTALES:
  1. Nunca rellenar datos que no fueron provistos explícitamente.
  2. Todo dato desconocido → {{NOMBRE_DEL_DATO}} visible en el borrador.
  3. Los escritos del estudio no son fuente de autoridad normativa.
  4. No inventar hechos, normativa ni jurisprudencia.
  5. No cerrar escritos como definitivos si faltan datos esenciales.
  6. Nivel de confianza refleja disponibilidad de fuentes reales (RAG).

Variantes soportadas:
  conservador      — mínimo riesgo, máxima formalidad
  estandar         — equilibrio prudencia / completitud (default)
  firme            — tono asertivo y directo
  agresivo_prudente— máxima argumentación sin temeridad

Compatibilidad: el alias "conservadora" y "agresiva_prudente" se normalizan.
"""

import re
from app.policies.reasoning_policy import ReasoningPipeline
from app.policies.validators import ValidationResult
from app.modules.search.retrieval import retrieve_sources
from app.modules.generation.registry import TemplateRegistry
from app.modules.generation.schemas import GenerationResponse
from app.modules.generation.templates import get_template_text


class GenerationService:
    """
    Servicio de generación de escritos forenses.

    Genera borradores con {{PLACEHOLDER}} para todo dato no provisto.
    NUNCA inventa datos para completar campos vacíos.
    Toda salida pasa por el ReasoningPipeline.
    Retorna GenerationResponse (extensión de JuridicalResponse).
    """

    # ── Helpers privados ─────────────────────────────────────────────────────

    @staticmethod
    def _apply_known_data(template: str, datos: dict | None) -> str:
        """Reemplazar placeholders solo para los datos provistos explícitamente."""
        if not datos:
            return template
        result = template
        for key, value in datos.items():
            placeholder = "{{" + key.upper() + "}}"
            if placeholder in result and value:
                result = result.replace(placeholder, str(value))
        return result

    @staticmethod
    def _collect_remaining_placeholders(text: str) -> list[str]:
        """Detectar todos los {{PLACEHOLDER}} que quedaron sin completar."""
        return re.findall(r"\{\{([^}]+)\}\}", text)

    @staticmethod
    def _nivel_respaldo(fuentes: list) -> str:
        """Descripción textual del nivel de respaldo documental."""
        if len(fuentes) >= 3:
            return "con respaldo documental suficiente"
        if len(fuentes) >= 1:
            return "con respaldo documental parcial"
        return "sin respaldo documental directo (borrador base)"

    # ── Método principal ─────────────────────────────────────────────────────

    async def generate(
        self,
        fuero: str,
        materia: str,
        tipo_escrito: str,
        variante: str = "estandar",
        hechos: str = None,
        datos: dict = None,
        session_id: str = None,
    ) -> tuple[GenerationResponse, ValidationResult]:
        """
        Generar un borrador de escrito jurídico estructurado.

        Retorna (GenerationResponse, ValidationResult).

        GenerationResponse incluye:
          - borrador: texto completo con {{PLACEHOLDER}} donde faltan datos
          - placeholders_detectados: lista de placeholders sin completar
          - checklist_previo: verificaciones previas (de la plantilla)
          - riesgos_habituales: riesgos típicos del tipo de escrito
          - datos_faltantes: detalle estructurado de cada placeholder (contrato base)
          - nivel_confianza: refleja disponibilidad de fuentes RAG
        """
        # Normalizar variante (compatibilidad con nombres anteriores)
        variante_norm = TemplateRegistry.normalizar_variante(variante)
        tipo_norm = tipo_escrito.lower().replace("-", "_").replace(" ", "_")

        pipeline = ReasoningPipeline(modulo="generacion", session_id=session_id)

        # Obtener metadata de la plantilla
        template_meta = TemplateRegistry.get(tipo_norm)

        if template_meta is None:
            disponibles = ", ".join(TemplateRegistry.get_tipos_disponibles())
            error_response = ReasoningPipeline.make_response_with_error(
                modulo="generacion",
                error_description=(
                    f"Tipo de escrito '{tipo_escrito}' no disponible en plantillas. "
                    f"Tipos disponibles: {disponibles}."
                ),
            )
            vr = ValidationResult()
            vr.add_error(f"Plantilla no disponible para: {tipo_escrito}")
            # Retornar como GenerationResponse vacía
            gen_error = GenerationResponse(
                **error_response.model_dump(),
                borrador="[PLANTILLA NO DISPONIBLE]",
                tipo_escrito=tipo_escrito,
                variante_aplicada=variante_norm,
                placeholders_detectados=[],
                checklist_previo=[],
                riesgos_habituales=[],
            )
            return gen_error, vr

        # Obtener texto de la plantilla según variante
        template_text = get_template_text(tipo_norm, variante_norm)

        # Combinar datos base + datos del request
        datos_combinados: dict = {"MATERIA": materia, "FUERO": fuero}
        if hechos:
            datos_combinados["RELATO_DE_HECHOS"] = hechos
        if datos:
            datos_combinados.update({k.upper(): v for k, v in datos.items()})

        # Aplicar datos conocidos → borrador con placeholders restantes
        borrador = self._apply_known_data(template_text, datos_combinados)

        # Detectar placeholders sin completar
        pendientes = self._collect_remaining_placeholders(borrador)

        # Placeholders requeridos de la plantilla que aún faltan
        requeridos_faltantes = [
            ph for ph in template_meta.placeholders_requeridos
            if ph not in datos_combinados
        ]

        # ── RAG: recuperar fuentes de respaldo ───────────────────────────────
        gen_query = f"{tipo_norm} {fuero} {materia}"
        if hechos:
            gen_query += f" {hechos[:200]}"

        fuentes = await retrieve_sources(
            query=gen_query,
            module="generation",
            jurisdiction="Jujuy",
            legal_area=fuero,
            top_k=5,
        )

        nivel_respaldo = self._nivel_respaldo(fuentes)

        # ── Construir componentes del pipeline ───────────────────────────────

        # Datos faltantes estructurados (contrato base)
        datos_faltantes = [
            pipeline.missing(
                description=ph.replace("_", " ").title(),
                impact="Dato necesario para completar el escrito",
                required_for=f"Completar campo del escrito ({tipo_norm})",
            )
            for ph in pendientes
        ]

        # Hechos relevantes
        hechos_relevantes = [
            pipeline.tag_extracted(f"Tipo de escrito: {tipo_norm}"),
            pipeline.tag_extracted(f"Variante aplicada: {variante_norm}"),
            pipeline.tag_extracted(f"Fuero: {fuero} — Materia: {materia}"),
            pipeline.tag_inference(
                f"Placeholders detectados: {len(pendientes)} campo(s) sin completar"
            ),
            pipeline.tag_inference(
                f"Requeridos faltantes: {len(requeridos_faltantes)} de {len(template_meta.placeholders_requeridos)} obligatorios"
            ),
        ]
        if fuentes:
            hechos_relevantes.append(
                pipeline.tag_extracted(
                    f"Fuentes de respaldo recuperadas: {len(fuentes)}"
                )
            )

        # Encuadre procesal
        encuadre = [
            f"Fuero: {fuero} | Materia: {materia} | Tipo: {tipo_norm} | Variante: {variante_norm}.",
            f"Jurisdicción: Jujuy, Argentina. Verificar normativa local antes de presentar.",
            f"Estructura del escrito: {' → '.join(template_meta.estructura_base)}.",
            f"Placeholders sin completar: {len(pendientes)} (de los cuales {len(requeridos_faltantes)} son obligatorios).",
            f"Nivel de respaldo documental: {nivel_respaldo}.",
        ]

        # Acciones sugeridas (variante + obligatorias)
        acciones = []
        if variante_norm == "conservador":
            acciones.append(pipeline.suggest(
                "Revisar que el escrito se ajuste estrictamente a los precedentes del fuero y a la estructura formal",
                priority="alta",
            ))
        elif variante_norm == "firme":
            acciones.append(pipeline.suggest(
                "Confirmar que el tono firme es apropiado para la instancia y el tribunal",
                priority="media",
            ))
        elif variante_norm == "agresivo_prudente":
            acciones.append(pipeline.suggest(
                "Verificar que todos los argumentos tienen respaldo en hechos o normativa verificable — sin afirmaciones sin sustento",
                priority="alta",
            ))

        acciones.append(pipeline.suggest(
            f"Completar los {len(pendientes)} campo(s) marcados como {{{{PLACEHOLDER}}}} antes de presentar",
            priority="alta",
            risk="No presentar el escrito con placeholders sin completar",
        ))
        acciones.append(pipeline.suggest(
            "Verificar la normativa procesal aplicable en el CPC de Jujuy vigente",
            priority="alta",
        ))
        if not fuentes:
            acciones.append(pipeline.suggest(
                "Buscar y citar normativa verificada antes de presentar — el borrador no tiene respaldo documental",
                priority="alta",
                risk="Base normativa no verificada",
            ))

        # Riesgos observados en esta generación específica
        riesgos_observados = [
            f"El borrador contiene {len(pendientes)} campo(s) sin completar ({{{{PLACEHOLDER}}}}).",
            "No presentar el escrito hasta completar y verificar todos los campos.",
            "Verificar artículos y normativa citados en el fundamento de derecho antes de presentar.",
        ]
        if len(requeridos_faltantes) > 0:
            riesgos_observados.append(
                f"Faltan {len(requeridos_faltantes)} dato(s) obligatorio(s): "
                f"{', '.join(requeridos_faltantes[:5])}"
                + (" (y más)" if len(requeridos_faltantes) > 5 else "") + "."
            )
        if not fuentes:
            riesgos_observados.append(
                "Sin respaldo documental recuperado. El borrador se generó como base estructural — "
                "completar con normativa y jurisprudencia verificada."
            )

        # Resumen ejecutivo
        fuentes_str = f", {len(fuentes)} fuente(s) de respaldo recuperada(s)" if fuentes else ", sin respaldo documental"
        resumen = (
            f"Borrador generado: {template_meta.nombre} — variante {variante_norm} "
            f"(fuero {fuero}, materia {materia}{fuentes_str}). "
            f"{len(pendientes)} campo(s) pendientes de completar. "
            "Revisar checklist previo antes de presentar."
        )

        # ── Ejecutar pipeline (build → validate) ────────────────────────────
        base_response, vr = pipeline.run(
            resumen_ejecutivo=resumen,
            hechos_relevantes=hechos_relevantes,
            encuadre_preliminar=encuadre,
            acciones_sugeridas=acciones,
            riesgos_observaciones=riesgos_observados,
            fuentes_respaldo=fuentes,
            datos_faltantes=datos_faltantes,
        )

        # ── Construir GenerationResponse ────────────────────────────────────
        gen_response = GenerationResponse(
            **base_response.model_dump(),
            borrador=borrador,
            tipo_escrito=tipo_norm,
            variante_aplicada=variante_norm,
            placeholders_detectados=pendientes,
            checklist_previo=template_meta.checklist_previo,
            riesgos_habituales=template_meta.riesgos_habituales,
        )

        return gen_response, vr

    # ── Métodos auxiliares (compatibilidad con endpoints existentes) ──────────

    async def list_templates(
        self, fuero: str = None, materia: str = None
    ) -> list[dict]:
        """Listar plantillas disponibles con filtros opcionales."""
        templates = TemplateRegistry.list_filtered(fuero=fuero, materia=materia)
        return [TemplateRegistry.to_summary_dict(t) for t in templates]

    async def get_draft(
        self,
        fuero: str,
        materia: str,
        tipo_escrito: str,
        variante: str = "estandar",
        datos: dict = None,
    ) -> str:
        """
        Obtener el borrador crudo del escrito con placeholders aplicados.
        Para uso directo sin pasar por JuridicalResponse (previsualización).
        """
        tipo_norm = tipo_escrito.lower().replace("-", "_").replace(" ", "_")
        variante_norm = TemplateRegistry.normalizar_variante(variante)
        template_text = get_template_text(tipo_norm, variante_norm)
        if template_text is None:
            return f"[PLANTILLA NO DISPONIBLE: {tipo_escrito}]"
        datos_base = {"MATERIA": materia, "FUERO": fuero}
        if datos:
            datos_base.update({k.upper(): v for k, v in datos.items()})
        return self._apply_known_data(template_text, datos_base)

    async def get_template_metadata(self, tipo_escrito: str) -> dict | None:
        """
        Obtener los metadatos completos de una plantilla.
        Retorna None si el tipo no existe.
        """
        tipo_norm = tipo_escrito.lower().replace("-", "_").replace(" ", "_")
        tmpl = TemplateRegistry.get(tipo_norm)
        if tmpl is None:
            return None
        return tmpl.model_dump()
