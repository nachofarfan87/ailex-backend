"""
AILEX — Workflow integrado desde notificación hasta borrador revisado.
"""

from app.api.schemas.contracts import ConfidenceLevel, MissingData, SourceCitationSchema
from app.modules.analysis.service import AnalysisService
from app.modules.audit.service import AuditService
from app.modules.generation.registry import TemplateRegistry
from app.modules.generation.service import GenerationService
from app.modules.legal.analyze_notification import analyze_notification
from app.modules.notifications.extractor import extract_notification_structure
from app.modules.procedural_deadlines import calculate_deadline, detect_deadlines
from app.modules.strategy.service import StrategyService
from app.modules.workflows.schemas import (
    NormativeReference,
    ReviewSummary,
    SuggestedDocumentInfo,
    WorkflowNotificationRequest,
    WorkflowNotificationResponse,
)
from app.policies.confidence_policy import ConfidencePolicy


class NotificationResponseWorkflow:
    """Orquesta el flujo jurídico integrado sin duplicar lógica de módulos."""

    def __init__(self):
        self._analysis = AnalysisService()
        self._strategy = StrategyService()
        self._generation = GenerationService()
        self._audit = AuditService()

    async def run(
        self,
        request: WorkflowNotificationRequest,
    ) -> WorkflowNotificationResponse:
        text = request.texto or ""
        notification_memo = await analyze_notification(
            text=text,
            jurisdiction="Jujuy",
            legal_area=request.fuero or request.tipo_proceso,
            top_k=5,
        )
        notification_structure = extract_notification_structure(text)
        analysis_doc_type = self._infer_analysis_doc_type(notification_structure, text)
        deadline_detections = [
            calculate_deadline(detection, notification_structure.get("fecha"))
            for detection in detect_deadlines(notification_structure.get("texto_normalizado", text))
        ]

        analysis_response, analysis_validation = await self._analysis.analyze(
            text=text,
            doc_type=analysis_doc_type,
            session_id=request.session_id,
            fuero=request.fuero or request.tipo_proceso,
        )

        strategy_response, strategy_validation = await self._strategy.analyze(
            text=text,
            tipo_proceso=request.tipo_proceso or request.fuero,
            etapa_procesal=request.etapa_procesal or self._infer_stage(notification_memo, notification_structure, deadline_detections),
            objetivo_abogado=request.objetivo_usuario,
            fuentes_recuperadas=[
                source.model_dump()
                for source in self._merge_sources(
                    notification_memo.get("relevant_sources", []),
                    analysis_response.fuentes_respaldo,
                )
            ],
            actuaciones_detectadas=notification_structure.get("actuaciones_detectadas", []),
            plazos_detectados=[detection.to_dict() for detection in deadline_detections],
            session_id=request.session_id,
        )

        suggestion = self._suggest_document_type(
            text=text,
            notification_memo=notification_memo,
            notification_structure=notification_structure,
            deadline_detections=deadline_detections,
            strategy_response=strategy_response,
        )

        generation_response = None
        generation_validation = None
        audit_response = None
        audit_validation = None

        if request.generar_borrador:
            can_generate, generation_reason = self._can_generate(
                suggestion=suggestion,
                request=request,
            )
            if can_generate:
                generation_response, generation_validation = await self._generation.generate(
                    fuero=(request.fuero or request.tipo_proceso or "general"),
                    materia=(request.materia or self._infer_materia(request) or "general"),
                    tipo_escrito=suggestion.tipo_escrito,
                    variante=request.variante_borrador,
                    hechos=text,
                    datos=request.datos_caso,
                    session_id=request.session_id,
                )
                suggestion.borrador_generado = generation_response is not None

                if generation_response:
                    audit_response, audit_validation = await self._audit.review(
                        text=generation_response.borrador,
                        tipo_escrito=suggestion.tipo_escrito,
                        session_id=request.session_id,
                        incluir_version_sugerida=True,
                    )
            else:
                suggestion.motivo_no_generado = generation_reason
        else:
            suggestion.motivo_no_generado = "La generación automática fue deshabilitada en la solicitud."

        fuentes = self._merge_sources(
            notification_memo.get("relevant_sources", []),
            analysis_response.fuentes_respaldo,
            strategy_response.fuentes_respaldo,
            generation_response.fuentes_respaldo if generation_response else [],
            audit_response.fuentes_respaldo if audit_response else [],
        )
        datos_faltantes = self._merge_missing(
            analysis_response.datos_faltantes,
            strategy_response.datos_faltantes,
            generation_response.datos_faltantes if generation_response else [],
            audit_response.datos_faltantes if audit_response else [],
        )
        deadline_warning_risk = [notification_memo["deadline_warning"]] if notification_memo.get("deadline_warning") else []
        riesgos = self._merge_risks(
            notification_memo.get("procedural_risks", []),
            analysis_response.riesgos_observaciones,
            strategy_response.riesgos_observaciones,
            generation_response.riesgos_observaciones if generation_response else [],
            audit_response.riesgos_observaciones if audit_response else [],
            [warning for detection in deadline_detections for warning in detection.advertencias],
            [notification_memo.get("observations", "")],
            deadline_warning_risk,
            self._validation_notes(
                analysis_validation,
                strategy_validation,
                generation_validation,
                audit_validation,
            ),
        )

        confidence_score, confidence_level = self._compute_global_confidence(
            fuentes=fuentes,
            module_scores=[
                analysis_response.confianza_score,
                strategy_response.confianza_score,
                generation_response.confianza_score if generation_response else None,
                audit_response.confianza_score if audit_response else None,
            ],
            missing_count=len(datos_faltantes),
        )

        resumen = self._build_summary(
            analysis_response=analysis_response,
            suggestion=suggestion,
            generated=bool(generation_response),
            reviewed=bool(audit_response),
        )

        estimated_due_date = notification_memo.get("estimated_due_date", "")
        deadline_warning = notification_memo.get("deadline_warning", "")
        normative_references = [
            NormativeReference(**ref)
            for ref in notification_memo.get("normative_references", [])
        ]

        return WorkflowNotificationResponse(
            document_detected=notification_memo.get("document_detected", ""),
            court=notification_memo.get("court", ""),
            case_number=notification_memo.get("case_number", ""),
            notification_date=notification_memo.get("notification_date", ""),
            procedural_action=notification_memo.get("procedural_action", ""),
            deadline=notification_memo.get("deadline", ""),
            critical_date=notification_memo.get("critical_date", ""),
            procedural_risks=notification_memo.get("procedural_risks", []),
            recommended_next_step=notification_memo.get("recommended_next_step", ""),
            observations=notification_memo.get("observations", ""),
            relevant_sources=fuentes,
            confidence=notification_memo.get("confidence", "low"),
            resumen_caso=resumen,
            datos_extraidos={
                "expediente": notification_memo.get("case_number") or notification_structure.get("expediente"),
                "partes": notification_structure.get("partes"),
                "organo": notification_memo.get("court") or notification_structure.get("organo"),
                "fecha": notification_memo.get("notification_date") or notification_structure.get("fecha"),
                "texto_normalizado": notification_memo.get("normalized_text") or notification_structure.get("texto_normalizado"),
            },
            actuacion_detectada=notification_memo.get("procedural_action") or self._first_action(notification_structure),
            plazo_detectado=notification_memo.get("deadline") or self._first_deadline_phrase(notification_structure, deadline_detections),
            vencimiento_estimado=estimated_due_date or notification_memo.get("critical_date") or self._first_due_date(deadline_detections),
            estimated_due_date=estimated_due_date,
            deadline_type=notification_memo.get("deadline_type", ""),
            deadline_basis=notification_memo.get("deadline_basis", ""),
            deadline_warning=deadline_warning,
            riesgos_inmediatos=riesgos,
            opciones_estrategicas_resumidas=strategy_response.opciones_estrategicas,
            comparacion_opciones=strategy_response.comparacion_opciones,
            tipo_escrito_sugerido=suggestion,
            borrador_inicial=generation_response.borrador if generation_response else None,
            observaciones_revision=self._build_review_summary(audit_response),
            fuentes_respaldo=fuentes,
            datos_faltantes=datos_faltantes,
            nivel_confianza_global=confidence_level,
            confianza_score_global=confidence_score,
            normative_references=normative_references,
            normative_confidence=notification_memo.get("normative_confidence"),
            normative_warning=notification_memo.get("normative_warning"),
            normative_summary=notification_memo.get("normative_summary"),
        )

    def _infer_analysis_doc_type(self, notification_structure: dict, text: str) -> str | None:
        if (
            notification_structure.get("expediente")
            or notification_structure.get("organo")
            or notification_structure.get("actuaciones_detectadas")
            or notification_structure.get("plazos_detectados")
        ):
            return "notificacion"
        if "sentencia" in text.casefold():
            return "sentencia"
        return None

    def _infer_stage(self, notification_memo: dict, notification_structure: dict, deadline_detections: list) -> str | None:
        action_slug = notification_memo.get("procedural_action", "").casefold()
        if "traslado" in action_slug:
            return "traslado"
        if "intimacion" in action_slug:
            return "intimacion"
        if "audiencia" in action_slug:
            return "audiencia"

        actions = notification_structure.get("actuaciones_detectadas", [])
        if any((item.get("tipo") or "").casefold() == "traslado" for item in actions):
            return "traslado"
        if any((item.get("tipo") or "").casefold() == "intimacion" for item in actions):
            return "intimación"
        if any((item.tipo_actuacion or "") == "plazo_para_apelar" for item in deadline_detections):
            return "recurso"
        return None

    def _infer_materia(self, request: WorkflowNotificationRequest) -> str | None:
        if request.datos_caso and request.datos_caso.get("materia"):
            return str(request.datos_caso["materia"])
        return request.tipo_proceso

    def _suggest_document_type(
        self,
        text: str,
        notification_memo: dict,
        notification_structure: dict,
        deadline_detections: list,
        strategy_response,
    ) -> SuggestedDocumentInfo:
        text_lower = text.casefold()
        memo_action = (notification_memo.get("procedural_action") or "").casefold()
        actions = {(item.get("tipo") or "").casefold() for item in notification_structure.get("actuaciones_detectadas", [])}
        deadline_types = {(item.tipo_actuacion or "").casefold() for item in deadline_detections}
        option_names = {option.nombre for option in strategy_response.opciones_estrategicas}
        templates = set(TemplateRegistry.get_tipos_disponibles())

        suggested_type = None
        reason = "No hay base suficiente para sugerir un escrito único sin más verificación."

        if "traslado" in memo_action or "traslado" in actions or "plazo_para_contestar" in deadline_types:
            suggested_type = "contesta_traslado"
            reason = "Se detectó traslado o plazo de respuesta; un escrito de contestación o respuesta inicial aparece como opción natural a evaluar."
        elif ("intimacion" in memo_action or "intimacion" in actions) and any(word in text_lower for word in ("document", "acompañ", "acompan", "adjunt")):
            suggested_type = "acompana_documentacion"
            reason = "La intimación parece vinculada a acompañar o completar documental."
        elif "demora" in text_lower or "pronto despacho" in text_lower or "resolución pendiente" in text_lower:
            suggested_type = "pronto_despacho"
            reason = "El cuadro relatado sugiere una demora o resolución pendiente compatible con pronto despacho."
        elif "subsanar presentación" in option_names or "reformular escrito" in option_names or "subsan" in text_lower:
            suggested_type = "subsanar/reformular"
            reason = "El problema parece más cercano a subsanar o reformular la presentación que a impulsar un escrito estándar ya disponible."
        elif "esperar constancia o documentación antes de actuar" in option_names:
            reason = "La información disponible todavía favorece esperar constancia o documentación antes de preparar un escrito."

        available = suggested_type in templates if suggested_type else False
        return SuggestedDocumentInfo(
            tipo_escrito=suggested_type,
            razon=reason,
            disponible_en_generador=available,
            borrador_generado=False,
        )

    def _can_generate(
        self,
        suggestion: SuggestedDocumentInfo,
        request: WorkflowNotificationRequest,
    ) -> tuple[bool, str]:
        if not suggestion.tipo_escrito:
            return False, "No hay un tipo de escrito suficientemente definido para generar borrador."
        if not suggestion.disponible_en_generador:
            return False, "La sugerencia táctica actual no tiene una plantilla compatible en el generador."
        if not (request.fuero or request.tipo_proceso):
            return False, "Falta fuero o tipo de proceso para encuadrar el borrador base con prudencia."
        if not request.texto or len(request.texto.strip()) < 20:
            return False, "El texto base es demasiado escaso para generar un borrador útil."
        return True, ""

    def _build_review_summary(self, audit_response) -> ReviewSummary:
        if not audit_response:
            return ReviewSummary()
        return ReviewSummary(
            diagnostico_general=audit_response.diagnostico_general,
            severidad_general=audit_response.severidad_general.value,
            hallazgos_clave=[hallazgo.observacion for hallazgo in audit_response.hallazgos[:5]],
            mejoras_sugeridas=audit_response.mejoras_sugeridas[:5],
            version_sugerida=audit_response.version_sugerida,
        )

    def _merge_sources(self, *groups) -> list[SourceCitationSchema]:
        merged = []
        seen = set()
        for group in groups:
            for source in group or []:
                if not isinstance(source, SourceCitationSchema):
                    continue
                key = (
                    source.document_id,
                    source.document_title,
                    source.page_or_section,
                    source.fragment,
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(source)
        return merged

    def _merge_missing(self, *groups) -> list[MissingData]:
        merged = []
        seen = set()
        for group in groups:
            for missing in group or []:
                if not isinstance(missing, MissingData):
                    continue
                key = (missing.description, missing.required_for or "")
                if key in seen:
                    continue
                seen.add(key)
                merged.append(missing)
        return merged

    def _merge_risks(self, *groups) -> list[str]:
        merged = []
        seen = set()
        for group in groups:
            for risk in group or []:
                risk = str(risk).strip()
                if not risk or risk in seen:
                    continue
                seen.add(risk)
                merged.append(risk)
        return merged[:12]

    def _validation_notes(self, *validations) -> list[str]:
        notes = []
        labels = ["análisis", "estrategia", "generación", "revisión"]
        for label, validation in zip(labels, validations):
            if validation is not None and not validation.is_valid:
                notes.append(
                    f"El módulo de {label} dejó observaciones de validación: revisar el resultado antes de usarlo operativamente."
                )
        return notes

    def _compute_global_confidence(
        self,
        fuentes: list[SourceCitationSchema],
        module_scores: list[float | None],
        missing_count: int,
    ) -> tuple[float, ConfidenceLevel]:
        """
        Regla de nivel_confianza_global del workflow:

        1. Sin fuentes y score==0 → SIN_RESPALDO (obligatorio, no BAJO).
        2. Sin fuentes pero score>0 (solo inferencia de módulos) → BAJO.
        3. Con fuentes → ConfidencePolicy.calculate() por jerarquía y relevancia:
           - Solo fuentes normativa/jurisprudencia pueden alcanzar ALTO (score>=0.75).
           - Solo doctrina/interno → máximo MEDIO (score<0.75).
        4. Penalización: 2+ datos_faltantes descuenta 0.10 del score final.
        5. El score global es el mínimo entre source_score y el máximo de los
           scores individuales de módulos (evita inflar si hay bajo respaldo).
        """
        sources_for_policy = []
        for source in fuentes:
            hierarchy = source.source_hierarchy
            hierarchy = hierarchy.value if hasattr(hierarchy, "value") else hierarchy
            sources_for_policy.append(
                {
                    "hierarchy": hierarchy,
                    "relevance": source.relevance_score,
                }
            )

        source_score, source_level = ConfidencePolicy.calculate(sources_for_policy)
        usable_scores = [score for score in module_scores if isinstance(score, (int, float))]
        if usable_scores:
            score = min(source_score if source_score > 0 else max(usable_scores), max(usable_scores))
        else:
            score = source_score

        if missing_count >= 2:
            score = max(score - 0.1, 0.0)

        if not fuentes and score == 0.0:
            return 0.0, ConfidenceLevel.SIN_RESPALDO

        if not fuentes and score < ConfidencePolicy.THRESHOLD_MEDIO:
            return round(score, 3), ConfidenceLevel.BAJO

        return round(score, 3), ConfidencePolicy.classify(score if score > 0 else source_score)

    def _build_summary(
        self,
        analysis_response,
        suggestion: SuggestedDocumentInfo,
        generated: bool,
        reviewed: bool,
    ) -> str:
        parts = [analysis_response.resumen_ejecutivo]
        if suggestion.tipo_escrito:
            parts.append(f"Escrito sugerido para evaluar: {suggestion.tipo_escrito}.")
        else:
            parts.append("No surge todavía un escrito único para generar sin mayor contraste.")
        if generated:
            parts.append("Se generó un borrador base.")
        if reviewed:
            parts.append("El borrador pasó por revisión automática.")
        return " ".join(parts).strip()

    def _first_action(self, notification_structure: dict) -> str | None:
        actions = notification_structure.get("actuaciones_detectadas", [])
        if not actions:
            return None
        return actions[0].get("texto") or actions[0].get("tipo")

    def _first_deadline_phrase(self, notification_structure: dict, deadline_detections: list) -> str | None:
        if deadline_detections:
            return deadline_detections[0].frase_detectada
        plazos = notification_structure.get("plazos_detectados", [])
        if not plazos:
            return None
        return plazos[0].get("texto")

    def _first_due_date(self, deadline_detections: list) -> str | None:
        for detection in deadline_detections:
            if detection.fecha_vencimiento:
                return detection.fecha_vencimiento
        return None
