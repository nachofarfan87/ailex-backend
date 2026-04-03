# c:\Users\nacho\Documents\APPS\AILEX\backend\legal_engine\response_postprocessor.py
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from app.services import conversation_observability_service
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
from app.services.strategic_decision_service import resolve_strategic_decision
from legal_engine.orchestrator_schema import FinalOutput, RetrievalBundle, StrategyBundle


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
        response_text = self._prepend_quick_start(
            response_text, pipeline_payload.get("quick_start"),
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
        response_text = self._inject_legal_reasoning(
            response_text=response_text,
            pipeline_payload=pipeline_payload,
            api_payload=api_payload,
        )
        response_text = self._transform_response_by_output_mode(
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

        # 8.3 — Persist conversation memory
        # Registra en el snapshot lo que pasó en este turno (policy + composer).
        # Si falla, no afecta la respuesta.
        self._persist_conversation_memory(db=db, api_payload=api_payload)
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
        progression_policy = api_payload.get("progression_policy") or {}
        output_mode = str(
            progression_policy.get("output_mode")
            or api_payload.get("output_mode")
            or "orientacion_inicial"
        ).strip()
        if output_mode == "orientacion_inicial":
            return response_text

        try:
            if output_mode == "estructuracion":
                return self._render_structuring_response(
                    pipeline_payload=pipeline_payload,
                    api_payload=api_payload,
                )
            if output_mode == "estrategia":
                return self._render_strategy_response(
                    pipeline_payload=pipeline_payload,
                    api_payload=api_payload,
                )
            if output_mode == "ejecucion":
                return self._render_execution_response(
                    pipeline_payload=pipeline_payload,
                    api_payload=api_payload,
                )
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
        conversation_state = dict(api_payload.get("conversation_state") or {})
        dialogue_policy = dict(api_payload.get("dialogue_policy") or {})
        execution_output = dict(api_payload.get("execution_output") or {})
        progression_policy = dict(api_payload.get("progression_policy") or {})

        known_items = self._select_known_case_facts(conversation_state)[:3]
        missing_items = self._select_missing_case_facts(conversation_state)[:3]
        point_key = self._resolve_point_key(dialogue_policy, conversation_state)
        followup_question = self._resolve_followup_question(api_payload, execution_output)

        sections: list[str] = []
        sections.append(
            "Con lo que me contaste hasta ahora:\n" +
            "\n".join(f"- {item}" for item in (known_items or ["Ya hay una base inicial del caso, pero conviene ordenarla mejor."]))
        )
        sections.append(
            "Lo que todavia falta definir:\n" +
            "\n".join(f"- {item}" for item in (missing_items or ["Queda cerrar el dato que define el encuadre final."]))
        )
        if point_key:
            sections.append(f"Ahora lo mas importante es: {point_key}.")
        elif progression_policy.get("missing_focus"):
            sections.append(
                f"Ahora lo mas importante es: {str((progression_policy.get('missing_focus') or [''])[0]).strip()}."
            )
        if followup_question:
            sections.append(f"Para seguir, necesito confirmar: {followup_question}")
        return "\n\n".join(section for section in sections if section.strip()).strip()

    def _render_strategy_response(
        self,
        *,
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> str:
        conversation_state = dict(api_payload.get("conversation_state") or {})
        progression_policy = dict(api_payload.get("progression_policy") or {})
        execution_output = dict(api_payload.get("execution_output") or {})
        strategic_decision = resolve_strategic_decision(
            conversation_state=conversation_state,
            pipeline_payload=pipeline_payload,
            progression_policy=progression_policy,
        )
        api_payload["strategic_decision"] = strategic_decision

        recommended_path = self._strip_known_quick_start(str(strategic_decision.get("recommended_path") or "").strip())
        priority_action = self._strip_known_quick_start(str(strategic_decision.get("priority_action") or "").strip())
        justification = str(strategic_decision.get("justification") or "").strip()
        alternative_path = self._strip_known_quick_start(str(strategic_decision.get("alternative_path") or "").strip())
        alternative_reason = str(strategic_decision.get("alternative_reason") or "").strip()
        followup_question = self._resolve_followup_question(api_payload, execution_output)

        sections: list[str] = []
        if recommended_path:
            sections.append(f"En este caso, lo mas conveniente es: {recommended_path}")
        if priority_action:
            sections.append(f"La accion prioritaria ahora es: {priority_action}")
        if justification:
            sections.append(f"Esto suele convenir porque {justification[0].lower() + justification[1:] if len(justification) > 1 else justification.lower()}.")
        if alternative_path:
            sections.append(f"Otra opcion seria {alternative_path}, pero suele ser menos conveniente porque {alternative_reason or 'normalmente deja mas puntos criticos abiertos antes de presentar'}.")
        if followup_question:
            sections.append(f"Antes de cerrar la estrategia, necesito confirmar esto: {followup_question}")
        return "\n\n".join(section for section in sections if section.strip()).strip()

    def _render_execution_response(
        self,
        *,
        pipeline_payload: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> str:
        execution_output = dict(api_payload.get("execution_output") or {})
        execution_data = dict(execution_output.get("execution_output") or {})
        actions = self._dedupe_texts(list(execution_data.get("what_to_do_now") or []))
        where_to_go = self._dedupe_texts(list(execution_data.get("where_to_go") or []))
        requests = self._dedupe_texts(list(execution_data.get("what_to_request") or []))
        documents = self._dedupe_texts(list(execution_data.get("documents_needed") or []))
        followup_question = self._resolve_followup_question(api_payload, execution_output)

        if not actions:
            case_strategy = dict(pipeline_payload.get("case_strategy") or {})
            actions = self._dedupe_texts(list(case_strategy.get("recommended_actions") or []))[:3]

        sections: list[str] = []
        sections.append(
            "Manana podrias hacer esto:\n" +
            "\n".join(f"{index}. {item}" for index, item in enumerate(actions[:3], start=1))
        )
        if where_to_go:
            sections.append(
                "Donde ir:\n" +
                "\n".join(f"- {item}" for item in where_to_go[:2])
            )
        if documents:
            sections.append(
                "Que presentar:\n" +
                "\n".join(f"- {item}" for item in documents[:3])
            )
        if requests:
            sections.append(
                "Que pedir:\n" +
                "\n".join(f"- {item}" for item in requests[:3])
            )
        sections.append("Si no tenes abogado:\n- podes pedir orientacion inicial en defensoria o en el organismo publico que corresponda en tu jurisdiccion.")
        if followup_question:
            sections.append(f"Para ajustar el paso siguiente, necesito este dato: {followup_question}")
        return "\n\n".join(section for section in sections if section.strip()).strip()

    def _select_known_case_facts(self, conversation_state: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for item in list(conversation_state.get("known_facts") or []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            value = item.get("value")
            rendered = self._render_known_fact(key=key, value=value)
            if rendered:
                result.append(rendered)
        return self._dedupe_texts(result)

    def _select_missing_case_facts(self, conversation_state: dict[str, Any]) -> list[str]:
        critical: list[str] = []
        ordinary: list[str] = []
        for item in list(conversation_state.get("missing_facts") or []):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("key") or "").strip()
            priority = str(item.get("priority") or "").strip().lower()
            importance = str(item.get("importance") or "").strip().lower()
            purpose = str(item.get("purpose") or "").strip().lower()
            if not label:
                continue
            if priority in {"critical", "high", "required"} or importance == "core" or purpose in {"identify", "enable"}:
                critical.append(label)
            else:
                ordinary.append(label)
        return self._dedupe_texts([*critical, *ordinary])

    def _resolve_point_key(self, dialogue_policy: dict[str, Any], conversation_state: dict[str, Any]) -> str:
        dominant = str(dialogue_policy.get("dominant_missing_key") or "").strip().replace("_", " ")
        if dominant:
            return dominant
        missing = self._select_missing_case_facts(conversation_state)
        return missing[0] if missing else ""

    def _resolve_followup_question(
        self,
        api_payload: dict[str, Any],
        execution_output: dict[str, Any],
    ) -> str:
        execution_data = dict(execution_output.get("execution_output") or {})
        question = str(execution_data.get("followup_question") or "").strip()
        if question:
            return question
        progression_policy = dict(api_payload.get("progression_policy") or {})
        missing_focus = list(progression_policy.get("missing_focus") or [])
        if missing_focus:
            return f"Necesito precisar {str(missing_focus[0]).strip()}."
        conversational = dict(api_payload.get("conversational") or {})
        return str(conversational.get("question") or "").strip()

    def _render_known_fact(self, *, key: str, value: Any) -> str:
        clean_key = str(key or "").strip().replace("_", " ")
        clean_value = str(value or "").strip()
        if key == "hay_hijos":
            return "Hay hijos involucrados." if str(value).lower() not in {"false", "0", "no"} else "No aparecen hijos involucrados."
        if key == "rol_procesal" and clean_value:
            return f"El rol procesal informado es {clean_value}."
        if key == "ingresos_otro_progenitor" and clean_value:
            return "Ya hay un dato inicial sobre los ingresos del otro progenitor."
        if clean_value:
            return f"{clean_key.capitalize()}: {clean_value}."
        return ""

    def _strip_known_quick_start(self, text: str) -> str:
        value = str(text or "").strip()
        prefix = "Primer paso recomendado:"
        if value.lower().startswith(prefix.lower()):
            return value[len(prefix):].strip(" .:")
        return value

    def _dedupe_texts(self, items: list[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            value = str(item or "").strip()
            normalized = value.casefold()
            if not value or normalized in seen:
                continue
            seen.add(normalized)
            result.append(value)
        return result

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
            )
            if result:
                api_payload["composer_output"] = result
                composed = str(result.get("composed_response_text") or "").strip()
                if composed:
                    return composed
        except Exception:
            logger.exception("No se pudo aplicar conversation composer (8.2D).")

        return response_text

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
                return rendered
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
            if rendered and progression_policy.get("output_mode") != "orientacion_inicial":
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

    def _prepend_quick_start(self, response_text: str, quick_start: str | None) -> str:
        """Insert quick_start at the beginning of response_text if not already present."""
        qs = str(quick_start or "").strip()
        if not qs:
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
