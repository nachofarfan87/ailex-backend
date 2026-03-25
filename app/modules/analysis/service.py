"""
AILEX — Módulo de Análisis Jurídico.

Analiza textos legales y produce JuridicalResponse validadas.

Pipeline:
1. Normalización de entrada (NormalizationService)
2. Extracción de entidades (expediente, fechas, partes, artículos)
3. Clasificación del documento
4. Construcción de respuesta mediante ReasoningPipeline
5. Validación con guardrails (OutputValidator)

Nota: el análisis semántico profundo (LLM + RAG) se conectará
en la siguiente etapa. Este servicio produce respuestas estructuradas
reales basadas en extracción de entidades del texto.
"""

from app.api.schemas.contracts import JuridicalResponse
from app.policies.reasoning_policy import ReasoningPipeline
from app.policies.validators import ValidationResult
from app.modules.normalization.service import NormalizationService
from app.modules.notifications.extractor import extract_notification_structure
from app.modules.procedural_deadlines import calculate_deadline, detect_deadlines
from app.modules.search.retrieval import retrieve_sources


class AnalysisService:
    """
    Servicio de análisis jurídico.

    Recibe texto crudo → produce JuridicalResponse validada.
    Toda salida pasa por el ReasoningPipeline (guardrails obligatorios).
    """

    def __init__(self):
        self._normalizer = NormalizationService()

    async def analyze(
        self,
        text: str,
        doc_type: str = None,
        session_id: str = None,
        fuero: str = None,
    ) -> tuple[JuridicalResponse, ValidationResult]:
        """
        Analizar un texto jurídico.

        Retorna (JuridicalResponse, ValidationResult).
        El ValidationResult permite al route loguear warnings/corrections.
        """
        if not text or not text.strip():
            error_response = ReasoningPipeline.make_response_with_error(
                modulo="analisis",
                error_description="Texto de entrada vacío. No hay contenido para analizar.",
            )
            vr = ValidationResult()
            vr.add_error("Texto vacío — no se puede analizar.")
            return error_response, vr

        # 1. Normalizar
        normalized = await self._normalizer.normalize(text)
        entities = normalized.get("entities", {})
        detected_doc_type = doc_type or normalized.get("doc_type", "desconocido")
        notification_structure = None

        if detected_doc_type == "notificacion":
            notification_structure = extract_notification_structure(text)

        pipeline = ReasoningPipeline(
            modulo="notificaciones" if detected_doc_type == "notificacion" else "analisis",
            session_id=session_id,
        )

        hechos = []
        hechos_seen = set()
        encuadre = []
        acciones = []
        riesgos = []
        datos_faltantes = []
        riesgos_seen = set()
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

        def add_faltante(description: str, impact: str, required_for: str = None):
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

        # 2. Hechos extraídos de entidades detectadas

        for exp in entities.get("expediente", []):
            add_hecho(pipeline.tag_extracted(f"Expediente identificado: {exp}"))

        for fecha in entities.get("fecha", []):
            fecha_str = " ".join(str(p) for p in fecha) if isinstance(fecha, tuple) else str(fecha)
            add_hecho(pipeline.tag_extracted(f"Fecha detectada en el documento: {fecha_str}"))

        for caratula in entities.get("caratula", []):
            actor, materia = caratula if isinstance(caratula, tuple) and len(caratula) == 2 else (str(caratula), "")
            add_hecho(pipeline.tag_extracted(
                f"Carátula: {actor} / {materia}".strip(" /")
            ))

        # Artículos: siempre como inferencia (no verificados contra base)
        for art in entities.get("articulo", []):
            add_hecho(pipeline.tag_inference(
                f"Se cita el artículo {art} — verificar existencia y vigencia normativa"
            ))

        if notification_structure:
            notification_date = notification_structure.get("fecha")
            deadline_detections = [
                calculate_deadline(detection, fecha_notificacion=notification_date)
                for detection in detect_deadlines(notification_structure.get("texto_normalizado", text))
            ]
            if notification_structure.get("expediente"):
                add_hecho(pipeline.tag_extracted(
                    f"Expediente identificado: {notification_structure['expediente']}"
                ))
            if notification_structure.get("partes"):
                add_hecho(pipeline.tag_extracted(
                    f"Partes detectadas: {notification_structure['partes']}"
                ))
            if notification_structure.get("organo"):
                add_hecho(pipeline.tag_extracted(
                    f"Órgano judicial detectado: {notification_structure['organo']}"
                ))
            if notification_structure.get("fecha"):
                add_hecho(pipeline.tag_extracted(
                    f"Fecha detectada en el documento: {notification_structure['fecha']}"
                ))
            for action in notification_structure.get("actuaciones_detectadas", []):
                add_hecho(pipeline.tag_extracted(
                    f"Actuación procesal detectada: {action['texto']}"
                ))
            for plazo in notification_structure.get("plazos_detectados", []):
                add_hecho(pipeline.tag_extracted(
                    f"Plazo mencionado: {plazo['texto']}"
                ))
            for detection in deadline_detections:
                if detection.tipo_actuacion:
                    add_hecho(pipeline.tag_extracted(
                        f"Actuación con plazo detectada: {detection.tipo_actuacion}"
                    ))
                if detection.plazo_dias is not None:
                    add_hecho(pipeline.tag_extracted(
                        f"Plazo procesal detectado: {detection.plazo_dias} {detection.unidad}"
                    ))
                else:
                    add_hecho(pipeline.tag_inference(
                        f"Se detectó una referencia a plazo en '{detection.frase_detectada}', pero la cantidad requiere verificación manual."
                    ))
                if detection.fecha_vencimiento:
                    add_hecho(pipeline.tag_inference(
                        f"Vencimiento estimado en cálculo simple: {detection.fecha_vencimiento}"
                    ))
                for warning in detection.advertencias:
                    add_riesgo(warning)
                if detection.requiere_calculo and not detection.fecha_notificacion:
                    add_faltante(
                        description="Fecha de notificación suficiente para estimar vencimiento",
                        impact="Sin ella no puede estimarse el vencimiento del plazo detectado",
                        required_for="Cálculo básico de plazo procesal",
                    )

        # Tipo de documento
        if detected_doc_type and detected_doc_type != "desconocido":
            add_hecho(pipeline.tag_extracted(
                f"Tipo de documento detectado: {detected_doc_type}"
            ))
            encuadre.append(
                f"Documento clasificado como '{detected_doc_type}'. "
                "Verificar normativa procesal aplicable."
            )
        else:
            hechos.append(pipeline.tag_inference(
                "Tipo de documento no determinado. Requiere clasificación manual."
            ))

        # 3. Acciones y riesgos según tipo de documento
        if detected_doc_type == "notificacion":
            if notification_structure and notification_structure.get("texto_normalizado"):
                encuadre.append(
                    "El texto fue normalizado con reglas específicas para notificaciones judiciales."
                )
            acciones.append(pipeline.suggest(
                "Verificar el tipo de resolución notificada y el plazo que genera",
                priority="alta",
                risk="Vencimiento sin respuesta puede generar preclusión o rebeldía",
            ))
            acciones.append(pipeline.suggest(
                "Calcular plazo exacto desde la fecha de notificación efectiva",
                priority="alta",
            ))
            if not notification_structure or not notification_structure.get("fecha"):
                add_riesgo(
                    "Sin fecha exacta de notificación, el cómputo del plazo solo puede estimarse de forma incompleta."
                )
                add_faltante(
                    description="Fecha exacta de notificación efectiva",
                    impact="Sin ella no se puede estimar el vencimiento del plazo detectado",
                    required_for="Cómputo de plazo procesal",
                )

        elif detected_doc_type == "sentencia":
            acciones.append(pipeline.suggest(
                "Evaluar si la sentencia es recurrible y en qué plazo",
                priority="alta",
                risk="Plazo de apelación es perentorio — verificar CPC Jujuy",
            ))
            riesgos.append("Plazos de recurso son perentorios. Verificar CPC de Jujuy.")

        elif detected_doc_type == "demanda":
            acciones.append(pipeline.suggest(
                "Analizar el objeto de la demanda y pretensiones",
                priority="alta",
            ))
            acciones.append(pipeline.suggest(
                "Evaluar excepciones previas procedentes",
                priority="alta",
            ))

        elif detected_doc_type == "contestacion":
            acciones.append(pipeline.suggest(
                "Contrastar las negativas con los hechos de la demanda original",
                priority="alta",
                risk="Negativas genéricas pueden ser ineficaces",
            ))

        encuadre.append(
            "Jurisdicción: Provincia de Jujuy, Argentina. "
            "Verificar normativa procesal local (CPC Jujuy)."
        )
        if fuero:
            encuadre.append(f"Fuero indicado: {fuero}.")

        # 4. Recuperación de fuentes relevantes (RAG)
        search_profile = "notifications" if detected_doc_type == "notificacion" else "general"
        search_terms = [detected_doc_type] if detected_doc_type != "desconocido" else []
        if fuero:
            search_terms.append(fuero)
        if entities.get("articulo"):
            search_terms += [f"artículo {a}" for a in entities["articulo"][:2]]
        search_query = " ".join(search_terms) if search_terms else text[:300]

        fuentes = await retrieve_sources(
            query=search_query,
            module=search_profile,
            jurisdiction="Jujuy",
            legal_area=fuero,
            top_k=5,
        )

        # 5. Resumen ejecutivo
        if not entities and detected_doc_type == "desconocido":
            resumen = (
                "Sin respaldo documental suficiente para análisis estructurado. "
                "No se detectaron entidades jurídicas relevantes. "
                "Verificar que el texto corresponde a un documento judicial."
            )
        else:
            parts_found = []
            if entities.get("expediente"):
                parts_found.append(f"expediente {entities['expediente'][0]}")
            if detected_doc_type != "desconocido":
                parts_found.append(f"tipo '{detected_doc_type}'")
            if entities.get("caratula"):
                parts_found.append("carátula identificada")

            found_str = ", ".join(parts_found) if parts_found else "entidades parciales"
            fuentes_str = f" — {len(fuentes)} fuente(s) recuperada(s)" if fuentes else ""
            resumen = (
                f"Análisis preliminar: {found_str}{fuentes_str}. "
                "Respaldo parcial — basado en extracción del texto provisto. "
                "Verificar entidades y plazos antes de actuar."
            )

        return pipeline.run(
            resumen_ejecutivo=resumen,
            hechos_relevantes=hechos,
            encuadre_preliminar=encuadre,
            acciones_sugeridas=acciones,
            riesgos_observaciones=riesgos,
            fuentes_respaldo=fuentes,
            datos_faltantes=datos_faltantes,
        )
