# c:\Users\nacho\Documents\APPS\AILEX\backend\legal_engine\response_postprocessor.py
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from app.services import conversation_observability_service
from app.services.case_state_extractor_service import (
    PROGRESSION_TO_CASE_STAGE,
    case_state_extractor_service,
)
from app.services.case_followup_service import case_followup_service
from app.services.case_confidence_service import resolve_case_confidence
from app.services.case_progress_service import (
    build_case_progress,
    extract_case_progress_snapshot,
)
from app.services.case_progress_narrative_service import case_progress_narrative_service
from app.services.case_summary_service import case_summary_service
from app.services.case_workspace_service import build_case_workspace
from app.services.professional_judgment_service import build_professional_judgment
from app.services.smart_strategy_service import resolve_smart_strategy
from app.services.conversation_integrity_service import (
    build_integrity_state,
    should_allow_followup,
)
from app.services.strategy_composition_service import resolve_strategy_composition_profile
from app.services.strategy_language_service import resolve_strategy_language_profile
from app.services.response_composition_service import resolve_response_composition
from app.services.conversation_consistency_service import resolve_consistency_policy
from app.services.case_state_service import case_state_service
from app.services.conversation_state_service import conversation_state_service
from app.services.conversational_intelligence_service import (
    apply_conversational_intelligence_to_policy,
    resolve_conversational_intelligence,
)
from app.services.dialogue_policy_service import resolve_dialogue_policy
from app.services.execution_output_service import build_execution_output
from app.services.intent_resolution_service import resolve_intent_resolution
from app.services.legal_reasoning_service import (
    build_legal_reasoning,
    format_legal_reasoning_as_text,
)
from app.services.output_mode_service import apply_output_mode_progression
from app.services.progression_policy import (
    finalize_progression_state,
    resolve_progression_policy,
)
from app.services.utc import utc_now
from legal_engine.orchestrator_schema import FinalOutput, RetrievalBundle, StrategyBundle
from app.services.adaptive_followup_service import resolve_followup_decision

_QUICK_START_PREFIX = "Primer paso recomendado:"
_QUICK_START_SIMILARITY_THRESHOLD = 0.75

_NOISE_PATTERNS = (
    "fallback generico",
    "fallback",
    "generic",
    "missing handler",
    "modelo no aplicable",
    "internal_fallback",
    "no se encontro un patron",
    "razonamiento normativo generico",
)

logger = logging.getLogger(__name__)


class ResponsePostprocessor:
    def postprocess(
        self,
        *,
        request_id: str,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        retrieval: RetrievalBundle,
        strategy: StrategyBundle,
        db: Any | None = None,
    ) -> FinalOutput:
        raw_response_text = self._build_response_text(pipeline_payload)
        response_text = self._sanitize_text(raw_response_text)
        if (
            not bool(dict(pipeline_payload.get("conversational") or {}).get("should_ask_first"))
            and not bool(dict(pipeline_payload.get("core_legal_response") or {}).get("action_steps"))
        ):
            response_text = self._prepend_quick_start(
                response_text,
                pipeline_payload.get("quick_start"),
                output_mode=pipeline_payload.get("output_mode"),
            )
        response_text = self._apply_prudence(
            response_text=response_text,
            pipeline_payload=pipeline_payload,
            retrieval=retrieval,
            strategy=strategy,
        )

        api_payload = self._build_api_payload(
            request_id=request_id,
            response_text=response_text,
            pipeline_payload=pipeline_payload,
            retrieval=retrieval,
            strategy=strategy,
        )
        self._attach_conversation_state(
            db=db,
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
        )
        self._attach_dialogue_policy(
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
        )
        self._attach_conversational_intelligence(
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
        )

        # 8.2D — Composition layer
        # Recompone la presentación de la respuesta para mayor continuidad narrativa.
        # Si falla, response_text queda intacto.
        response_text = self._attach_intent_resolution_and_execution_output(
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
            response_text=response_text,
        )
        response_text = self._attach_progression_policy(
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
            response_text=response_text,
        )

        # FASE 9 — Professional-grade reasoning
        # Inyecta el bloque de razonamiento jurídico estructurado ANTES de los pasos prácticos.
        # Si falla, response_text queda intacto.
        self._attach_case_state(
            db=db,
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
        )
        # FASE 13A — Case Memory: consolida hechos, partes y faltantes del turno
        self._attach_case_memory(api_payload=api_payload)
        self._attach_case_progress(api_payload=api_payload)
        self._attach_case_followup(api_payload=api_payload)
        self._attach_case_confidence(api_payload=api_payload)
        self._attach_smart_strategy(api_payload=api_payload)
        self._attach_strategy_composition_profile(api_payload=api_payload)
        self._apply_followup_integrity_arbitration(api_payload=api_payload)
        # FASE 12.7 — consistency policy antes que language profile para pasar stable_bucket
        self._attach_consistency_policy(api_payload=api_payload)
        self._attach_strategy_language_profile(api_payload=api_payload)
        self._attach_case_summary(
            db=db,
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
        )
        self._attach_case_workspace(api_payload=api_payload)
        self._attach_case_progress_narrative(api_payload=api_payload)
        self._attach_professional_judgment(api_payload=api_payload)
        response_text = self._transform_response_by_output_mode(
            response_text=response_text,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
        )
        response_text = self._inject_case_progress_narrative(
            response_text=response_text,
            api_payload=api_payload,
        )
        response_text = self._inject_legal_reasoning(
            response_text=response_text,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
        )

        api_payload["response_text"] = response_text
        response_text = self._apply_conversation_composer(
            api_payload=api_payload,
            response_text=response_text,
        )
        api_payload["response_text"] = response_text

        try:
            output_mode = self._get_output_mode(api_payload)
            self._get_strategy_composition_profile(api_payload)
            self._get_strategy_language_profile(api_payload)
            case_followup = dict(api_payload.get("case_followup") or {})
            has_followup = bool(case_followup.get("should_ask")) and bool(str(case_followup.get("question") or "").strip())
            if output_mode == "orientacion_inicial":
                response_text = self._normalize_closing(response_text, has_followup=has_followup)
            else:
                response_text = self._normalize_opening(response_text, output_mode)
                response_text = self._normalize_final_response(response_text, output_mode=output_mode)
                response_text = self._normalize_closing(response_text, has_followup=has_followup)
                response_text = self._apply_length_limits(response_text, output_mode=output_mode)
            api_payload["response_text"] = response_text
        except Exception:
            logger.exception("No se pudo normalizar la respuesta final.")

        # 8.3 — Persist conversation memory
        # Registra en el snapshot lo que pasó en este turno (policy + composer).
        # Si falla, no afecta la respuesta.
        self._persist_conversation_memory(db=db, api_payload=api_payload)
        # 13A — Persist case memory
        self._persist_case_memory(db=db, api_payload=api_payload)
        self._persist_case_progress(db=db, api_payload=api_payload)
        self._persist_conversation_progression(
            db=db,
            api_payload=api_payload,
            response_text=response_text,
        )

        try:
            conversational = pipeline_payload.get("conversational") or {}
            conversation_memory = conversational.get("conversation_memory") or {}
            conversation_observability_service.record_observation(
                turn_input=normalized_input,
                response=api_payload,
                memory=conversation_memory if isinstance(conversation_memory, dict) else None,
            )
        except Exception:
            pass

        return FinalOutput(
            request_id=request_id,
            response_text=response_text,
            pipeline_version=self._safe_pipeline_version(api_payload.get("pipeline_version")),
            case_domain=str(api_payload.get("case_domain") or ""),
            action_slug=str(api_payload.get("action_slug") or ""),
            source_mode=str(api_payload.get("source_mode") or "unknown"),
            documents_considered=self._safe_int(api_payload.get("documents_considered")),
            strategy_mode=str(api_payload.get("strategy_mode") or ""),
            dominant_factor=str(api_payload.get("dominant_factor") or ""),
            blocking_factor=str(api_payload.get("blocking_factor") or ""),
            execution_readiness=str(api_payload.get("execution_readiness") or ""),
            confidence_score=api_payload.get("confidence_score"),
            confidence_label=str(api_payload.get("confidence_label") or "low"),
            fallback_used=bool(api_payload.get("fallback_used")),
            fallback_reason=str(api_payload.get("fallback_reason") or ""),
            sanitized_output=response_text != raw_response_text,
            warnings=list(api_payload.get("warnings") or []),
            api_payload=api_payload,
        )

    # FASE 9 — Legal Reasoning

    def _inject_legal_reasoning(
        self,
        *,
        response_text: str,
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> str:
        """
        Extrae contexto del pipeline, construye el razonamiento jurídico estructurado
        y lo antepone al texto de respuesta (antes de los pasos prácticos).
        Si falla o el resultado está vacío, devuelve response_text sin modificar.
        """
        try:
            case_profile = pipeline_payload.get("case_profile") or {}
            procedural_case_state = pipeline_payload.get("procedural_case_state") or {}
            classification = pipeline_payload.get("classification") or {}

            context = {
                "facts": case_profile.get("facts") or pipeline_payload.get("facts") or "",
                "detected_intent": (
                    classification.get("detected_intent")
                    or pipeline_payload.get("detected_intent")
                    or ""
                ),
                "legal_area": (
                    case_profile.get("legal_area")
                    or case_profile.get("case_domain")
                    or pipeline_payload.get("legal_area")
                    or api_payload.get("case_domain")
                    or ""
                ),
                "urgency_level": (
                    case_profile.get("urgency_level")
                    or pipeline_payload.get("urgency_level")
                    or "low"
                ),
                "has_children": bool(
                    case_profile.get("has_children")
                    or pipeline_payload.get("has_children")
                ),
                "agreement_level": (
                    case_profile.get("agreement_level")
                    or pipeline_payload.get("agreement_level")
                    or "none"
                ),
                "blocking_factors": (
                    procedural_case_state.get("blocking_factor")
                    or pipeline_payload.get("blocking_factor")
                    or ""
                ),
                "procedural_posture": (
                    case_profile.get("procedural_posture")
                    or pipeline_payload.get("procedural_posture")
                    or ""
                ),
            }

            reasoning = build_legal_reasoning(context)
            api_payload["legal_reasoning"] = reasoning
            output_mode = self._get_output_mode(api_payload)
            if output_mode != "orientacion_inicial":
                return response_text

            block = format_legal_reasoning_as_text(reasoning).strip()
            if block:
                return f"{block}\n\n{response_text}" if response_text else block
        except Exception:
            logger.exception("No se pudo construir el razonamiento jurídico (Fase 9).")

        return response_text

    def _transform_response_by_output_mode(
        self,
        *,
        response_text: str,
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> str:
        output_mode = self._get_output_mode(api_payload)
        if output_mode == "orientacion_inicial":
            return response_text

        try:
            followup_question = self._resolve_followup_question(
                api_payload,
                dict(api_payload.get("execution_output") or {}),
                output_mode=output_mode,
            )
            composed = resolve_response_composition(
                output_mode=output_mode,
                smart_strategy=dict(api_payload.get("smart_strategy") or {}),
                strategy_composition_profile=self._get_strategy_composition_profile(api_payload),
                strategy_language_profile=self._get_strategy_language_profile(api_payload),
                conversation_state=dict(api_payload.get("conversation_state") or {}),
                dialogue_policy=dict(api_payload.get("dialogue_policy") or {}),
                execution_output=dict(api_payload.get("execution_output") or {}),
                progression_policy=dict(api_payload.get("progression_policy") or {}),
                pipeline_payload=pipeline_payload,
                api_payload=api_payload,
                followup_question=followup_question,
            )
            if composed:
                api_payload["response_composition"] = composed
                # Cache composition metadata so _normalize_closing can read it
                self._composition_metadata = dict(composed.get("composition_metadata") or {})
                strategic_decision = dict(composed.get("strategic_decision") or {})
                if strategic_decision:
                    api_payload["strategic_decision"] = strategic_decision
                rendered = str(composed.get("rendered_response_text") or "").strip()
                if rendered:
                    return rendered
        except Exception:
            logger.exception("No se pudo transformar la respuesta segun output_mode.")
            return response_text
        return response_text

    def _render_structuring_response(
        self,
        *,
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> str:
        composed = resolve_response_composition(
            output_mode="estructuracion",
            smart_strategy=dict(api_payload.get("smart_strategy") or {}),
            strategy_composition_profile=self._get_strategy_composition_profile(api_payload),
            strategy_language_profile=self._get_strategy_language_profile(api_payload),
            conversation_state=dict(api_payload.get("conversation_state") or {}),
            dialogue_policy=dict(api_payload.get("dialogue_policy") or {}),
            execution_output=dict(api_payload.get("execution_output") or {}),
            progression_policy=dict(api_payload.get("progression_policy") or {}),
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
            followup_question=self._resolve_followup_question(
                api_payload,
                dict(api_payload.get("execution_output") or {}),
                output_mode="estructuracion",
            ),
        )
        return str(composed.get("rendered_response_text") or "").strip()

    def _render_strategy_response(
        self,
        *,
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> str:
        composed = resolve_response_composition(
            output_mode="estrategia",
            smart_strategy=dict(api_payload.get("smart_strategy") or {}),
            strategy_composition_profile=self._get_strategy_composition_profile(api_payload),
            strategy_language_profile=self._get_strategy_language_profile(api_payload),
            conversation_state=dict(api_payload.get("conversation_state") or {}),
            dialogue_policy=dict(api_payload.get("dialogue_policy") or {}),
            execution_output=dict(api_payload.get("execution_output") or {}),
            progression_policy=dict(api_payload.get("progression_policy") or {}),
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
            followup_question=self._resolve_followup_question(
                api_payload,
                dict(api_payload.get("execution_output") or {}),
                output_mode="estrategia",
            ),
        )
        strategic_decision = dict(composed.get("strategic_decision") or {})
        if strategic_decision:
            api_payload["strategic_decision"] = strategic_decision
        return str(composed.get("rendered_response_text") or "").strip()

    def _render_execution_response(
        self,
        *,
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> str:
        composed = resolve_response_composition(
            output_mode="ejecucion",
            smart_strategy=dict(api_payload.get("smart_strategy") or {}),
            strategy_composition_profile=self._get_strategy_composition_profile(api_payload),
            strategy_language_profile=self._get_strategy_language_profile(api_payload),
            conversation_state=dict(api_payload.get("conversation_state") or {}),
            dialogue_policy=dict(api_payload.get("dialogue_policy") or {}),
            execution_output=dict(api_payload.get("execution_output") or {}),
            progression_policy=dict(api_payload.get("progression_policy") or {}),
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
            followup_question=self._resolve_followup_question(
                api_payload,
                dict(api_payload.get("execution_output") or {}),
                output_mode="ejecucion",
            ),
        )
        return str(composed.get("rendered_response_text") or "").strip()

    def _resolve_followup_question(
        self,
        api_payload: dict[str, Any],
        execution_output: dict[str, Any],
        output_mode: str = "",
    ) -> str:
        case_followup = dict(api_payload.get("case_followup") or {})
        profile = self._get_strategy_composition_profile(api_payload)
        if case_followup:
            if not bool(profile.get("allow_followup", True)):
                return ""
            if bool(case_followup.get("should_ask")):
                decision = should_allow_followup(
                    api_payload=api_payload,
                    question=str(case_followup.get("question") or "").strip(),
                    need_key=str(case_followup.get("need_key") or "").strip(),
                )
                if not decision.get("should_allow_followup"):
                    return ""
                case_followup_question = str(case_followup.get("question") or "").strip()
                if not self._should_include_followup_question(
                    api_payload=api_payload,
                    execution_output=execution_output,
                    output_mode=output_mode,
                    question=case_followup_question,
                ):
                    return ""
                return case_followup_question
            return ""

        execution_data = dict(execution_output.get("execution_output") or {})
        question = str(execution_data.get("followup_question") or "").strip()
        if not question:
            conversational = dict(api_payload.get("conversational") or {})
            question = str(conversational.get("question") or "").strip()
        if not question:
            progression_policy = dict(api_payload.get("progression_policy") or {})
            missing_focus = list(progression_policy.get("missing_focus") or [])
            if missing_focus:
                question = self._normalize_followup_question(str(missing_focus[0]).strip())
        else:
            question = self._normalize_followup_question(question)

        if not question:
            return ""
        decision = should_allow_followup(
            api_payload=api_payload,
            question=question,
        )
        if not decision.get("should_allow_followup"):
            return ""
        if not self._should_include_followup_question(
            api_payload=api_payload,
            execution_output=execution_output,
            output_mode=output_mode,
            question=question,
        ):
            return ""
        return question

    def _normalize_followup_question(self, question: str) -> str:
        text = self._normalize_whitespace(question)
        if not text:
            return ""
        if text.endswith("?") and ("¿" in text or text.startswith(("Que ", "Como ", "Cual ", "Donde ", "Quien "))):
            return text
        if text.endswith("?"):
            return text if text.startswith("¿") else f"¿{text}"
        lowered = text.lower().rstrip(".:;")
        lowered = re.sub(r"^(necesito precisar|precisar|confirmar|definir|verificar)\s+", "", lowered).strip()
        if not lowered:
            return ""
        return f"¿{lowered[0].upper()}{lowered[1:]}?"

    def _should_include_followup_question(
        self,
        *,
        api_payload: dict[str, Any],
        execution_output: dict[str, Any],
        output_mode: str,
        question: str,
    ) -> bool:
        """
        Decide si conviene terminar con follow-up.

        Regla buscada: solo preguntar cuando mejora la siguiente decision o accion.
        """
        if not str(question or "").strip():
            return False

        case_followup = dict(api_payload.get("case_followup") or {})
        has_explicit_case_followup = bool(case_followup.get("should_ask")) and bool(
            str(case_followup.get("question") or "").strip()
        )
        dialogue_policy = dict(api_payload.get("dialogue_policy") or {})
        action = str(dialogue_policy.get("action") or "").strip().lower()
        if action not in {"ask", "hybrid"} and not has_explicit_case_followup:
            return False

        conversation_state = dict(api_payload.get("conversation_state") or {})
        progress = dict(conversation_state.get("progress_signals") or {})
        case_progress = dict(api_payload.get("case_progress") or {})
        blocking_missing = bool(progress.get("blocking_missing"))
        completeness = str(progress.get("case_completeness") or "low").strip().lower()
        dominant_purpose = str(dialogue_policy.get("dominant_missing_purpose") or "").strip().lower()
        next_step_type = str(case_progress.get("next_step_type") or "").strip().lower()
        progress_status = str(case_progress.get("progress_status") or "").strip().lower()
        readiness_label = str(case_progress.get("readiness_label") or "").strip().lower()
        has_blockers = bool(list(case_progress.get("blocking_issues") or []))
        critical_gap_count = len(list(case_progress.get("critical_gaps") or []))

        if has_explicit_case_followup and not dialogue_policy:
            if next_step_type == "execute" or (
                readiness_label == "high" and not has_blockers and critical_gap_count == 0
            ):
                return False
            return True

        if completeness in {"high", "very_high"} and not blocking_missing:
            return False
        if next_step_type == "resolve_contradiction":
            return True
        if next_step_type == "execute" or (readiness_label == "high" and not has_blockers and critical_gap_count == 0):
            return False
        if progress_status == "blocked" and next_step_type not in {"ask", "resolve_contradiction"}:
            return False
        if output_mode == "ejecucion" and self._has_clear_execution_steps(execution_output):
            return False
        if blocking_missing:
            return True
        if output_mode == "ejecucion":
            return blocking_missing and dominant_purpose in {"enable"}
        if output_mode == "estrategia":
            return (
                blocking_missing
                or dominant_purpose in {"enable"}
            )
        if output_mode == "estructuracion":
            return action == "ask" or dominant_purpose in {"enable", "identify", "quantify"}

        if execution_output.get("applies"):
            return dominant_purpose in {"enable", "identify"}
        return True

    def _truncate_text(self, text: str, max_chars: int = 180) -> str:
        value = self._normalize_whitespace(text)
        if len(value) <= max_chars:
            return value
        truncated = value[: max_chars + 1]
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        truncated = truncated.rstrip(" ,.;:")
        return f"{truncated}..." if truncated else value[:max_chars].rstrip() + "..."

    # 8.2D — Conversation Composer

    def _apply_conversation_composer(
        self,
        *,
        api_payload: dict[str, Any],
        response_text: str,
    ) -> str:
        """
        Aplica la capa de composición conversacional (Fase 8.2D).

        Requiere que conversation_state y dialogue_policy ya estén adjuntos.
        Si faltan, o si el composer falla, devuelve response_text sin modificar.
        El resultado de composición se adjunta a api_payload["composer_output"].
        """
        conversation_state = api_payload.get("conversation_state")
        dialogue_policy = api_payload.get("dialogue_policy")
        core_legal_response = dict(api_payload.get("core_legal_response") or {})
        if (
            str(core_legal_response.get("direct_answer") or "").strip()
            and list(core_legal_response.get("action_steps") or [])
        ):
            return response_text

        if not isinstance(conversation_state, dict) or not conversation_state:
            return response_text
        if not isinstance(dialogue_policy, dict) or not dialogue_policy:
            return response_text

        try:
            from app.services.conversation_composer_service import compose

            result = compose(
                conversation_state=conversation_state,
                dialogue_policy=dialogue_policy,
                response_text=response_text,
                pipeline_payload={
                    "output_mode": api_payload.get("output_mode"),
                    "progression_policy": api_payload.get("progression_policy"),
                    "smart_strategy": api_payload.get("smart_strategy"),
                    "strategy_composition_profile": api_payload.get("strategy_composition_profile"),
                    "strategy_language_profile": api_payload.get("strategy_language_profile"),
                },
                consistency_policy=dict(api_payload.get("consistency_policy") or {}),
            )
            if result:
                api_payload["composer_output"] = result
                composed = str(result.get("composed_response_text") or "").strip()
                if composed:
                    if len(composed) > 1200:
                        composed = composed[:1200].rsplit(" ", 1)[0] + "..."
                    return composed
        except Exception:
            logger.exception("No se pudo aplicar conversation composer (8.2D).")

        return response_text

    def _inject_case_progress_narrative(
        self,
        *,
        response_text: str,
        api_payload: dict[str, Any],
    ) -> str:
        narrative = dict(api_payload.get("case_progress_narrative") or {})
        if not narrative or not narrative.get("applies"):
            return response_text

        output_mode = self._get_output_mode(api_payload)
        paragraphs = [
            str(narrative.get("opening") or "").strip(),
            str(narrative.get("known_block") or "").strip(),
            str(narrative.get("contradiction_block") or "").strip(),
            str(narrative.get("missing_block") or "").strip(),
            str(narrative.get("progress_block") or "").strip(),
            str(narrative.get("priority_block") or "").strip(),
        ]
        unique_paragraphs = [
            paragraph
            for paragraph in paragraphs
            if paragraph and not self._response_contains_similar_block(response_text, paragraph)
        ]
        if not unique_paragraphs:
            return response_text

        response_paragraphs = self._split_paragraphs(response_text)
        trailing_question = ""
        if response_paragraphs and "?" in response_paragraphs[-1]:
            trailing_question = response_paragraphs.pop()

        if output_mode == "ejecucion":
            concise = next(
                (
                    paragraph
                    for paragraph in unique_paragraphs
                    if paragraph.casefold().startswith("con lo que ya esta definido")
                ),
                unique_paragraphs[-1],
            )
            parts = [*response_paragraphs, concise]
            if trailing_question:
                parts.append(trailing_question)
            return "\n\n".join(part for part in parts if part).strip()

        opening = str(narrative.get("opening") or "").strip()
        known_block = str(narrative.get("known_block") or "").strip()
        contradiction_block = str(narrative.get("contradiction_block") or "").strip()
        missing_block = str(narrative.get("missing_block") or "").strip()
        progress_block = str(narrative.get("progress_block") or "").strip()
        priority_block = str(narrative.get("priority_block") or "").strip()

        if output_mode == "estructuracion":
            preferred_blocks = [known_block, contradiction_block, missing_block, progress_block]
        elif output_mode == "estrategia":
            preferred_blocks = [progress_block, contradiction_block, priority_block, missing_block]
        else:
            preferred_blocks = [opening, known_block, contradiction_block, progress_block, missing_block, priority_block]

        selected_narrative: list[str] = []
        for paragraph in preferred_blocks:
            if not paragraph or paragraph not in unique_paragraphs or paragraph in selected_narrative:
                continue
            selected_narrative.append(paragraph)
            if len(selected_narrative) >= 2:
                break

        if response_paragraphs and opening in selected_narrative:
            selected_narrative = [paragraph for paragraph in selected_narrative if paragraph != opening]
        if not selected_narrative:
            return response_text

        if response_paragraphs:
            inline_additions = " ".join(selected_narrative).strip()
            first_paragraph = response_paragraphs[0]
            if inline_additions and not self._response_contains_similar_block(first_paragraph, inline_additions):
                response_paragraphs[0] = f"{first_paragraph} {inline_additions}".strip()
            parts = response_paragraphs
        else:
            parts = selected_narrative
        if trailing_question:
            parts.append(trailing_question)
        return "\n\n".join(part for part in parts if part).strip()

    def _normalize_opening(self, text: str, output_mode: str) -> str:
        profile = self._current_strategy_composition_profile
        language_profile = self._current_strategy_language_profile
        opening_style = str(profile.get("opening_style") or "").strip().lower() if profile else ""
        preferred_opening = str(language_profile.get("selected_opening") or "").strip()
        paragraphs = self._split_paragraphs(text)
        if not paragraphs:
            return text

        if opening_style == "none":
            while len(paragraphs) > 1 and not self._paragraph_is_actionable(paragraphs[0]):
                paragraphs.pop(0)
            return "\n\n".join(paragraphs).strip()

        generic_openers = (
            "para orientarte mejor",
            "para avanzar con una orientacion mas firme",
            "hay base para orientar",
        )

        if output_mode == "estructuracion":
            kept = [paragraph for paragraph in paragraphs if not paragraph.casefold().startswith(generic_openers)]
            if kept and kept[0].casefold().startswith("con lo que me contaste hasta ahora"):
                return "\n\n".join(kept).strip()
            if preferred_opening:
                return "\n\n".join([preferred_opening, *kept[:3]]).strip()
            return "\n\n".join([
                "Con lo que me contaste hasta ahora...",
                *kept[:3],
            ]).strip()

        if output_mode == "estrategia":
            while len(paragraphs) > 1 and paragraphs[0].casefold().startswith(generic_openers + ("con lo que me contaste",)):
                paragraphs.pop(0)
            return "\n\n".join(paragraphs).strip()

        if output_mode == "ejecucion":
            while len(paragraphs) > 1 and not self._paragraph_is_actionable(paragraphs[0]):
                paragraphs.pop(0)
            return "\n\n".join(paragraphs).strip()

        return "\n\n".join(paragraphs).strip()

    def _normalize_final_response(self, text: str, *, output_mode: str = "orientacion_inicial") -> str:
        paragraphs = self._split_paragraphs(text)
        if not paragraphs:
            return text

        normalized_paragraphs: list[str] = []

        for paragraph in paragraphs:
            if any(self._normalize_similarity_text(paragraph) == self._normalize_similarity_text(existing) for existing in normalized_paragraphs):
                continue
            if any(
                min(len(paragraph), len(existing)) > 80 and self._paragraph_similarity(paragraph, existing) > 0.9
                for existing in normalized_paragraphs
            ):
                continue
            normalized_paragraphs.append(paragraph)

        if output_mode != "orientacion_inicial" and len(normalized_paragraphs) > 4:
            if "?" in normalized_paragraphs[-1]:
                normalized_paragraphs = [*normalized_paragraphs[:3], normalized_paragraphs[-1]]
            else:
                normalized_paragraphs = normalized_paragraphs[:4]
        compacted = "\n\n".join(normalized_paragraphs).strip()
        if len(compacted) > 900:
            compacted = self._trim_text_by_sentences(compacted, 900)
        return compacted

    def _normalize_closing(self, text: str, *, has_followup: bool) -> str:
        profile = self._current_strategy_composition_profile
        language_profile = self._current_strategy_language_profile
        case_progress = self._current_case_progress
        closing_style = str(profile.get("closing_style") or "").strip().lower() if profile else ""
        compacted = self._sanitize_text(text)

        # Contrato composition → postprocessor:
        # Si composition ya decidió el cierre (closing_applied) o no autorizó al postprocessor
        # a agregar uno (allow_postprocessor_closing=False), respetamos esa decisión.
        composition_metadata = self._current_composition_metadata
        if composition_metadata and not composition_metadata.get("allow_postprocessor_closing", True):
            return compacted

        if has_followup or closing_style == "question_only":
            sentences = self._split_sentences(compacted)
            question_sentences = [sentence for sentence in sentences if "?" in sentence]
            if not question_sentences:
                return compacted
            final_question = question_sentences[-1]
            body = " ".join(sentence for sentence in sentences if "?" not in sentence).strip()
            return f"{body}\n\n{final_question}".strip() if body else final_question

        actionable_closures = (
            "para avanzar de forma concreta",
            "si quisieras mover esto ya",
        )
        if any(marker in compacted.casefold() for marker in actionable_closures):
            return compacted

        closing = str(language_profile.get("selected_closing") or "").strip()
        progress_status = str(case_progress.get("progress_status") or "").strip().lower()
        next_step_type = str(case_progress.get("next_step_type") or "").strip().lower()
        if not closing:
            closing = "Con esto ya podés avanzar con bastante claridad."
            if closing_style == "action_close":
                closing = "Con esto ya tenes un siguiente paso concreto para mover el caso."
            elif closing_style == "analysis_close":
                closing = "Con esta base, ya se puede sostener una orientacion mas firme del caso."
        if progress_status == "stalled":
            closing = "Con esto ya se puede seguir ordenando el caso, pero todavia conviene cerrar el dato que falta."
        elif next_step_type == "resolve_contradiction":
            closing = "Antes de avanzar mas, conviene aclarar ese punto inconsistente."
        elif progress_status == "ready" or next_step_type == "execute":
            if closing_style == "action_close":
                closing = "Con esto ya tenes un siguiente paso concreto y bastante definido para mover el caso."
            elif closing_style != "analysis_close":
                closing = "Con esta base, ya podes avanzar con un grado de claridad bastante firme."
        lowered = compacted.casefold()
        if closing.casefold() in lowered:
            return compacted
        if compacted.endswith("?"):
            return compacted
        return f"{compacted}\n\n{closing}".strip() if compacted else closing

    def _apply_length_limits(self, text: str, *, output_mode: str) -> str:
        # Si composition produjo una clarificación (una sola pregunta precisa),
        # no aplicamos límites — el texto ya es inherentemente corto.
        composition_metadata = self._current_composition_metadata
        render_family = str(composition_metadata.get("render_family") or "").strip()
        if render_family == "clarification":
            return text

        profile = self._current_strategy_composition_profile
        if profile and profile.get("max_chars"):
            limit = self._safe_int(profile.get("max_chars"))
            if limit > 0:
                if output_mode == "orientacion_inicial":
                    return self._trim_orientacion_text(text, limit)
                if output_mode == "estrategia":
                    return self._trim_strategy_text(text, limit)
                return self._trim_text_by_sentences(text, limit)
        limits = {
            "orientacion_inicial": 900,
            "estructuracion": 700,
            "estrategia": 700,
            "ejecucion": 600,
        }
        limit = limits.get(output_mode, 900)
        if output_mode == "orientacion_inicial":
            return self._trim_orientacion_text(text, limit)
        if output_mode == "estrategia":
            return self._trim_strategy_text(text, limit)
        return self._trim_text_by_sentences(text, limit)

    def _trim_text_by_sentences(self, text: str, max_chars: int) -> str:
        compacted = self._sanitize_text(text)
        if len(compacted) <= max_chars:
            return compacted

        question = ""
        sentences = self._split_sentences(compacted)
        if sentences and "?" in sentences[-1]:
            question = sentences[-1]
            compacted = " ".join(sentences[:-1]).strip()

        paragraphs = self._split_paragraphs(compacted)
        selected_paragraphs: list[str] = []
        current_length = len(question) + (2 if question else 0)
        for paragraph in paragraphs:
            projected = current_length + len(paragraph) + (2 if selected_paragraphs else 0)
            if projected <= max_chars:
                selected_paragraphs.append(paragraph)
                current_length = projected
                continue
            if not selected_paragraphs:
                selected_paragraphs.append(self._truncate_text(paragraph, max_chars=max_chars - current_length))
            break

        result = "\n\n".join(part for part in selected_paragraphs if part).strip()
        if question:
            return f"{result}\n\n{question}".strip() if result else question

        if result:
            return result

        sentences = self._split_sentences(compacted)
        selected: list[str] = []
        current_length = 0
        for sentence in sentences:
            projected = current_length + len(sentence) + (1 if selected else 0)
            if projected > max_chars:
                break
            selected.append(sentence)
            current_length = projected

        if selected:
            return " ".join(selected).strip()
        return self._truncate_text(compacted, max_chars=max_chars)

    def _trim_orientacion_text(self, text: str, max_chars: int) -> str:
        compacted = self._sanitize_text(text)
        if len(compacted) <= max_chars:
            return compacted

        paragraphs = self._split_paragraphs(compacted)
        if not paragraphs:
            return self._truncate_text(compacted, max_chars=max_chars)

        kept: list[str] = [paragraphs[0]]
        remaining = paragraphs[1:]
        tail: list[str] = []
        for paragraph in reversed(remaining):
            candidate = kept + list(reversed(tail + [paragraph]))
            joined = "\n\n".join(candidate).strip()
            if len(joined) <= max_chars:
                tail.append(paragraph)
            else:
                break
        result = "\n\n".join([kept[0], *reversed(tail)]).strip()
        if len(result) <= max_chars:
            return result
        return self._trim_text_by_sentences(result, max_chars)

    def _trim_strategy_text(self, text: str, max_chars: int) -> str:
        compacted = self._sanitize_text(text)
        if len(compacted) <= max_chars:
            return compacted

        paragraphs = self._split_paragraphs(compacted)
        if not paragraphs:
            return self._truncate_text(compacted, max_chars=max_chars)

        selected: list[str] = []

        def _add_matching(patterns: tuple[str, ...]) -> None:
            for paragraph in paragraphs:
                lowered = paragraph.casefold()
                if any(pattern in lowered for pattern in patterns) and paragraph not in selected:
                    selected.append(paragraph)
                    return

        selected.append(paragraphs[0])
        _add_matching(("el paso que priorizaria ahora es:", "si tuviera que ordenar el siguiente movimiento"))
        _add_matching(("la otra via existe, pero hoy queda mas atras:", "como alternativa se puede pensar esta via, pero hoy queda en segundo plano:"))

        if paragraphs and "?" in paragraphs[-1] and paragraphs[-1] not in selected:
            selected.append(paragraphs[-1])

        candidate = "\n\n".join(selected).strip()
        if candidate and len(candidate) <= max_chars:
            return candidate
        if candidate:
            return self._trim_text_by_sentences(candidate, max_chars)
        return self._trim_text_by_sentences(compacted, max_chars)

    def _split_paragraphs(self, text: str) -> list[str]:
        return [
            self._normalize_whitespace(part)
            for part in re.split(r"\n{2,}", str(text or ""))
            if str(part).strip()
        ]

    def _split_sentences(self, text: str) -> list[str]:
        compacted = self._normalize_whitespace(text)
        if not compacted:
            return []
        return [part.strip() for part in re.split(r"(?<=[.!?])\s+", compacted) if part.strip()]

    def _paragraph_similarity(self, left: str, right: str) -> float:
        return SequenceMatcher(
            a=self._normalize_similarity_text(left),
            b=self._normalize_similarity_text(right),
        ).ratio()

    def _response_contains_similar_block(self, response_text: str, candidate: str) -> bool:
        candidate_normalized = self._normalize_similarity_text(candidate)
        if not candidate_normalized:
            return True
        for paragraph in self._split_paragraphs(response_text):
            if self._normalize_similarity_text(paragraph) == candidate_normalized:
                return True
            if self._paragraph_similarity(paragraph, candidate) > 0.75:
                return True
        return False

    def _normalize_similarity_text(self, text: str) -> str:
        normalized = re.sub(r"[^\w\s]", "", self._normalize_whitespace(text)).casefold()
        return re.sub(r"\s+", " ", normalized).strip()

    def _paragraph_is_actionable(self, paragraph: str) -> bool:
        lowered = self._normalize_whitespace(paragraph).casefold()
        return (
            lowered.startswith("para avanzar de forma concreta")
            or lowered.startswith("si quisieras mover esto ya")
            or bool(re.match(r"^\d+\.", lowered))
        )

    def _has_clear_execution_steps(self, execution_output: dict[str, Any]) -> bool:
        execution_data = dict(execution_output.get("execution_output") or {})
        actions = [item for item in list(execution_data.get("what_to_do_now") or []) if str(item or "").strip()]
        where_to_go = [item for item in list(execution_data.get("where_to_go") or []) if str(item or "").strip()]
        requests = [item for item in list(execution_data.get("what_to_request") or []) if str(item or "").strip()]
        documents = [item for item in list(execution_data.get("documents_needed") or []) if str(item or "").strip()]
        return bool(actions) and (len(actions) >= 2 or bool(where_to_go or requests or documents or execution_output.get("applies")))

    # 8.3 — Conversation Memory

    def _persist_conversation_memory(
        self,
        *,
        db: Any | None,
        api_payload: dict[str, Any],
    ) -> None:
        """
        Actualiza conversation_memory en el snapshot con los resultados del turno.
        Requiere que dialogue_policy y composer_output ya estén en api_payload.
        Fallback seguro: si falla, no afecta la respuesta.
        """
        if db is None:
            return
        conversation_state = api_payload.get("conversation_state")
        if not isinstance(conversation_state, dict) or not conversation_state:
            return
        dialogue_policy = api_payload.get("dialogue_policy") or {}
        if not dialogue_policy:
            return

        conversation_id = str(conversation_state.get("conversation_id") or "").strip()
        if not conversation_id:
            return

        try:
            from app.services.conversation_memory_service import build_memory_update

            current_memory = dict(conversation_state.get("conversation_memory") or {})
            composer_output = dict(api_payload.get("composer_output") or {})
            # Derive last_user_message: prefer the clarification answer over the raw query
            _meta = dict(api_payload.get("metadata") or {})
            _cc = dict(_meta.get("clarification_context") or {})
            last_user_message = str(
                _cc.get("submitted_text")
                or _cc.get("last_user_answer")
                or api_payload.get("query")
                or ""
            ).strip()
            updated_memory = build_memory_update(
                current_memory=current_memory,
                dialogue_policy=dialogue_policy,
                composer_output=composer_output,
                conversation_state=conversation_state,
                last_user_message=last_user_message,
            )
            api_payload["conversation_state"]["conversation_memory"] = updated_memory
            conversation_state_service.update_conversation_memory(
                db,
                conversation_id=conversation_id,
                conversation_memory=updated_memory,
            )
        except Exception:
            logger.exception("No se pudo persistir conversation_memory (8.3).")

    def _persist_case_memory(
        self,
        *,
        db: Any | None,
        api_payload: dict[str, Any],
    ) -> None:
        """
        Persiste case_memory en el snapshot del estado de conversación (FASE 13A).
        También actualiza api_payload["conversation_state"]["case_memory"] para
        que el próximo turno pueda leerlo como previous_memory.
        Fallback seguro: si falla, no afecta la respuesta.
        """
        if db is None:
            return
        case_memory = api_payload.get("case_memory")
        if not case_memory or not isinstance(case_memory, dict):
            return
        conversation_state = api_payload.get("conversation_state")
        if not isinstance(conversation_state, dict) or not conversation_state:
            return
        conversation_id = str(conversation_state.get("conversation_id") or "").strip()
        if not conversation_id:
            return
        try:
            api_payload["conversation_state"]["case_memory"] = case_memory
            conversation_state_service.update_case_memory(
                db,
                conversation_id=conversation_id,
                case_memory=case_memory,
            )
        except Exception:
            logger.exception("No se pudo persistir case_memory (13A).")

    def _persist_case_progress(
        self,
        *,
        db: Any | None,
        api_payload: dict[str, Any],
    ) -> None:
        if db is None:
            return
        case_progress = api_payload.get("case_progress")
        if not case_progress or not isinstance(case_progress, dict):
            return
        conversation_state = api_payload.get("conversation_state")
        if not isinstance(conversation_state, dict) or not conversation_state:
            return
        conversation_id = str(conversation_state.get("conversation_id") or "").strip()
        if not conversation_id:
            return
        try:
            progress_snapshot = dict(api_payload.get("case_progress_snapshot") or {})
            api_payload["conversation_state"]["case_progress"] = case_progress
            api_payload["conversation_state"]["case_progress_snapshot"] = progress_snapshot
            conversation_state_service.update_case_progress(
                db,
                conversation_id=conversation_id,
                case_progress=case_progress,
                case_progress_snapshot=progress_snapshot,
            )
        except Exception:
            logger.exception("No se pudo persistir case_progress (13B).")

    # Conversación y policy

    def _attach_conversation_state(
        self,
        *,
        db: Any | None,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> None:
        conversation_id = self._extract_conversation_id(normalized_input, pipeline_payload, api_payload)
        if not conversation_id or db is None:
            return
        try:
            snapshot = conversation_state_service.update_conversation_state(
                db,
                conversation_id=conversation_id,
                turn_input=normalized_input,
                pipeline_payload=pipeline_payload,
                response_payload=api_payload,
            )
        except Exception:
            logger.exception(
                "No se pudo actualizar el estado conversacional.",
                extra={"conversation_id": conversation_id},
            )
            return
        if snapshot:
            api_payload["conversation_state"] = snapshot

    def _attach_case_state(
        self,
        *,
        db: Any | None,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> None:
        conversation_id = self._extract_conversation_id(normalized_input, pipeline_payload, api_payload)
        if not conversation_id or db is None:
            return
        try:
            enriched_payload = dict(pipeline_payload)
            enriched_payload["conversation_id"] = conversation_id
            enriched_payload.setdefault("user_message", normalized_input.get("query"))
            if api_payload.get("output_mode"):
                enriched_payload["output_mode"] = api_payload.get("output_mode")
            if isinstance(api_payload.get("legal_reasoning"), dict):
                enriched_payload["legal_reasoning"] = api_payload["legal_reasoning"]
            if api_payload.get("confidence_score") is not None:
                enriched_payload["confidence_score"] = api_payload.get("confidence_score")

            extracted = case_state_extractor_service.extract_from_pipeline_payload(enriched_payload)
            case_state_service.get_or_create_case_state(db, conversation_id)
            turn_index = self._resolve_case_turn_index(api_payload)

            for fact in list(extracted.get("facts") or []):
                persisted_fact = case_state_service.upsert_case_fact(
                    db,
                    conversation_id=conversation_id,
                    fact_key=str(fact.get("fact_key") or ""),
                    fact_value=fact.get("fact_value"),
                    value_type=str(fact.get("value_type") or ""),
                    domain=str(fact.get("domain") or ""),
                    source_type=str(fact.get("source_type") or "pipeline_inferred"),
                    confidence=fact.get("confidence"),
                    status=str(fact.get("status") or ""),
                    turn_index=turn_index,
                    evidence_excerpt=str(fact.get("evidence_excerpt") or ""),
                )
                for need in case_state_service.get_case_needs(db, conversation_id):
                    if (
                        need.status != "resolved"
                        and self._need_matches_fact(need_key=need.need_key, resolved_by_fact_key=need.resolved_by_fact_key, fact_key=persisted_fact.fact_key)
                    ):
                        case_state_service.resolve_need(
                            db,
                            conversation_id=conversation_id,
                            need_key=need.need_key,
                            fact_key=persisted_fact.fact_key,
                        )

            for need in list(extracted.get("needs") or []):
                persisted_need = case_state_service.upsert_case_need(
                    db,
                    conversation_id=conversation_id,
                    need_key=str(need.get("need_key") or ""),
                    category=str(need.get("category") or ""),
                    priority=str(need.get("priority") or ""),
                    status=str(need.get("status") or "open"),
                    reason=str(need.get("reason") or ""),
                    suggested_question=str(need.get("suggested_question") or ""),
                    resolved_by_fact_key=str(need.get("resolved_by_fact_key") or ""),
                )
                matching_fact_key = self._resolve_matching_fact_key(
                    need_key=str(need.get("need_key") or ""),
                    resolved_by_fact_key=str(need.get("resolved_by_fact_key") or ""),
                )
                if matching_fact_key and case_state_service.fact_is_active(
                    db,
                    conversation_id=conversation_id,
                    fact_key=matching_fact_key,
                ):
                    case_state_service.resolve_need(
                        db,
                        conversation_id=conversation_id,
                        need_key=persisted_need.need_key,
                        fact_key=matching_fact_key,
                    )

            for event in list(extracted.get("events") or []):
                case_state_service.append_case_event(
                    db,
                    conversation_id=conversation_id,
                    event_type=str(event.get("event_type") or "case_state_update"),
                    payload=event.get("payload") if isinstance(event.get("payload"), dict) else {},
                )

            now_iso = utc_now().isoformat()
            progression_policy = dict(api_payload.get("progression_policy") or {})
            progression_stage = str(progression_policy.get("progression_stage") or "").strip()
            case_stage = str(extracted.get("case_stage") or "")
            if progression_stage:
                case_stage = PROGRESSION_TO_CASE_STAGE.get(progression_stage, case_stage)
            case_state_service.update_case_state(
                db,
                conversation_id=conversation_id,
                case_type=str(extracted.get("case_type") or ""),
                case_stage=case_stage,
                primary_goal=str(extracted.get("primary_goal") or ""),
                secondary_goals_json=list(extracted.get("secondary_goals_json") or []),
                jurisdiction=str(extracted.get("jurisdiction") or ""),
                status=str(extracted.get("status") or "active"),
                confidence_score=extracted.get("confidence_score"),
                summary_text=str(extracted.get("summary_text") or ""),
                last_user_turn_at=now_iso,
                last_system_turn_at=now_iso,
            )
            snapshot = case_state_service.build_case_snapshot(db, conversation_id)
            api_payload["case_state_snapshot"] = snapshot
            pipeline_payload["case_state_snapshot"] = snapshot
        except Exception:
            logger.exception(
                "No se pudo actualizar el case state persistente.",
                extra={"conversation_id": conversation_id},
            )

    def _attach_case_followup(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        snapshot = api_payload.get("case_state_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return
        try:
            followup = case_followup_service.build_case_followup(
                case_state_snapshot=snapshot,
                api_payload=api_payload,
                output_mode=self._get_output_mode(api_payload),
            )
            api_payload["case_followup"] = followup

            # FASE 11A — Adaptive follow-up intelligence
            # Veta o confirma la decision del servicio existente usando la capa adaptativa.
            # Si falla, la decision original de case_followup_service queda intacta.
            if followup.get("should_ask"):
                self._apply_adaptive_followup_veto(
                    followup=followup,
                    snapshot=snapshot,
                    api_payload=api_payload,
                )
        except Exception:
            logger.exception("No se pudo construir case_followup.")

    def _apply_adaptive_followup_veto(
        self,
        *,
        followup: dict[str, Any],
        snapshot: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> None:
        """
        Aplica la capa adaptativa (Fase 11A) como veto sobre la decision de case_followup_service.

        Lee del estado conversacional:
          - known_facts     → hechos ya confirmados
          - missing_facts   → necesidades pendientes con metadatos de importancia
          - previous_questions → preguntas ya formuladas en turnos anteriores
          - last_user_messages → para detectar si el usuario sigue aportando info

        Si la capa adaptativa decide no preguntar (loop, completo, baja prioridad),
        desactiva should_ask en el followup sin eliminar los metadatos internos.
        """
        try:
            conversation_state = dict(api_payload.get("conversation_state") or {})
            conversation_memory = dict(conversation_state.get("conversation_memory") or {})

            known_facts = self._extract_known_facts_dict(conversation_state)
            missing_facts = self._extract_missing_facts_list(snapshot)
            previous_questions = self._extract_previous_questions(
                conversation_memory=conversation_memory,
                conversation_state=conversation_state,
                api_payload=api_payload,
            )
            last_user_messages = self._extract_last_user_messages(
                conversation_memory=conversation_memory,
                conversation_state=conversation_state,
                api_payload=api_payload,
            )

            decision = resolve_followup_decision(
                known_facts=known_facts,
                missing_facts=missing_facts,
                conversation_state=conversation_state,
                previous_questions=previous_questions,
                last_user_messages=last_user_messages,
            )
            api_payload["adaptive_followup"] = decision
            followup["adaptive_progress_state"] = str(decision.get("progress_state") or "")
            followup["adaptive_reason"] = str(decision.get("reason") or "")
            followup["adaptive_question_type"] = str(decision.get("question_type") or "")
            followup["detected_loop"] = bool(decision.get("detected_loop"))
            followup["user_cannot_answer"] = bool(decision.get("user_cannot_answer"))
            followup["recent_progress"] = bool(decision.get("recent_progress"))
            followup["stagnation_reason"] = decision.get("stagnation_reason")
            followup.setdefault("adaptive_override", False)
            followup.setdefault("adaptive_suppressed", False)
            case_progress = dict(api_payload.get("case_progress") or {})
            next_step_type = str(case_progress.get("next_step_type") or "").strip().lower()
            contradiction_driven = (
                next_step_type == "resolve_contradiction"
                or str(followup.get("source") or "").strip().lower() == "case_progress"
                or str(followup.get("need_key") or "").strip().lower().startswith("contradiction::")
            )

            if not decision.get("should_ask") and not contradiction_driven:
                followup["should_ask"] = False
                followup["question"] = ""
                followup["adaptive_suppressed"] = True
            else:
                priority_question = str(decision.get("priority_question") or "").strip()
                if priority_question:
                    followup["should_ask"] = True
                    followup["question"] = priority_question
            followup["adaptive_override"] = True

        except Exception:
            logger.exception("No se pudo aplicar adaptive followup veto (Fase 11A).")

    @staticmethod
    def _extract_known_facts_dict(conversation_state: dict[str, Any]) -> dict[str, Any]:
        """Construye un dict {key: value} de hechos conocidos desde conversation_state."""
        result: dict[str, Any] = {}
        for item in list(conversation_state.get("known_facts") or []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if key:
                result[key] = item.get("value")
        return result

    @staticmethod
    def _extract_missing_facts_list(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extrae missing_facts desde el snapshot de case_state.
        Cada elemento del snapshot tiene al menos: need_key, category, priority.
        Los mapea al formato que espera adaptive_followup_service:
          key, label, importance, impact_on_strategy, suggested_question.
        """
        result: list[dict[str, Any]] = []
        for need in list(snapshot.get("open_needs") or []):
            if not isinstance(need, dict):
                continue
            priority = str(need.get("priority") or "").strip().lower()
            category = str(need.get("category") or "").strip().lower()
            need_key = str(need.get("need_key") or "").strip()
            if not need_key:
                continue
            # Map priority/category to importance
            if priority == "critical":
                importance = "critical"
            elif priority == "high":
                importance = "high"
            elif priority in {"normal", "medium"}:
                importance = "medium"
            else:
                importance = "low"
            result.append({
                "key": need_key,
                "label": str(need.get("label") or need_key).strip(),
                "importance": importance,
                "impact_on_strategy": category in {"procesal", "estrategia"},
                "suggested_question": str(need.get("suggested_question") or "").strip(),
            })
        return result

    @staticmethod
    def _extract_previous_questions(
        conversation_memory: dict[str, Any],
        conversation_state: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> list[str]:
        """Extrae preguntas previas desde memory y, si falta, desde recent_turns u otras huellas conversacionales."""
        result: list[str] = []
        raw = list(conversation_memory.get("asked_questions") or [])
        result.extend(str(q) for q in raw if str(q).strip())

        for turn in list(conversation_state.get("recent_turns") or []):
            if not isinstance(turn, dict):
                continue
            question = str(
                turn.get("assistant_question")
                or turn.get("followup_question")
                or turn.get("question")
                or ""
            ).strip()
            if question:
                result.append(question)

        conversational = dict(api_payload.get("conversational") or {})
        current_question = str(conversational.get("question") or "").strip()
        if current_question:
            result.append(current_question)

        return ResponsePostprocessor._dedupe_followup_context_texts(result)

    @staticmethod
    def _extract_last_user_messages(
        conversation_memory: dict[str, Any],
        conversation_state: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> list[str]:
        """Extrae los últimos mensajes del usuario desde memory y, como fallback, desde recent_turns/query."""
        result: list[str] = []
        raw = list(conversation_memory.get("last_user_messages") or [])
        result.extend(str(m) for m in raw if str(m).strip())

        last_user_message = str(conversation_memory.get("last_user_message") or "").strip()
        if last_user_message:
            result.append(last_user_message)

        for turn in list(conversation_state.get("recent_turns") or []):
            if not isinstance(turn, dict):
                continue
            message = str(
                turn.get("user_message")
                or turn.get("submitted_text")
                or turn.get("last_user_answer")
                or ""
            ).strip()
            if message:
                result.append(message)

        query = str(api_payload.get("query") or "").strip()
        if query:
            result.append(query)

        return ResponsePostprocessor._dedupe_followup_context_texts(result)

    @staticmethod
    def _dedupe_followup_context_texts(items: list[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            value = str(item or "").strip()
            normalized = re.sub(r"[^\w\s]", "", value).casefold()
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(value)
        return result

    def _attach_case_progress_narrative(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        snapshot = api_payload.get("case_state_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return
        try:
            api_payload["case_progress_narrative"] = case_progress_narrative_service.build_case_progress_narrative(
                case_state_snapshot=snapshot,
                api_payload=api_payload,
                output_mode=self._get_output_mode(api_payload),
            )
        except Exception:
            logger.exception("No se pudo construir case_progress_narrative.")

    def _attach_professional_judgment(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        try:
            api_payload["professional_judgment"] = build_professional_judgment(
                api_payload=api_payload,
            )
        except Exception:
            logger.exception("No se pudo construir professional_judgment.")

    def _attach_case_confidence(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        snapshot = api_payload.get("case_state_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return

        try:
            conversation_state = dict(api_payload.get("conversation_state") or {})
            known_facts = self._extract_known_facts_dict(conversation_state)
            confirmed_facts = dict(snapshot.get("confirmed_facts") or {})
            probable_facts = dict(snapshot.get("probable_facts") or {})
            if confirmed_facts:
                known_facts.update(confirmed_facts)
            elif probable_facts:
                known_facts.update(probable_facts)

            api_payload["case_confidence"] = resolve_case_confidence(
                known_facts=known_facts,
                missing_facts=self._extract_missing_facts_list(snapshot),
                conversation_state=conversation_state,
                case_followup=dict(api_payload.get("case_followup") or {}),
            )
        except Exception:
            logger.exception("No se pudo construir case_confidence.")

    # FASE 13A — Case Memory

    def _attach_case_memory(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        """
        Construye el case_memory del turno y lo almacena en api_payload["case_memory"].

        Lee case_state_snapshot y conversation_state que ya están en api_payload.
        Fallback seguro: si falla, api_payload no se modifica.
        """
        try:
            from app.services.case_memory_service import build_case_memory, merge_case_memory

            snapshot = api_payload.get("case_state_snapshot")
            conversation_state = dict(api_payload.get("conversation_state") or {})
            previous_memory = conversation_state.get("case_memory")
            safe_snapshot = snapshot if isinstance(snapshot, dict) else None

            if previous_memory and isinstance(previous_memory, dict):
                api_payload["case_memory"] = merge_case_memory(
                    previous_memory=previous_memory,
                    case_state_snapshot=safe_snapshot,
                    conversation_state=conversation_state,
                    api_payload=api_payload,
                )
            else:
                api_payload["case_memory"] = build_case_memory(
                    case_state_snapshot=safe_snapshot,
                    conversation_state=conversation_state,
                    api_payload=api_payload,
                )
        except Exception:
            logger.exception("No se pudo construir case_memory (13A).")

    def _attach_case_progress(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        """
        Traduce case_memory y señales del pipeline a un estado operativo del caso.
        Se ubica antes de smart_strategy para dejar una lectura serializable y estable
        disponible para las capas que siguen, sin acoplarlas al detalle de la memoria.
        """
        try:
            progress = build_case_progress(
                case_memory=api_payload.get("case_memory"),
                conversation_state=api_payload.get("conversation_state"),
                case_state_snapshot=api_payload.get("case_state_snapshot"),
                api_payload=api_payload,
            )
            api_payload["case_progress"] = progress
            api_payload["case_progress_snapshot"] = extract_case_progress_snapshot(progress)
            self._case_progress = dict(progress)
        except Exception:
            logger.exception("No se pudo construir case_progress (13B).")

    def _attach_smart_strategy(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        snapshot = api_payload.get("case_state_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return

        try:
            conversation_state = dict(api_payload.get("conversation_state") or {})
            known_facts = self._extract_known_facts_dict(conversation_state)
            confirmed_facts = dict(snapshot.get("confirmed_facts") or {})
            probable_facts = dict(snapshot.get("probable_facts") or {})
            if confirmed_facts:
                known_facts.update(confirmed_facts)
            elif probable_facts:
                known_facts.update(probable_facts)

            api_payload["smart_strategy"] = resolve_smart_strategy(
                known_facts=known_facts,
                missing_facts=self._extract_missing_facts_list(snapshot),
                conversation_state=conversation_state,
                case_followup=dict(api_payload.get("case_followup") or {}),
                case_confidence=dict(api_payload.get("case_confidence") or {}),
                output_mode=self._get_output_mode(api_payload),
                case_progress=dict(api_payload.get("case_progress") or {}),
            )
        except Exception:
            logger.exception("No se pudo construir smart_strategy.")

    def _attach_strategy_composition_profile(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        try:
            smart_strategy = dict(api_payload.get("smart_strategy") or {})
            if not smart_strategy:
                return
            api_payload["strategy_composition_profile"] = resolve_strategy_composition_profile(
                smart_strategy,
                output_mode=self._get_output_mode(api_payload),
                case_followup=dict(api_payload.get("case_followup") or {}),
                case_confidence=dict(api_payload.get("case_confidence") or {}),
            )
        except Exception:
            logger.exception("No se pudo construir strategy_composition_profile.")

    def _apply_followup_integrity_arbitration(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        followup = dict(api_payload.get("case_followup") or {})
        if not followup:
            api_payload["conversation_integrity"] = build_integrity_state(
                conversation_state=dict(api_payload.get("conversation_state") or {}),
                case_memory=dict(api_payload.get("case_memory") or {}),
            )
            return

        try:
            decision = should_allow_followup(
                api_payload=api_payload,
                question=str(followup.get("question") or "").strip(),
                need_key=str(followup.get("need_key") or "").strip(),
            )
            api_payload["conversation_integrity"] = dict(decision.get("integrity_state") or {})
            followup["canonical_slot"] = str(decision.get("canonical_slot") or "")
            followup["integrity_reason"] = str(decision.get("reason") or "")
            followup["integrity_suppressed"] = False

            if not decision.get("should_allow_followup"):
                followup["should_ask"] = False
                followup["question"] = ""
                followup["reason"] = self._integrity_reason_message(str(decision.get("reason") or ""))
                followup["integrity_suppressed"] = True

            api_payload["case_followup"] = followup
        except Exception:
            logger.exception("No se pudo aplicar la capa de integridad conversacional.")

    @staticmethod
    def _integrity_reason_message(reason: str) -> str:
        messages = {
            "strategy_profile_disallows_followup": "La estrategia final indica cerrar este turno sin mÃ¡s preguntas.",
            "strategy_mode_closes_without_questions": "La estrategia dominante permite avanzar sin un follow-up final.",
            "case_followup_already_closed": "Hay suficiente informaciÃ³n para avanzar sin follow-up.",
            "readiness_allows_advancing_without_followup": "Hay suficiente informaciÃ³n para avanzar sin follow-up.",
            "slot_already_resolved": "Ese punto ya quedÃ³ resuelto en esta conversaciÃ³n.",
            "slot_already_answered_partially": "Ese punto ya fue respondido en esta conversaciÃ³n y no conviene repetir la misma pregunta.",
        }
        return messages.get(reason, "Hay suficiente informaciÃ³n para avanzar sin follow-up.")

    def _attach_strategy_language_profile(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        try:
            smart_strategy = dict(api_payload.get("smart_strategy") or {})
            if not smart_strategy:
                return
            consistency = dict(api_payload.get("consistency_policy") or {})
            stable_bucket: int | None = consistency.get("stable_variation_bucket")
            api_payload["strategy_language_profile"] = resolve_strategy_language_profile(
                smart_strategy,
                composition_profile=dict(api_payload.get("strategy_composition_profile") or {}),
                conversation_state=dict(api_payload.get("conversation_state") or {}),
                output_mode=self._get_output_mode(api_payload),
                stable_bucket=stable_bucket,
            )
        except Exception:
            logger.exception("No se pudo construir strategy_language_profile.")

    def _attach_consistency_policy(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        try:
            smart_strategy = dict(api_payload.get("smart_strategy") or {})
            if not smart_strategy:
                return
            api_payload["consistency_policy"] = resolve_consistency_policy(
                strategy_mode=str(smart_strategy.get("strategy_mode") or ""),
                output_mode=self._get_output_mode(api_payload),
                composition_profile=dict(api_payload.get("strategy_composition_profile") or {}),
                conversation_state=dict(api_payload.get("conversation_state") or {}),
            )
        except Exception:
            logger.exception("No se pudo construir consistency_policy (Fase 12.7).")

    def _get_strategy_composition_profile(self, api_payload: dict[str, Any]) -> dict[str, Any]:
        profile = dict(api_payload.get("strategy_composition_profile") or {})
        self._strategy_composition_profile = profile
        return profile

    @property
    def _current_strategy_composition_profile(self) -> dict[str, Any]:
        return dict(getattr(self, "_strategy_composition_profile", {}) or {})

    def _get_strategy_language_profile(self, api_payload: dict[str, Any]) -> dict[str, Any]:
        profile = dict(api_payload.get("strategy_language_profile") or {})
        self._strategy_language_profile = profile
        return profile

    @property
    def _current_strategy_language_profile(self) -> dict[str, Any]:
        return dict(getattr(self, "_strategy_language_profile", {}) or {})

    @property
    def _current_case_progress(self) -> dict[str, Any]:
        return dict(getattr(self, "_case_progress", {}) or {})

    @property
    def _current_composition_metadata(self) -> dict[str, Any]:
        """Metadata producida por resolve_response_composition en este turno."""
        return dict(getattr(self, "_composition_metadata", {}) or {})

    @staticmethod
    def _get_smart_strategy_mode(api_payload: dict[str, Any]) -> str:
        smart_strategy = dict(api_payload.get("smart_strategy") or {})
        return str(smart_strategy.get("strategy_mode") or "").strip().lower()

    def _attach_case_summary(
        self,
        *,
        db: Any | None,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> None:
        snapshot = api_payload.get("case_state_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return

        try:
            summary = case_summary_service.build_case_summary(
                case_state_snapshot=snapshot,
                api_payload=api_payload,
                output_mode=self._get_output_mode(api_payload),
            )
            api_payload["case_summary"] = summary
        except Exception:
            logger.exception("No se pudo construir case_summary.")
            return

        if not summary.get("applies"):
            return

        summary_text = str(summary.get("summary_text") or "").strip()
        if not summary_text:
            return

        try:
            snapshot_case_state = dict(snapshot.get("case_state") or {})
            snapshot_case_state["summary_text"] = summary_text
            snapshot["case_state"] = snapshot_case_state
            api_payload["case_state_snapshot"] = snapshot
            pipeline_payload["case_state_snapshot"] = snapshot

            conversation_id = self._extract_conversation_id(normalized_input, pipeline_payload, api_payload)
            if db is not None and conversation_id:
                case_state_service.update_case_summary_text(
                    db,
                    conversation_id=conversation_id,
                    summary_text=summary_text,
                )
        except Exception:
            logger.exception("No se pudo persistir case_summary en case_state.")

    def _attach_case_workspace(
        self,
        *,
        api_payload: dict[str, Any],
    ) -> None:
        try:
            api_payload["case_workspace"] = build_case_workspace(api_payload=api_payload)
        except Exception:
            logger.exception("No se pudo construir case_workspace (15A).")

    def _attach_dialogue_policy(
        self,
        *,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> None:
        conversation_state = api_payload.get("conversation_state")
        if not isinstance(conversation_state, dict) or not conversation_state:
            return
        try:
            api_payload["dialogue_policy"] = resolve_dialogue_policy(
                conversation_state=conversation_state,
                turn_signals={"normalized_input": normalized_input},
                pipeline_payload=pipeline_payload,
            )
        except Exception:
            logger.exception("No se pudo resolver dialogue policy.")

    def _attach_conversational_intelligence(
        self,
        *,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> None:
        conversation_state = api_payload.get("conversation_state")
        dialogue_policy = api_payload.get("dialogue_policy")
        if not isinstance(conversation_state, dict) or not conversation_state:
            return
        if not isinstance(dialogue_policy, dict) or not dialogue_policy:
            return
        try:
            intelligence = resolve_conversational_intelligence(
                conversation_state=conversation_state,
                dialogue_policy=dialogue_policy,
                conversation_memory=conversation_state.get("conversation_memory"),
                normalized_input=normalized_input,
                pipeline_payload=pipeline_payload,
            )
            api_payload["conversational_intelligence"] = intelligence
            api_payload["dialogue_policy"] = apply_conversational_intelligence_to_policy(
                dialogue_policy=dialogue_policy,
                conversational_intelligence=intelligence,
            )
        except Exception:
            logger.exception("No se pudo resolver conversational intelligence (8.4).")

    def _attach_intent_resolution_and_execution_output(
        self,
        *,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
        response_text: str,
    ) -> str:
        conversation_state = api_payload.get("conversation_state")
        dialogue_policy = api_payload.get("dialogue_policy")
        conversational_intelligence = api_payload.get("conversational_intelligence")
        if not isinstance(conversation_state, dict) or not conversation_state:
            return response_text
        if not isinstance(dialogue_policy, dict) or not dialogue_policy:
            return response_text
        if not isinstance(conversational_intelligence, dict) or not conversational_intelligence:
            return response_text

        try:
            intent_resolution = resolve_intent_resolution(
                normalized_input=normalized_input,
                conversation_state=conversation_state,
                dialogue_policy=dialogue_policy,
                conversational_intelligence=conversational_intelligence,
                pipeline_payload=pipeline_payload,
            )
            api_payload["intent_resolution"] = intent_resolution
        except Exception:
            logger.exception("No se pudo resolver intent resolution (8.5).")
            return response_text

        try:
            execution_output = build_execution_output(
                conversation_state=conversation_state,
                dialogue_policy=api_payload.get("dialogue_policy"),
                conversational_intelligence=conversational_intelligence,
                pipeline_payload=pipeline_payload,
                response_text=response_text,
                intent_resolution=intent_resolution,
            )
            api_payload["execution_output"] = execution_output
            policy_patch = execution_output.get("policy_patch") or {}
            if isinstance(policy_patch, dict) and policy_patch:
                api_payload["dialogue_policy"] = {
                    **dict(api_payload.get("dialogue_policy") or {}),
                    **policy_patch,
                }
            rendered = str(execution_output.get("rendered_response_text") or "").strip()
            if execution_output.get("applies") and rendered:
                return f"{response_text.strip()}\n\n{rendered}".strip()
        except Exception:
            logger.exception("No se pudo construir execution output (8.5).")

        return response_text

    def _attach_progression_policy(
        self,
        *,
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
        response_text: str,
    ) -> str:
        conversation_state = api_payload.get("conversation_state")
        dialogue_policy = api_payload.get("dialogue_policy")
        conversational_intelligence = api_payload.get("conversational_intelligence")
        if not isinstance(conversation_state, dict) or not conversation_state:
            return response_text
        if not isinstance(dialogue_policy, dict) or not dialogue_policy:
            return response_text
        if not isinstance(conversational_intelligence, dict) or not conversational_intelligence:
            return response_text

        try:
            progression_policy = resolve_progression_policy(
                conversation_state=conversation_state,
                dialogue_policy=dialogue_policy,
                conversational_intelligence=conversational_intelligence,
                intent_resolution=api_payload.get("intent_resolution"),
                execution_output=api_payload.get("execution_output"),
                pipeline_payload=pipeline_payload,
                response_text=response_text,
            )
            api_payload["progression_policy"] = progression_policy
            evolved_payload = apply_output_mode_progression(api_payload, progression_policy)
            if isinstance(evolved_payload.get("output_modes"), dict) and evolved_payload.get("output_modes"):
                api_payload["output_modes"] = evolved_payload["output_modes"]
            if str(evolved_payload.get("output_mode") or "").strip():
                api_payload["output_mode"] = evolved_payload["output_mode"]
            rendered = str(progression_policy.get("rendered_response_text") or "").strip()
            if rendered and self._get_output_mode(api_payload) != "orientacion_inicial":
                return rendered
        except Exception:
            logger.exception("No se pudo resolver progression policy.")

        return response_text

    def _persist_conversation_progression(
        self,
        *,
        db: Any | None,
        api_payload: dict[str, Any],
        response_text: str,
    ) -> None:
        if db is None:
            return
        conversation_state = api_payload.get("conversation_state")
        progression_policy = api_payload.get("progression_policy")
        if not isinstance(conversation_state, dict) or not conversation_state:
            return
        if not isinstance(progression_policy, dict) or not progression_policy:
            return

        conversation_id = str(conversation_state.get("conversation_id") or "").strip()
        if not conversation_id:
            return

        try:
            finalized_state = finalize_progression_state(
                progression_policy=progression_policy,
                response_text=response_text,
            )
            api_payload["conversation_state"]["progression_state"] = finalized_state
            api_payload["conversation_state"]["progression_stage"] = finalized_state.get("progression_stage") or "initial"
            conversation_state_service.update_progression_state(
                db,
                conversation_id=conversation_id,
                progression_state=finalized_state,
            )
        except Exception:
            logger.exception("No se pudo persistir progression_state.")

    def _extract_conversation_id(
        self,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> str:
        metadata = normalized_input.get("metadata") or {}
        for source in (
            metadata.get("conversation_id"),
            metadata.get("conversationId"),
            # session_id is stable across turns and sent by the frontend in every request
            metadata.get("session_id"),
            metadata.get("sessionId"),
            pipeline_payload.get("conversation_id"),
            api_payload.get("conversation_id"),
        ):
            normalized = str(source or "").strip()
            if normalized:
                return normalized
        return ""

    def _get_output_mode(self, api_payload: dict[str, Any]) -> str:
        return str(
            (api_payload.get("progression_policy") or {}).get("output_mode")
            or "orientacion_inicial"
        ).strip()

    def _resolve_case_turn_index(self, api_payload: dict[str, Any]) -> int | None:
        conversation_state = api_payload.get("conversation_state")
        if isinstance(conversation_state, dict):
            try:
                return int(conversation_state.get("turn_count"))
            except (TypeError, ValueError):
                return None
        return None

    def _need_matches_fact(
        self,
        *,
        need_key: Any,
        resolved_by_fact_key: Any,
        fact_key: Any,
    ) -> bool:
        normalized_fact_key = self._normalize_case_key(fact_key)
        if not normalized_fact_key:
            return False
        explicit_fact_key = self._normalize_case_key(resolved_by_fact_key)
        if explicit_fact_key and explicit_fact_key == normalized_fact_key:
            return True
        normalized_need_key = str(need_key or "").strip()
        if "::" in normalized_need_key:
            suffix = normalized_need_key.rsplit("::", 1)[-1]
            return self._normalize_case_key(suffix) == normalized_fact_key
        return self._normalize_case_key(normalized_need_key) == normalized_fact_key

    def _resolve_matching_fact_key(
        self,
        *,
        need_key: Any,
        resolved_by_fact_key: Any,
    ) -> str:
        explicit_fact_key = self._normalize_case_key(resolved_by_fact_key)
        if explicit_fact_key:
            return explicit_fact_key
        normalized_need_key = str(need_key or "").strip()
        if "::" in normalized_need_key:
            return self._normalize_case_key(normalized_need_key.rsplit("::", 1)[-1])
        return self._normalize_case_key(normalized_need_key)

    @staticmethod
    def _normalize_case_key(value: Any) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
        return normalized[:120]

    # Construcción de payload

    def _build_api_payload(
        self,
        *,
        request_id: str,
        response_text: str,
        pipeline_payload: dict[str, Any],
        retrieval: RetrievalBundle,
        strategy: StrategyBundle,
    ) -> dict[str, Any]:
        payload = dict(pipeline_payload)
        warnings = self._sanitize_warnings(
            [
                *list(payload.get("warnings") or []),
                *list(retrieval.warnings or []),
            ]
        )

        payload["request_id"] = request_id
        payload["response_text"] = response_text
        payload["pipeline_version"] = self._safe_pipeline_version(payload.get("pipeline_version"))
        payload["retrieval_bundle"] = retrieval.to_dict()
        payload["source_mode"] = retrieval.source_mode
        payload["documents_considered"] = retrieval.documents_considered
        payload["action_slug"] = self._canonical_action_slug(payload)
        payload["case_domain"] = self._canonical_case_domain(payload)
        payload["strategy_mode"] = self._canonical_strategy_mode(payload)
        payload["dominant_factor"] = self._canonical_dominant_factor(payload)
        payload["blocking_factor"] = self._canonical_blocking_factor(payload)
        payload["execution_readiness"] = self._canonical_execution_readiness(payload)
        payload["confidence_score"] = self._canonical_confidence_score(payload)
        payload["confidence_label"] = self._confidence_label(payload["confidence_score"])
        payload["confidence"] = payload["confidence_score"]
        payload["fallback_used"] = strategy.fallback_used
        payload["fallback_reason"] = strategy.fallback_reason
        payload["warnings"] = warnings
        return payload

    def _build_response_text(self, payload: dict[str, Any]) -> str:
        core_legal_response = dict(payload.get("core_legal_response") or {})
        core_response_text = self._render_core_legal_response(core_legal_response)
        if core_response_text:
            return core_response_text

        conversational = payload.get("conversational") or {}
        if conversational.get("should_ask_first"):
            guided_response = str(conversational.get("guided_response") or "").strip()
            if guided_response:
                return guided_response

        generated_document = str(payload.get("generated_document") or "").strip()
        if generated_document:
            return generated_document

        reasoning = payload.get("reasoning") or {}
        short_answer = str(reasoning.get("short_answer") or "").strip()
        applied_analysis = str(reasoning.get("applied_analysis") or "").strip()
        strategy = payload.get("case_strategy") or {}
        reactive_transition = str(strategy.get("reactive_transition") or "").strip()
        strategic_narrative = str(strategy.get("strategic_narrative") or "").strip()

        parts = [part for part in (reactive_transition, short_answer, applied_analysis, strategic_narrative) if part]
        return "\n\n".join(self._dedupe_lines(parts))

    def _render_core_legal_response(self, core: dict[str, Any]) -> str:
        if not core:
            return ""
        direct_answer = str(core.get("direct_answer") or "").strip()
        action_steps = [str(item).strip() for item in list(core.get("action_steps") or []) if str(item).strip()]
        required_documents = [str(item).strip() for item in list(core.get("required_documents") or []) if str(item).strip()]
        local_practice_notes = [str(item).strip() for item in list(core.get("local_practice_notes") or []) if str(item).strip()]
        optional_clarification = str(core.get("optional_clarification") or "").strip()

        sections: list[str] = []
        if direct_answer:
            sections.append(direct_answer)
        if action_steps:
            sections.append("Que podes hacer ahora:\n" + "\n".join(f"- {item}" for item in action_steps[:3]))
        if required_documents:
            sections.append("Que conviene reunir:\n" + "\n".join(f"- {item}" for item in required_documents[:4]))
        if local_practice_notes:
            sections.append("Practica local orientativa:\n" + "\n".join(f"- {item}" for item in local_practice_notes[:3]))
        if optional_clarification:
            sections.append(f"Si queres afinar mejor la orientacion: {optional_clarification}")
        return "\n\n".join(section for section in sections if section.strip()).strip()

    def _prepend_quick_start(
        self,
        response_text: str,
        quick_start: str | None,
        *,
        output_mode: Any = None,
    ) -> str:
        """Insert quick_start at the beginning of response_text if not already present."""
        qs = str(quick_start or "").strip()
        if not qs:
            return response_text
        normalized_mode = str(output_mode or "").strip().lower()
        if normalized_mode and normalized_mode != "orientacion_inicial":
            return response_text
        normalized_response = self._normalize_whitespace(response_text).casefold()
        if "podrias hacer esto" in normalized_response or "podes hacer esto" in normalized_response:
            return response_text
        if any(
            marker in normalized_response for marker in (
                "manana podrias hacer esto:",
                "el paso que priorizaria ahora es:",
                "si tuviera que ordenar el siguiente movimiento",
                "que presentar:",
                "que pedir:",
            )
        ):
            return response_text

        qs_body = self._normalize_quick_start_prefix(qs)
        qs = f"{_QUICK_START_PREFIX} {qs_body}".strip()
        if qs and qs[-1] not in ".!?":
            qs += "."

        if not response_text.strip():
            return qs

        first_line = response_text.split("\n")[0].strip()
        if first_line.lower().startswith(_QUICK_START_PREFIX.lower()):
            return response_text

        norm_first = re.sub(r"\s+", " ", first_line.lower())
        norm_qs = re.sub(r"\s+", " ", qs_body.lower())
        if norm_qs and SequenceMatcher(a=norm_first, b=norm_qs).ratio() >= _QUICK_START_SIMILARITY_THRESHOLD:
            return response_text

        return f"{qs}\n\n{response_text}"

    @staticmethod
    def _normalize_quick_start_prefix(text: str) -> str:
        body = str(text or "").strip()
        prefix_pattern = re.compile(rf"^(?:{re.escape(_QUICK_START_PREFIX)}\s*)+", re.IGNORECASE)
        while True:
            normalized = prefix_pattern.sub("", body, count=1).strip()
            if normalized == body:
                break
            body = normalized
        return body

    def _apply_prudence(
        self,
        *,
        response_text: str,
        pipeline_payload: dict[str, Any],
        retrieval: RetrievalBundle,
        strategy: StrategyBundle,
    ) -> str:
        text = response_text
        evidence = pipeline_payload.get("evidence_reasoning_links") or {}
        confidence_score = float(evidence.get("confidence_score") or 0.0)

        if retrieval.source_mode in {"fallback", "legacy"} or strategy.fallback_used:
            text = self._append_once(
                text,
                "La orientacion recuperada tiene valor interno y prudente; no debe tratarse como cita verificable consolidada.",
            )
        if confidence_score and confidence_score < 0.45:
            text = self._append_once(
                text,
                "La evidencia disponible todavia es debil y conviene evitar afirmaciones concluyentes sin mayor soporte.",
            )
        if strategy.blocking_factor and strategy.blocking_factor != "none":
            text = self._append_once(
                text,
                f"Bloqueo procesal detectado: {strategy.blocking_factor}.",
            )
        return self._sanitize_text(text)

    # Utilidades

    def _sanitize_text(self, text: str) -> str:
        parts = [self._normalize_whitespace(part) for part in re.split(r"\n{2,}", str(text or "")) if str(part).strip()]
        clean = [part for part in self._dedupe_lines(parts) if not self._is_noise(part)]
        return "\n\n".join(clean).strip()

    def _sanitize_warnings(self, warnings: list[Any]) -> list[str]:
        clean: list[str] = []
        for item in warnings:
            text = self._normalize_whitespace(str(item or ""))
            if not text or self._is_noise(text):
                continue
            clean.append(text)
        return self._dedupe_lines(clean)

    def _canonical_case_domain(self, payload: dict[str, Any]) -> str:
        case_profile = payload.get("case_profile") or {}
        return str(case_profile.get("case_domain") or payload.get("case_domain") or "").strip()

    def _canonical_action_slug(self, payload: dict[str, Any]) -> str:
        classification = payload.get("classification") or {}
        case_structure = payload.get("case_structure") or {}
        return str(classification.get("action_slug") or case_structure.get("action_slug") or "").strip()

    def _canonical_strategy_mode(self, payload: dict[str, Any]) -> str:
        case_strategy = payload.get("case_strategy") or {}
        legal_decision = payload.get("legal_decision") or {}
        return str(case_strategy.get("strategy_mode") or legal_decision.get("strategic_posture") or "").strip()

    def _canonical_dominant_factor(self, payload: dict[str, Any]) -> str:
        legal_decision = payload.get("legal_decision") or {}
        return str(legal_decision.get("dominant_factor") or "").strip()

    def _canonical_blocking_factor(self, payload: dict[str, Any]) -> str:
        procedural_case_state = payload.get("procedural_case_state") or {}
        return str(procedural_case_state.get("blocking_factor") or "none").strip()

    def _canonical_execution_readiness(self, payload: dict[str, Any]) -> str:
        legal_decision = payload.get("legal_decision") or {}
        return str(legal_decision.get("execution_readiness") or "").strip()

    def _canonical_confidence_score(self, payload: dict[str, Any]) -> float | None:
        legal_decision = payload.get("legal_decision") or {}
        raw = legal_decision.get("confidence_score", payload.get("confidence"))
        try:
            return round(float(raw), 4)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_pipeline_version(value: Any) -> str:
        text = str(value or "").strip()
        return text or "unknown"

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _confidence_label(confidence_score: float | None) -> str:
        if confidence_score is None:
            return "low"
        if confidence_score >= 0.75:
            return "high"
        if confidence_score >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _append_once(text: str, line: str) -> str:
        normalized_text = text.casefold()
        if line.casefold() in normalized_text:
            return text
        return f"{text}\n\n{line}".strip() if text else line

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    @staticmethod
    def _dedupe_lines(lines: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for line in lines:
            normalized = line.casefold().strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(line.strip())
        return result

    def _is_noise(self, text: str) -> bool:
        normalized = text.casefold()
        return any(pattern in normalized for pattern in _NOISE_PATTERNS)
