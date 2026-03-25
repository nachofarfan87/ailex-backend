"""
AILEX — Módulo de estrategia procesal prudente.
"""

from app.api.schemas.contracts import SourceCitationSchema, SourceHierarchy
from app.modules.normalization.service import NormalizationService
from app.modules.notifications.extractor import extract_notification_structure
from app.modules.procedural_deadlines import calculate_deadline, detect_deadlines
from app.modules.strategy.comparators import build_option_comparisons
from app.modules.strategy.evaluators import evaluate_options
from app.modules.strategy.options import build_candidate_options
from app.modules.strategy.schemas import StrategyContext, StrategyResponse
from app.policies.reasoning_policy import ReasoningPipeline
from app.policies.validators import ValidationResult


class StrategyService:
    """Servicio de estrategia procesal comparada y prudente."""

    def __init__(self):
        self._normalizer = NormalizationService()

    async def analyze(
        self,
        text: str,
        tipo_proceso: str = None,
        etapa_procesal: str = None,
        objetivo_abogado: str = None,
        fuentes_recuperadas: list[dict] = None,
        actuaciones_detectadas: list[dict] = None,
        plazos_detectados: list[dict] = None,
        hallazgos_revision: list[str] = None,
        tipo_escrito_generado: str = None,
        session_id: str = None,
    ) -> tuple[StrategyResponse, ValidationResult]:
        if not (text and text.strip()) and not actuaciones_detectadas and not plazos_detectados:
            error_response = ReasoningPipeline.make_response_with_error(
                modulo="estrategia",
                error_description="No hay situación procesal suficiente para evaluar opciones.",
            )
            vr = ValidationResult()
            vr.add_error("Entrada insuficiente para estrategia.")
            strategy_error = StrategyResponse(
                **error_response.model_dump(),
                problema_central="Sin caso base para comparar opciones.",
                recomendacion_prudente=(
                    "Antes de definir una vía estratégica conviene reunir una pieza, constancia o relato mínimo verificable."
                ),
                version_corta_para_abogado=(
                    "Sin base fáctica suficiente. Reunir antecedentes antes de definir táctica."
                ),
            )
            return strategy_error, vr

        normalized = await self._normalizer.normalize(text or "")
        text_clean = normalized.get("text_clean", text or "")
        doc_type = normalized.get("doc_type", "desconocido")

        notification_structure = None
        if doc_type == "notificacion" or "notifi" in text_clean.casefold():
            notification_structure = extract_notification_structure(text or "")

        normalized_sources = self._normalize_sources(fuentes_recuperadas or [])
        if not normalized_sources and text_clean.strip():
            from app.modules.search.retrieval import retrieve_sources

            strategy_query = self._build_strategy_query(
                text_clean=text_clean,
                tipo_proceso=tipo_proceso,
                etapa_procesal=etapa_procesal,
                objetivo_abogado=objetivo_abogado,
                doc_type=doc_type,
            )
            normalized_sources = await retrieve_sources(
                query=strategy_query,
                module="strategy",
                jurisdiction="Jujuy",
                legal_area=tipo_proceso,
                top_k=5,
            )

        detected_actions = list(actuaciones_detectadas or [])
        if notification_structure:
            detected_actions.extend(notification_structure.get("actuaciones_detectadas", []))
        detected_actions = self._dedupe_dicts(detected_actions, key="texto")

        detected_deadlines = list(plazos_detectados or [])
        if notification_structure:
            notification_date = notification_structure.get("fecha")
            for detection in detect_deadlines(notification_structure.get("texto_normalizado", text_clean)):
                calculated = calculate_deadline(detection, notification_date)
                detected_deadlines.append(calculated.to_dict())
        detected_deadlines = self._dedupe_deadlines(detected_deadlines)

        context = StrategyContext(
            text=text or "",
            text_clean=text_clean,
            doc_type=doc_type,
            tipo_proceso=tipo_proceso,
            etapa_procesal=etapa_procesal,
            objetivo_abogado=objetivo_abogado,
            actuaciones_detectadas=detected_actions,
            plazos_detectados=detected_deadlines,
            hallazgos_revision=list(hallazgos_revision or []),
            tipo_escrito_generado=tipo_escrito_generado,
            fuentes_recuperadas=normalized_sources,
            notification_structure=notification_structure,
        )

        candidates = build_candidate_options(context)
        options = evaluate_options(candidates, context)

        pipeline = ReasoningPipeline(modulo="estrategia", session_id=session_id)
        hechos = []
        hechos_seen = set()
        riesgos = []
        riesgos_seen = set()
        datos_faltantes = []
        faltantes_seen = set()

        def add_hecho(tagged_fact):
            content = tagged_fact.content.strip()
            if content in hechos_seen:
                return
            hechos.append(tagged_fact)
            hechos_seen.add(content)

        def add_riesgo(message: str):
            message = message.strip()
            if not message or message in riesgos_seen:
                return
            riesgos.append(message)
            riesgos_seen.add(message)

        def add_missing(description: str, impact: str, required_for: str = None):
            key = (description.strip(), required_for or "")
            if key in faltantes_seen:
                return
            datos_faltantes.append(
                pipeline.missing(
                    description=description,
                    impact=impact,
                    required_for=required_for,
                )
            )
            faltantes_seen.add(key)

        if tipo_proceso:
            add_hecho(pipeline.tag_inference(f"Tipo de proceso informado: {tipo_proceso}"))
        if etapa_procesal:
            add_hecho(pipeline.tag_inference(f"Etapa procesal informada: {etapa_procesal}"))
        if objetivo_abogado:
            add_hecho(pipeline.tag_inference(f"Objetivo del abogado: {objetivo_abogado}"))
        if notification_structure and notification_structure.get("organo"):
            add_hecho(
                pipeline.tag_inference(
                    f"Órgano judicial detectado: {notification_structure['organo']}"
                )
            )
        for action in detected_actions[:5]:
            texto = action.get("texto") or action.get("tipo")
            if texto:
                add_hecho(pipeline.tag_inference(f"Actuación relevante: {texto}"))
        for deadline in detected_deadlines[:4]:
            phrase = deadline.get("frase_detectada") or deadline.get("texto")
            if phrase:
                add_hecho(pipeline.tag_inference(f"Plazo o ventana detectada: {phrase}"))
            if deadline.get("fecha_vencimiento"):
                add_hecho(
                    pipeline.tag_inference(
                        f"Vencimiento estimado en cálculo simple: {deadline['fecha_vencimiento']}"
                    )
                )
        if hallazgos_revision:
            add_hecho(
                pipeline.tag_inference(
                    f"Hallazgos de revisión disponibles: {len(hallazgos_revision)}"
                )
            )
        if tipo_escrito_generado:
            add_hecho(
                pipeline.tag_inference(
                    f"Tipo de escrito generado disponible como contexto: {tipo_escrito_generado}"
                )
            )
        if normalized_sources:
            add_hecho(
                pipeline.tag_inference(
                    f"Fuentes recuperadas para soporte estratégico: {len(normalized_sources)}"
                )
            )

        encuadre = [
            "La salida estratégica compara cursos de acción posibles sin asumir que exista una única vía obligatoria.",
            "Toda opción depende de admisibilidad, prueba y oportunidad procesal que deben verificarse en el caso concreto.",
        ]
        if doc_type != "desconocido":
            encuadre.append(f"Tipo de documento detectado: {doc_type}.")
        if etapa_procesal:
            encuadre.append(f"Etapa procesal considerada: {etapa_procesal}.")
        if normalized_sources:
            encuadre.append(
                f"Respaldo documental recuperado: {len(normalized_sources)} fuente(s) para contraste."
            )
        else:
            encuadre.append(
                "Sin respaldo documental suficiente: las opciones se formulan con prudencia y deben verificarse antes de actuar."
            )

        for source in normalized_sources:
            hierarchy = (
                source.source_hierarchy.value
                if hasattr(source.source_hierarchy, "value")
                else str(source.source_hierarchy)
            )
            if hierarchy == SourceHierarchy.INTERNO.value:
                add_riesgo(
                    "Parte del respaldo disponible es interno o referencial; no debe tomarse como autoridad normativa."
                )

        if not normalized_sources:
            add_riesgo(
                "La viabilidad de las opciones no puede valorarse con solidez sin normativa, jurisprudencia o constancias relevantes."
            )

        if not text_clean.strip():
            add_missing(
                description="Relato mínimo del caso o situación procesal",
                impact="Sin relato base no puede compararse utilidad táctica entre opciones",
                required_for="Análisis estratégico",
            )
        if not etapa_procesal:
            add_missing(
                description="Etapa procesal precisa",
                impact="Sin etapa definida puede variar admisibilidad y costo de cada opción",
                required_for="Comparación estratégica",
            )
        if not objetivo_abogado:
            add_missing(
                description="Objetivo concreto del abogado",
                impact="Sin objetivo explícito es más difícil priorizar entre opciones conservadoras u ofensivas",
                required_for="Priorización táctica",
            )
        if detected_deadlines and not any(item.get("fecha_notificacion") for item in detected_deadlines):
            add_missing(
                description="Fecha de notificación o constancia temporal relevante",
                impact="Sin fecha no puede evaluarse con seguridad la oportunidad relativa de responder, apelar o subsanar",
                required_for="Evaluación temporal de opciones",
            )

        for option in options:
            for risk in option.riesgos[:2]:
                add_riesgo(f"{option.nombre}: {risk}")

        acciones = []
        for option in options[:3]:
            priority = (
                "alta"
                if option.nivel_solidez.value == "alta"
                else "media" if option.nivel_solidez.value == "media" else "baja"
            )
            acciones.append(
                pipeline.suggest(
                    f"Comparar la opción '{option.nombre}' contra sus requisitos y riesgos antes de decidir.",
                    priority=priority,
                    risk=option.riesgos[0] if option.riesgos else None,
                )
            )

        comparisons = build_option_comparisons(options, has_missing_data=bool(datos_faltantes))
        problema_central = self._build_problem_statement(context, normalized_sources)
        recommendation = self._build_recommendation(options, datos_faltantes, normalized_sources)
        quick_version = self._build_quick_version(options, recommendation, bool(datos_faltantes))

        if options:
            resumen = (
                f"Estrategia procesal con {len(options)} opción(es) comparadas. "
                "No surge una única vía obligatoria con la información disponible. "
                "Conviene leer requisitos, riesgos y respaldo antes de priorizar."
            )
        else:
            resumen = (
                "Sin base suficiente para construir una comparación estratégica útil. "
                "Antes de sugerir una vía, conviene completar datos del caso y respaldo."
            )

        base_response, vr = pipeline.run(
            resumen_ejecutivo=resumen,
            hechos_relevantes=hechos,
            encuadre_preliminar=encuadre,
            acciones_sugeridas=acciones,
            riesgos_observaciones=riesgos,
            fuentes_respaldo=normalized_sources,
            datos_faltantes=datos_faltantes,
        )

        strategy_response = StrategyResponse(
            **base_response.model_dump(),
            problema_central=problema_central,
            opciones_estrategicas=options,
            comparacion_opciones=comparisons,
            requisitos_por_opcion={option.nombre: option.requisitos for option in options},
            ventajas_por_opcion={option.nombre: option.ventajas for option in options},
            riesgos_por_opcion={option.nombre: option.riesgos for option in options},
            recomendacion_prudente=recommendation,
            version_corta_para_abogado=quick_version,
        )
        return strategy_response, vr

    async def get_options(self, **kwargs) -> dict:
        response, _ = await self.analyze(**kwargs)
        return {
            "problema_central": response.problema_central,
            "opciones_estrategicas": [option.model_dump() for option in response.opciones_estrategicas],
            "comparacion_opciones": [item.model_dump() for item in response.comparacion_opciones],
            "nivel_confianza": response.nivel_confianza.value,
            "confianza_score": response.confianza_score,
        }

    async def get_quick_summary(self, **kwargs) -> dict:
        response, _ = await self.analyze(**kwargs)
        return {
            "problema_central": response.problema_central,
            "recomendacion_prudente": response.recomendacion_prudente,
            "version_corta_para_abogado": response.version_corta_para_abogado,
            "nivel_confianza": response.nivel_confianza.value,
            "confianza_score": response.confianza_score,
        }

    def _normalize_sources(self, sources: list) -> list[SourceCitationSchema]:
        normalized = []
        for source in sources:
            if isinstance(source, SourceCitationSchema):
                normalized.append(source)
            elif isinstance(source, dict):
                normalized.append(SourceCitationSchema(**source))
        return normalized

    def _build_strategy_query(
        self,
        text_clean: str,
        tipo_proceso: str,
        etapa_procesal: str,
        objetivo_abogado: str,
        doc_type: str,
    ) -> str:
        parts = []
        if doc_type and doc_type != "desconocido":
            parts.append(doc_type)
        if tipo_proceso:
            parts.append(tipo_proceso)
        if etapa_procesal:
            parts.append(etapa_procesal)
        if objetivo_abogado:
            parts.append(objetivo_abogado)
        if not parts:
            parts.append(text_clean[:220])
        return " ".join(parts)

    def _build_problem_statement(
        self,
        context: StrategyContext,
        sources: list[SourceCitationSchema],
    ) -> str:
        pieces = []
        if context.doc_type and context.doc_type != "desconocido":
            pieces.append(f"Situación a partir de {context.doc_type}")
        if context.etapa_procesal:
            pieces.append(f"en etapa {context.etapa_procesal}")
        if context.objetivo_abogado:
            pieces.append(f"con objetivo de {context.objetivo_abogado}")
        if context.plazos_detectados:
            pieces.append("con incidencia temporal o plazo detectado")
        if not pieces:
            pieces.append("Definir una respuesta táctica razonable con información parcial")
        suffix = (
            f". Respaldo documental disponible: {len(sources)} fuente(s)."
            if sources
            else ". Sin respaldo documental suficiente para evaluar viabilidad con solidez."
        )
        return " ".join(pieces) + suffix

    def _build_recommendation(
        self,
        options,
        missing_data,
        sources,
    ) -> str:
        if not options:
            return (
                "Con la información disponible todavía no es prudente cerrar una vía táctica. "
                "Primero conviene completar datos del caso y respaldo."
            )
        top = options[0].nombre
        if missing_data:
            return (
                f"Con la base actual podría ser razonable priorizar '{top}' o una variante de menor exposición, "
                "pero la decisión debería revisarse cuando se complete la información faltante."
            )
        if not sources:
            return (
                f"Una línea prudente podría comenzar por '{top}', siempre que se verifique antes la normativa y constancias aplicables."
            )
        return (
            f"Con el respaldo hoy disponible, '{top}' aparece como una de las opciones comparativamente más sólidas, "
            "sin excluir alternativas conservadoras o diferidas si el expediente muestra matices adicionales."
        )

    def _build_quick_version(
        self,
        options,
        recommendation: str,
        has_missing_data: bool,
    ) -> str:
        names = ", ".join(option.nombre for option in options[:3]) if options else "sin opciones comparables"
        tail = (
            "Faltan datos críticos; evitar cerrar una única vía."
            if has_missing_data
            else "Comparar costos, requisitos y respaldo antes de ejecutar."
        )
        return f"Opciones a mirar primero: {names}. {recommendation} {tail}"

    def _dedupe_dicts(self, items: list[dict], key: str) -> list[dict]:
        seen = set()
        unique = []
        for item in items:
            value = (item.get(key) or item.get('tipo') or "").strip().casefold()
            if value in seen:
                continue
            seen.add(value)
            unique.append(item)
        return unique

    def _dedupe_deadlines(self, items: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for item in items:
            key = (
                str(item.get('frase_detectada') or item.get('texto') or "").casefold(),
                item.get("tipo_actuacion"),
                item.get("plazo_dias"),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique
