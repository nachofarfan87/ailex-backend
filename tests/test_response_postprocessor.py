# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_response_postprocessor.py
from __future__ import annotations

import types

from app.services.case_state_extractor_service import PROGRESSION_TO_CASE_STAGE
from legal_engine.orchestrator_schema import RetrievalBundle, StrategyBundle
from legal_engine.response_postprocessor import ResponsePostprocessor
import legal_engine.response_postprocessor as response_postprocessor_module


def test_postprocessor_removes_technical_warnings_and_noise():
    processor = ResponsePostprocessor()
    final_output = processor.postprocess(
        request_id="req-1",
        normalized_input={"query": "consulta"},
        pipeline_payload={
            "query": "consulta",
            "pipeline_version": "beta-orchestrator-v1",
            "jurisdiction": "jujuy",
            "warnings": [
                "fallback generico del motor",
                "modelo no aplicable",
                "Advertencia prudente para usuario.",
            ],
            "reasoning": {"short_answer": "Respuesta base."},
            "classification": {"action_slug": "alimentos_hijos"},
            "case_profile": {"case_domain": "alimentos"},
            "case_strategy": {"strategy_mode": "conservadora"},
            "legal_decision": {"dominant_factor": "norma", "confidence_score": 0.66, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
        },
        retrieval=RetrievalBundle(source_mode="normative_only", warnings=["generic fallback interno", "Fuente apta para usuario."]),
        strategy=StrategyBundle(strategy_mode="conservadora", dominant_factor="norma", confidence_score=0.66, confidence_label="medium"),
    )

    joined = " ".join(final_output.warnings).lower()
    assert "fallback generico" not in joined
    assert "modelo no aplicable" not in joined
    assert "advertencia prudente para usuario" in joined
    assert "fuente apta para usuario" in joined
    assert final_output.pipeline_version == "beta-orchestrator-v1"
    assert final_output.documents_considered == 0
    assert final_output.api_payload["pipeline_version"] == "beta-orchestrator-v1"


def test_postprocessor_marks_procedural_block_explicitly():
    processor = ResponsePostprocessor()
    final_output = processor.postprocess(
        request_id="req-2",
        normalized_input={"query": "consulta"},
        pipeline_payload={
            "query": "consulta",
            "pipeline_version": "beta-orchestrator-v1",
            "reasoning": {"short_answer": "Existe una base para avanzar."},
            "classification": {"action_slug": "alimentos_hijos"},
            "case_profile": {"case_domain": "alimentos"},
            "case_strategy": {"strategy_mode": "conservadora"},
            "legal_decision": {"dominant_factor": "procesal", "confidence_score": 0.58, "execution_readiness": "bloqueado_procesalmente"},
            "procedural_case_state": {"blocking_factor": "service"},
            "evidence_reasoning_links": {"confidence_score": 0.7},
        },
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(
            strategy_mode="conservadora",
            dominant_factor="procesal",
            blocking_factor="service",
            execution_readiness="bloqueado_procesalmente",
            confidence_score=0.58,
            confidence_label="medium",
        ),
    )

    assert "Bloqueo procesal detectado: service." in final_output.response_text
    assert final_output.blocking_factor == "service"


def test_postprocessor_reinforces_prudence_when_sources_or_evidence_are_weak():
    processor = ResponsePostprocessor()
    final_output = processor.postprocess(
        request_id="req-3",
        normalized_input={"query": "consulta"},
        pipeline_payload={
            "query": "consulta",
            "pipeline_version": "beta-orchestrator-v1",
            "reasoning": {"short_answer": "Respuesta base."},
            "classification": {"action_slug": "generic"},
            "case_profile": {"case_domain": "generic"},
            "case_strategy": {"strategy_mode": "cautelosa"},
            "legal_decision": {"dominant_factor": "prueba", "confidence_score": 0.42, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
            "evidence_reasoning_links": {"confidence_score": 0.31},
        },
        retrieval=RetrievalBundle(source_mode="fallback"),
        strategy=StrategyBundle(
            strategy_mode="cautelosa",
            dominant_factor="prueba",
            confidence_score=0.42,
            confidence_label="low",
            fallback_used=True,
            fallback_reason="Se recurrió a orientación interna.",
        ),
    )

    text = final_output.response_text.lower()
    assert "no debe tratarse como cita verificable consolidada" in text
    assert "la evidencia disponible todavia es debil" in text
    assert final_output.fallback_used is True


def test_postprocessor_builds_response_text_internally():
    processor = ResponsePostprocessor()
    final_output = processor.postprocess(
        request_id="req-4",
        normalized_input={"query": "consulta"},
        pipeline_payload={
            "query": "consulta",
            "pipeline_version": "beta-orchestrator-v1",
            "reasoning": {
                "short_answer": "Respuesta base.",
                "applied_analysis": "Analisis aplicado.",
            },
            "case_strategy": {"strategic_narrative": "Narrativa prudente."},
            "classification": {"action_slug": "alimentos_hijos"},
            "case_profile": {"case_domain": "alimentos"},
            "legal_decision": {"confidence_score": 0.61, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
        },
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(confidence_score=0.61, confidence_label="medium"),
    )

    assert "Respuesta base." in final_output.response_text
    assert "Analisis aplicado." in final_output.response_text
    assert "Narrativa prudente." in final_output.response_text


def test_postprocessor_exposes_documents_considered_in_canonical_output():
    processor = ResponsePostprocessor()
    final_output = processor.postprocess(
        request_id="req-5",
        normalized_input={"query": "consulta"},
        pipeline_payload={
            "query": "consulta",
            "pipeline_version": "beta-orchestrator-v1",
            "reasoning": {"short_answer": "Respuesta base."},
            "classification": {"action_slug": "alimentos_hijos"},
            "case_profile": {"case_domain": "alimentos"},
            "legal_decision": {"confidence_score": 0.61, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
        },
        retrieval=RetrievalBundle(source_mode="normative_only", documents_considered=3),
        strategy=StrategyBundle(confidence_score=0.61, confidence_label="medium"),
    )

    assert final_output.documents_considered == 3
    assert final_output.api_payload["documents_considered"] == 3
    assert final_output.api_payload["retrieval_bundle"]["documents_considered"] == 3


def test_postprocessor_uses_unknown_pipeline_version_when_missing():
    processor = ResponsePostprocessor()
    final_output = processor.postprocess(
        request_id="req-6",
        normalized_input={"query": "consulta"},
        pipeline_payload={
            "query": "consulta",
            "pipeline_version": "",
            "reasoning": {"short_answer": "Respuesta base."},
            "classification": {"action_slug": "alimentos_hijos"},
            "case_profile": {"case_domain": "alimentos"},
            "legal_decision": {"confidence_score": 0.61, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
        },
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(confidence_score=0.61, confidence_label="medium"),
    )

    assert final_output.pipeline_version == "unknown"
    assert final_output.api_payload["pipeline_version"] == "unknown"


def test_followup_question_not_forced_in_strategy_when_action_is_advise():
    processor = ResponsePostprocessor()
    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "advise",
                "dominant_missing_purpose": "quantify",
                "dominant_missing_importance": "core",
            },
            "progression_policy": {"missing_focus": ["ingresos del otro progenitor"]},
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": False,
                    "case_completeness": "high",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Cuanto gana el otro progenitor?"}},
        output_mode="estrategia",
    )

    assert question == ""


def test_followup_question_not_forced_in_execution_for_non_blocking_quantify():
    processor = ResponsePostprocessor()
    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "quantify",
                "dominant_missing_importance": "secondary",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": False,
                    "case_completeness": "high",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Cuanto gana el otro progenitor?"}},
        output_mode="ejecucion",
    )

    assert question == ""


def test_followup_question_kept_in_execution_when_it_unblocks_next_step():
    processor = ResponsePostprocessor()
    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "enable",
                "dominant_missing_importance": "core",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": True,
                    "case_completeness": "medium",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Tenes la partida de nacimiento a mano?"}},
        output_mode="ejecucion",
    )

    assert "partida de nacimiento" in question.lower()


def test_execution_no_followup_if_not_blocking():
    processor = ResponsePostprocessor()
    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "identify",
                "dominant_missing_importance": "core",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": False,
                    "case_completeness": "low",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Cual es el domicilio exacto?"}},
        output_mode="ejecucion",
    )

    assert question == ""


def test_strategy_only_one_followup_condition():
    processor = ResponsePostprocessor()

    allowed = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "enable",
                "dominant_missing_importance": "secondary",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": True,
                    "case_completeness": "medium",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Tenes comprobantes de pago?"}},
        output_mode="estrategia",
    )
    rejected = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "quantify",
                "dominant_missing_importance": "secondary",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": False,
                    "case_completeness": "high",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Cuanto gana la otra parte?"}},
        output_mode="estrategia",
    )

    assert "comprobantes" in allowed.lower()
    assert rejected == ""


def test_truncate_text_applied():
    processor = ResponsePostprocessor()
    long_action = "Presentar un escrito con una descripcion extremadamente larga que sigue agregando detalles innecesarios para el frontend y termina generando overflow visual en la tarjeta principal del usuario final."

    rendered = processor._render_execution_response(  # noqa: SLF001
        pipeline_payload={"case_strategy": {"recommended_actions": [long_action]}},
        api_payload={
            "execution_output": {
                "execution_output": {
                    "what_to_do_now": [long_action],
                    "where_to_go": [],
                    "what_to_request": [],
                    "documents_needed": [],
                }
            }
        },
    )

    assert "..." in rendered
    assert long_action not in rendered


def test_reasoning_after_output_mode(monkeypatch):
    processor = ResponsePostprocessor()
    order: list[str] = []

    def _transform(self, *, response_text, pipeline_payload, api_payload):
        order.append("transform")
        return f"TRANSFORM::{response_text}"

    def _reasoning(self, *, response_text, pipeline_payload, api_payload):
        order.append("reasoning")
        return f"REASONING::{response_text}"

    def _composer(self, *, api_payload, response_text):
        order.append("composer")
        return response_text

    monkeypatch.setattr(processor, "_transform_response_by_output_mode", types.MethodType(_transform, processor))
    monkeypatch.setattr(processor, "_inject_legal_reasoning", types.MethodType(_reasoning, processor))
    monkeypatch.setattr(processor, "_apply_conversation_composer", types.MethodType(_composer, processor))

    final_output = processor.postprocess(
        request_id="req-order",
        normalized_input={"query": "consulta"},
        pipeline_payload={
            "query": "consulta",
            "pipeline_version": "beta-orchestrator-v1",
            "output_mode": "estrategia",
            "reasoning": {"short_answer": "Respuesta base."},
            "classification": {"action_slug": "alimentos_hijos"},
            "case_profile": {"case_domain": "alimentos"},
            "legal_decision": {"confidence_score": 0.61, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
        },
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(confidence_score=0.61, confidence_label="medium"),
    )

    assert order == ["transform", "reasoning", "composer"]
    assert final_output.response_text.startswith("REASONING::TRANSFORM::")


def test_output_mode_single_source():
    processor = ResponsePostprocessor()

    output_mode = processor._get_output_mode(  # noqa: SLF001
        {
            "output_mode": "ejecucion",
            "progression_policy": {"output_mode": "estrategia"},
        }
    )

    assert output_mode == "estrategia"


def test_execution_output_does_not_override(monkeypatch):
    processor = ResponsePostprocessor()

    def _resolve_intent_resolution(**kwargs):
        return {"intent_type": "action_now"}

    def _build_execution_output(**kwargs):
        return {
            "applies": True,
            "rendered_response_text": "Manana podrias hacer esto:\n1. Presentar escrito.",
            "execution_output": {"what_to_do_now": ["Presentar escrito."]},
        }

    monkeypatch.setattr(response_postprocessor_module, "resolve_intent_resolution", _resolve_intent_resolution)
    monkeypatch.setattr(response_postprocessor_module, "build_execution_output", _build_execution_output)

    response_text = processor._attach_intent_resolution_and_execution_output(  # noqa: SLF001
        normalized_input={"query": "Que hago ahora?"},
        pipeline_payload={"query": "Que hago ahora?"},
        api_payload={
            "conversation_state": {"conversation_id": "conv-1"},
            "dialogue_policy": {"action": "hybrid"},
            "conversational_intelligence": {"recommended_adjustment": "keep_policy"},
        },
        response_text="Respuesta base con contexto.",
    )

    assert "Respuesta base con contexto." in response_text
    assert "Manana podrias hacer esto:" in response_text


def test_resolve_followup_question_usa_primero_case_followup():
    processor = ResponsePostprocessor()

    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "case_followup": {
                "should_ask": True,
                "question": "¿El divorcio sería unilateral o de común acuerdo?",
                "reason": "Define la vía estratégica inmediata.",
                "source": "case_need",
                "priority": "high",
                "need_key": "estrategia::modalidad_divorcio",
            },
            "progression_policy": {"missing_focus": ["ingresos del otro progenitor"]},
            "conversational": {"question": "¿Querés contarme más?"},
        },
        {"execution_output": {"followup_question": "¿Tenés comprobantes?"}},
        output_mode="estrategia",
    )

    assert question == "¿El divorcio sería unilateral o de común acuerdo?"


def test_resolve_followup_question_no_fuerza_si_case_followup_false():
    processor = ResponsePostprocessor()

    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "case_followup": {
                "should_ask": False,
                "question": "",
                "reason": "Hay suficiente información para avanzar sin follow-up.",
                "source": "none",
                "priority": "",
                "need_key": "",
            },
            "progression_policy": {"missing_focus": ["ingresos del otro progenitor"]},
            "conversational": {"question": "¿Querés contarme más?"},
        },
        {"execution_output": {"followup_question": "¿Tenés comprobantes?"}},
        output_mode="estrategia",
    )

    assert question == ""


def test_resolve_followup_question_anula_followup_por_readiness_alta():
    processor = ResponsePostprocessor()

    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "case_followup": {
                "should_ask": True,
                "question": "¿Podés precisar los ingresos del otro progenitor?",
                "need_key": "hecho::ingresos_otro_progenitor",
            },
            "case_progress": {
                "readiness_label": "high",
                "critical_gaps": [],
                "blocking_issues": [],
                "next_step_type": "execute",
            },
            "strategy_composition_profile": {"allow_followup": True},
        },
        {"execution_output": {}},
        output_mode="estrategia",
    )

    assert question == ""


def test_resolve_followup_question_filtra_case_followup_de_refinement_si_ya_hay_paso_claro():
    processor = ResponsePostprocessor()

    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "case_followup": {
                "should_ask": True,
                "question": "¿Cuanto gana la otra parte?",
                "need_key": "hecho::ingresos_otro_progenitor",
                "priority": "high",
                "source": "case_need",
            },
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "quantify",
                "dominant_missing_importance": "secondary",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": False,
                    "case_completeness": "high",
                }
            },
            "case_progress": {
                "readiness_label": "high",
                "critical_gaps": [],
                "blocking_issues": [],
                "next_step_type": "execute",
                "progress_status": "ready",
            },
            "strategy_composition_profile": {
                "allow_followup": True,
            },
        },
        {"execution_output": {"what_to_do_now": ["Presentar escrito inicial."]}},
        output_mode="ejecucion",
    )

    assert question == ""


def test_resolve_followup_question_anula_followup_por_strategy_mode_de_cierre():
    processor = ResponsePostprocessor()

    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "case_followup": {
                "should_ask": True,
                "question": "¿Necesito confirmar algo mas?",
                "need_key": "hecho::aportes_actuales",
            },
            "smart_strategy": {"strategy_mode": "close_without_more_questions"},
            "strategy_composition_profile": {"allow_followup": True},
        },
        {"execution_output": {}},
        output_mode="estrategia",
    )

    assert question == ""


def test_followup_integrity_arbitration_suprime_slot_ya_resuelto_por_alias(monkeypatch):
    processor = ResponsePostprocessor()
    api_payload = {
        "case_followup": {
            "should_ask": True,
            "question": "¿El otro progenitor está aportando algo actualmente?",
            "need_key": "hecho::pagos_actuales",
            "reason": "Falta cerrar si hay aportes actuales.",
        },
        "case_memory": {
            "facts": {
                "aportes_actuales": {"value": False, "source": "confirmed", "confidence": 1.0},
            }
        },
        "conversation_state": {
            "asked_questions": ["¿El otro padre o madre le pasa algo de plata actualmente?"],
        },
        "strategy_composition_profile": {"allow_followup": True},
        "smart_strategy": {"strategy_mode": "clarify_critical"},
        "case_progress": {"readiness_label": "medium", "critical_gaps": [{"key": "aportes_actuales"}]},
    }

    processor._apply_followup_integrity_arbitration(api_payload=api_payload)  # noqa: SLF001

    assert api_payload["case_followup"]["should_ask"] is False
    assert api_payload["case_followup"]["question"] == ""
    assert api_payload["case_followup"]["canonical_slot"] == "aportes_actuales"
    assert api_payload["case_followup"]["integrity_reason"] == "slot_already_resolved"


def test_attach_professional_judgment_agrega_capa_sin_romper_payload():
    processor = ResponsePostprocessor()
    api_payload = {
        "quick_start": "Presentar el reclamo principal.",
        "case_progress": {
            "readiness_label": "high",
            "progress_status": "ready",
            "next_step_type": "execute",
            "critical_gaps": [],
            "important_gaps": [],
            "blocking_issues": [],
            "contradictions": [],
        },
        "case_workspace": {
            "action_plan": [
                {
                    "title": "Presentar el reclamo principal.",
                    "why_it_matters": "Ya hay base suficiente para avanzar.",
                }
            ]
        },
        "smart_strategy": {"strategy_mode": "action_first"},
    }

    processor._attach_professional_judgment(api_payload=api_payload)  # noqa: SLF001

    judgment = api_payload["professional_judgment"]
    assert judgment["applies"] is True
    assert judgment["recommendation_stance"] == "firm_action"
    assert "Presentar el reclamo principal" in judgment["best_next_move"]
    assert api_payload["smart_strategy"]["strategy_mode"] == "action_first"


def test_resolve_followup_question_mantiene_fallback_sin_case_followup():
    processor = ResponsePostprocessor()

    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "hybrid",
                "dominant_missing_purpose": "enable",
                "dominant_missing_importance": "core",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": True,
                    "case_completeness": "medium",
                }
            },
            "progression_policy": {"missing_focus": ["domicilio relevante"]},
        },
        {"execution_output": {}},
        output_mode="estrategia",
    )

    assert "domicilio relevante" in question.lower()


def test_resolve_followup_question_humanizes_missing_focus_fallback():
    processor = ResponsePostprocessor()

    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "dialogue_policy": {
                "action": "ask",
                "dominant_missing_purpose": "enable",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": True,
                    "case_completeness": "low",
                }
            },
            "case_progress": {
                "next_step_type": "ask",
                "critical_gaps": ["hijos"],
                "blocking_issues": ["missing_children"],
            },
            "progression_policy": {
                "missing_focus": [
                    "existen hijos menores o con capacidad restringida y que cuestiones de cuidado, comunicacion y alimentos deben regularse",
                ],
            },
        },
        {"execution_output": {}},
        output_mode="orientacion_inicial",
    )

    assert question.startswith("¿")
    assert question.endswith("?")
    assert "existen hijos menores" in question.lower()


def test_resolve_followup_question_prefers_conversational_question_over_missing_focus():
    processor = ResponsePostprocessor()

    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "conversational": {"question": "¿Tienen hijos en comun?"},
            "dialogue_policy": {
                "action": "ask",
                "dominant_missing_purpose": "identify",
            },
            "conversation_state": {
                "progress_signals": {
                    "blocking_missing": True,
                    "case_completeness": "low",
                }
            },
            "case_progress": {
                "next_step_type": "ask",
                "critical_gaps": ["hijos"],
                "blocking_issues": ["missing_children"],
            },
            "progression_policy": {"missing_focus": ["existen hijos menores"]},
        },
        {"execution_output": {}},
        output_mode="orientacion_inicial",
    )

    assert question == "¿Tienen hijos en comun?"


def test_attach_case_followup_veta_followup_legacy_si_adaptive_lo_suprime(monkeypatch):
    processor = ResponsePostprocessor()
    api_payload = {
        "query": "Quiero reclamar alimentos",
        "conversation_state": {
            "conversation_memory": {
                "asked_questions": ["¿Podés precisar los ingresos del otro progenitor?"],
                "last_user_messages": ["No sé"],
            }
        },
        "case_state_snapshot": {
            "case_state": {"case_stage": "recopilacion_hechos"},
            "confirmed_facts": {},
            "probable_facts": {},
            "open_needs": [
                {
                    "need_key": "hecho::ingresos_otro_progenitor",
                    "category": "hecho",
                    "priority": "high",
                    "suggested_question": "¿Podés precisar los ingresos del otro progenitor?",
                }
            ],
        },
        "progression_policy": {"output_mode": "estructuracion"},
    }

    monkeypatch.setattr(
        response_postprocessor_module.case_followup_service,
        "build_case_followup",
        lambda **kwargs: {
            "should_ask": True,
            "question": "¿Podés precisar los ingresos del otro progenitor?",
            "reason": "Falta el dato.",
            "source": "case_need",
            "priority": "high",
            "need_key": "hecho::ingresos_otro_progenitor",
        },
    )
    monkeypatch.setattr(
        response_postprocessor_module,
        "resolve_followup_decision",
        lambda **kwargs: {
            "should_ask": False,
            "reason": "Se detectó loop.",
            "priority_question": None,
            "question_type": None,
            "detected_loop": True,
            "progress_state": "blocked",
        },
    )

    processor._attach_case_followup(api_payload=api_payload)  # noqa: SLF001

    assert api_payload["case_followup"]["should_ask"] is False
    assert api_payload["case_followup"]["adaptive_suppressed"] is True
    assert api_payload["case_followup"]["detected_loop"] is True


def test_attach_case_followup_usa_priority_question_de_adaptive_service(monkeypatch):
    processor = ResponsePostprocessor()
    api_payload = {
        "query": "Quiero iniciar mi divorcio",
        "conversation_state": {
            "conversation_memory": {},
            "recent_turns": [
                {"user_message": "Quiero iniciar mi divorcio"}
            ],
        },
        "case_state_snapshot": {
            "case_state": {"case_stage": "analisis_estrategico"},
            "confirmed_facts": {},
            "probable_facts": {},
            "open_needs": [
                {
                    "need_key": "estrategia::modalidad_divorcio",
                    "category": "estrategia",
                    "priority": "critical",
                    "suggested_question": "¿El divorcio sería unilateral o de común acuerdo?",
                }
            ],
        },
        "progression_policy": {"output_mode": "estrategia"},
    }

    monkeypatch.setattr(
        response_postprocessor_module.case_followup_service,
        "build_case_followup",
        lambda **kwargs: {
            "should_ask": True,
            "question": "¿Querés contarme más?",
            "reason": "Legacy follow-up.",
            "source": "case_need",
            "priority": "high",
            "need_key": "estrategia::modalidad_divorcio",
        },
    )
    monkeypatch.setattr(
        response_postprocessor_module,
        "resolve_followup_decision",
        lambda **kwargs: {
            "should_ask": True,
            "reason": "Hay un dato prioritario.",
            "priority_question": "¿El divorcio sería unilateral o de común acuerdo?",
            "question_type": "critical",
            "detected_loop": False,
            "progress_state": "advancing",
        },
    )

    processor._attach_case_followup(api_payload=api_payload)  # noqa: SLF001

    assert api_payload["case_followup"]["should_ask"] is True
    assert api_payload["case_followup"]["question"] == "¿El divorcio sería unilateral o de común acuerdo?"
    assert api_payload["case_followup"]["adaptive_override"] is True


def test_apply_adaptive_followup_veto_expone_nuevos_metadatos():
    postprocessor = ResponsePostprocessor()
    followup = {
        "should_ask": True,
        "question": "Â¿Pregunta legacy?",
        "priority": "high",
    }

    postprocessor._apply_adaptive_followup_veto(  # noqa: SLF001
        followup=followup,
        snapshot={
            "open_needs": [
                {
                    "need_key": "procesal::jurisdiccion",
                    "category": "procesal",
                    "priority": "critical",
                    "suggested_question": "Â¿En que provincia o jurisdiccion tramitarias esto?",
                }
            ]
        },
        api_payload={
            "query": "No se",
            "conversation_state": {
                "conversation_memory": {},
                "recent_turns": [
                    {"user_message": "No se"},
                    {"user_message": "No tengo ese dato"},
                ],
            },
        },
    )

    assert followup["should_ask"] is False
    assert followup["adaptive_suppressed"] is True
    assert followup["adaptive_progress_state"] == "blocked"
    assert followup["user_cannot_answer"] is True
    assert "stagnation_reason" in followup


def test_apply_adaptive_followup_veto_overridea_pregunta_si_hay_priority_question():
    postprocessor = ResponsePostprocessor()
    followup = {
        "should_ask": True,
        "question": "Â¿Pregunta legacy?",
        "priority": "high",
    }

    postprocessor._apply_adaptive_followup_veto(  # noqa: SLF001
        followup=followup,
        snapshot={
            "open_needs": [
                {
                    "need_key": "estrategia::modalidad_divorcio",
                    "category": "estrategia",
                    "priority": "critical",
                    "suggested_question": "Â¿El divorcio seria unilateral o de comun acuerdo?",
                }
            ]
        },
        api_payload={
            "query": "Todavia no lo definimos.",
            "conversation_state": {
                "conversation_memory": {},
                "recent_turns": [
                    {"user_message": "Estamos viendo como hacerlo."},
                ],
            },
        },
    )

    assert followup["should_ask"] is True
    assert followup["adaptive_override"] is True
    assert "divorcio" in followup["question"].lower()
    assert followup["adaptive_progress_state"] in ("advancing", "blocked", "stalled")


def test_attach_case_confidence_agrega_bloque_al_api_payload():
    processor = ResponsePostprocessor()
    api_payload = {
        "conversation_state": {
            "progress_state": "advancing",
            "known_facts": [{"key": "hay_hijos", "value": True}],
        },
        "case_state_snapshot": {
            "confirmed_facts": {
                "jurisdiccion": "Jujuy",
                "fecha_separacion": "2024-03-10",
            },
            "probable_facts": {},
            "open_needs": [
                {
                    "need_key": "estrategia::modalidad_divorcio",
                    "category": "estrategia",
                    "priority": "critical",
                    "suggested_question": "¿El divorcio seria unilateral o de comun acuerdo?",
                }
            ],
        },
        "case_followup": {
            "should_ask": True,
            "adaptive_progress_state": "advancing",
            "user_cannot_answer": False,
        },
    }

    processor._attach_case_confidence(api_payload=api_payload)  # noqa: SLF001

    assert "case_confidence" in api_payload
    assert api_payload["case_confidence"]["confidence_level"] in {"low", "medium", "high"}
    assert api_payload["case_confidence"]["needs_more_questions"] is True


def test_postprocess_incluye_case_confidence_y_convive_con_case_followup(monkeypatch):
    processor = ResponsePostprocessor()
    monkeypatch.setattr(
        response_postprocessor_module.case_followup_service,
        "build_case_followup",
        lambda **kwargs: {
            "should_ask": True,
            "question": "¿El divorcio seria unilateral o de comun acuerdo?",
            "reason": "Falta el dato.",
            "source": "case_need",
            "priority": "high",
            "need_key": "estrategia::modalidad_divorcio",
        },
    )

    final_output = processor.postprocess(
        request_id="req-case-confidence-1",
        normalized_input={"query": "Quiero iniciar mi divorcio"},
        pipeline_payload={
            "query": "Quiero iniciar mi divorcio",
            "pipeline_version": "beta-orchestrator-v1",
            "reasoning": {"short_answer": "Hay una base inicial para orientarte."},
            "classification": {"action_slug": "divorcio"},
            "case_profile": {"case_domain": "familia"},
            "legal_decision": {"confidence_score": 0.61, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
            "conversation_state": {
                "progress_state": "advancing",
                "known_facts": [{"key": "hay_hijos", "value": True}],
            },
            "case_state_snapshot": {
                "case_state": {"case_stage": "analisis_estrategico"},
                "confirmed_facts": {"jurisdiccion": "Jujuy"},
                "probable_facts": {},
                "open_needs": [
                    {
                        "need_key": "estrategia::modalidad_divorcio",
                        "category": "estrategia",
                        "priority": "critical",
                        "suggested_question": "¿El divorcio seria unilateral o de comun acuerdo?",
                    }
                ],
            },
        },
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(confidence_score=0.61, confidence_label="medium"),
    )

    assert "case_confidence" in final_output.api_payload
    assert "case_followup" in final_output.api_payload
    assert final_output.api_payload["case_confidence"]["reason"]


def test_attach_smart_strategy_agrega_bloque_al_api_payload():
    processor = ResponsePostprocessor()
    api_payload = {
        "progression_policy": {"output_mode": "estrategia"},
        "conversation_state": {
            "progress_state": "advancing",
            "known_facts": [{"key": "hay_hijos", "value": True}],
        },
        "case_state_snapshot": {
            "confirmed_facts": {
                "jurisdiccion": "Jujuy",
                "domicilio": "Jujuy",
            },
            "probable_facts": {},
            "open_needs": [
                {
                    "need_key": "estrategia::modalidad_divorcio",
                    "category": "estrategia",
                    "priority": "critical",
                    "suggested_question": "Â¿El divorcio seria unilateral o de comun acuerdo?",
                }
            ],
        },
        "case_followup": {
            "should_ask": True,
            "adaptive_progress_state": "advancing",
        },
        "case_confidence": {
            "confidence_level": "low",
            "case_stage": "developing",
            "needs_more_questions": True,
            "closure_readiness": "low",
            "recommended_depth": "minimal",
        },
    }

    processor._attach_smart_strategy(api_payload=api_payload)  # noqa: SLF001

    assert "smart_strategy" in api_payload
    assert api_payload["smart_strategy"]["strategy_mode"]
    assert api_payload["smart_strategy"]["reason"]


def test_postprocess_incluye_smart_strategy_y_convive_con_otras_capas(monkeypatch):
    processor = ResponsePostprocessor()
    monkeypatch.setattr(
        response_postprocessor_module.case_followup_service,
        "build_case_followup",
        lambda **kwargs: {
            "should_ask": True,
            "question": "Â¿El divorcio seria unilateral o de comun acuerdo?",
            "reason": "Falta el dato.",
            "source": "case_need",
            "priority": "high",
            "need_key": "estrategia::modalidad_divorcio",
        },
    )

    final_output = processor.postprocess(
        request_id="req-smart-strategy-1",
        normalized_input={"query": "Quiero iniciar mi divorcio"},
        pipeline_payload={
            "query": "Quiero iniciar mi divorcio",
            "pipeline_version": "beta-orchestrator-v1",
            "reasoning": {"short_answer": "Hay una base inicial para orientarte."},
            "classification": {"action_slug": "divorcio"},
            "case_profile": {"case_domain": "familia"},
            "legal_decision": {"confidence_score": 0.61, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
            "conversation_state": {
                "progress_state": "advancing",
                "known_facts": [{"key": "hay_hijos", "value": True}],
            },
            "case_state_snapshot": {
                "case_state": {"case_stage": "analisis_estrategico"},
                "confirmed_facts": {"jurisdiccion": "Jujuy", "domicilio": "Jujuy"},
                "probable_facts": {},
                "open_needs": [
                    {
                        "need_key": "estrategia::modalidad_divorcio",
                        "category": "estrategia",
                        "priority": "critical",
                        "suggested_question": "Â¿El divorcio seria unilateral o de comun acuerdo?",
                    }
                ],
            },
            "progression_policy": {"output_mode": "estrategia"},
        },
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(confidence_score=0.61, confidence_label="medium"),
    )

    assert "smart_strategy" in final_output.api_payload
    assert "case_followup" in final_output.api_payload
    assert "case_confidence" in final_output.api_payload
    assert final_output.api_payload["smart_strategy"]["strategy_mode"]


def test_attach_strategy_composition_profile_agrega_policy_al_api_payload():
    processor = ResponsePostprocessor()
    api_payload = {
        "progression_policy": {"output_mode": "estrategia"},
        "smart_strategy": {"strategy_mode": "clarify_critical"},
        "case_followup": {"should_ask": True},
        "case_confidence": {"recommended_depth": "minimal"},
    }

    processor._attach_strategy_composition_profile(api_payload=api_payload)  # noqa: SLF001

    assert "strategy_composition_profile" in api_payload
    assert api_payload["strategy_composition_profile"]["strategy_mode"] == "clarify_critical"


def test_close_without_more_questions_no_reabre_followup():
    processor = ResponsePostprocessor()
    question = processor._resolve_followup_question(  # noqa: SLF001
        {
            "case_followup": {
                "should_ask": True,
                "question": "¿Necesito confirmar algo mas?",
            },
            "strategy_composition_profile": {
                "allow_followup": False,
            },
        },
        {"execution_output": {"followup_question": "¿Necesito confirmar algo mas?"}},
        output_mode="estrategia",
    )

    assert question == ""


def test_action_first_pone_pasos_concretos_arriba():
    processor = ResponsePostprocessor()
    rendered = processor._render_execution_response(  # noqa: SLF001
        pipeline_payload={},
        api_payload={
            "smart_strategy": {"strategy_mode": "action_first"},
            "strategy_composition_profile": {
                "strategy_mode": "action_first",
                "allow_followup": False,
                "prioritize_action": True,
            },
            "execution_output": {
                "execution_output": {
                    "what_to_do_now": ["Presentar escrito.", "Reunir documentacion."],
                    "where_to_go": ["Juzgado competente."],
                    "what_to_request": ["Fijacion provisoria de cuota."],
                    "documents_needed": ["Partida de nacimiento."],
                }
            },
        },
    )

    assert rendered.startswith("Para avanzar de forma concreta, podes hacer esto:")
    assert "Presentar escrito." in rendered


def test_clarify_critical_genera_salida_corta_y_una_sola_pregunta():
    processor = ResponsePostprocessor()
    rendered = processor._render_strategy_response(  # noqa: SLF001
        pipeline_payload={},
        api_payload={
            "conversation_state": {},
            "progression_policy": {},
            "execution_output": {},
            "smart_strategy": {"strategy_mode": "clarify_critical"},
            "strategy_composition_profile": {
                "strategy_mode": "clarify_critical",
                "allow_followup": True,
            },
            "case_followup": {
                "should_ask": True,
                "question": "¿El divorcio seria unilateral o de comun acuerdo?",
            },
            "strategic_decision": {},
        },
    )

    assert rendered.count("?") == 1
    assert len(rendered) < 400


def test_case_progress_narrative_se_adjunta_a_api_payload():
    processor = ResponsePostprocessor()

    api_payload = {
        "progression_policy": {"output_mode": "estructuracion"},
        "case_state_snapshot": {
            "case_state": {"case_stage": "recopilacion_hechos", "primary_goal": "reclamar cuota alimentaria"},
            "confirmed_facts": {"hay_hijos": True},
            "probable_facts": {},
            "open_needs": [{"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high"}],
        },
    }

    processor._attach_case_progress_narrative(api_payload=api_payload)  # noqa: SLF001

    assert "case_progress_narrative" in api_payload
    assert api_payload["case_progress_narrative"]["applies"] is True


def test_case_progress_narrative_enriquece_response_text():
    processor = ResponsePostprocessor()

    enriched = processor._inject_case_progress_narrative(  # noqa: SLF001
        response_text="Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
        api_payload={
            "progression_policy": {"output_mode": "estructuracion"},
            "case_progress_narrative": {
                "applies": True,
                "opening": "Con lo que ya sabemos hasta ahora...",
                "known_block": "Ya esta claro que hay hijos involucrados.",
                "missing_block": "Todavia falta precisar los ingresos del otro progenitor.",
                "progress_block": "Con esto ya se puede ordenar mejor el caso.",
                "priority_block": "",
            },
        },
    )

    assert "ingresos del otro progenitor" in enriched.lower()


def test_case_progress_narrative_no_rompe_output_mode_actual():
    processor = ResponsePostprocessor()

    enriched = processor._inject_case_progress_narrative(  # noqa: SLF001
        response_text="Para avanzar de forma concreta, podes hacer esto:\n1. Presentar escrito.",
        api_payload={
            "progression_policy": {"output_mode": "ejecucion"},
            "case_progress_narrative": {
                "applies": True,
                "opening": "",
                "known_block": "",
                "missing_block": "",
                "progress_block": "Con lo que ya esta definido, ya se puede avanzar de forma concreta.",
                "priority_block": "",
            },
        },
    )

    assert enriched.startswith("Para avanzar de forma concreta")


def test_case_progress_narrative_no_duplica_bloques_ya_presentes():
    processor = ResponsePostprocessor()

    enriched = processor._inject_case_progress_narrative(  # noqa: SLF001
        response_text="Ya esta claro que hay hijos involucrados.",
        api_payload={
            "progression_policy": {"output_mode": "estructuracion"},
            "case_progress_narrative": {
                "applies": True,
                "opening": "",
                "known_block": "Ya esta claro que hay hijos involucrados.",
                "missing_block": "",
                "progress_block": "",
                "priority_block": "",
            },
        },
    )

    assert enriched.count("Ya esta claro que hay hijos involucrados.") == 1


def test_progression_mapping_constant():
    assert PROGRESSION_TO_CASE_STAGE["structuring_case"] == "analisis_estructurado"
    assert PROGRESSION_TO_CASE_STAGE["strategy"] == "analisis_estrategico"
    assert PROGRESSION_TO_CASE_STAGE["execution"] == "ejecucion"
    assert PROGRESSION_TO_CASE_STAGE.get("unknown", "recopilacion_hechos") == "recopilacion_hechos"


def test_postprocessor_coerces_invalid_documents_considered_to_zero():
    processor = ResponsePostprocessor()
    final_output = processor.postprocess(
        request_id="req-7",
        normalized_input={"query": "consulta"},
        pipeline_payload={
            "query": "consulta",
            "pipeline_version": "beta-orchestrator-v1",
            "reasoning": {"short_answer": "Respuesta base."},
            "classification": {"action_slug": "alimentos_hijos"},
            "case_profile": {"case_domain": "alimentos"},
            "legal_decision": {"confidence_score": 0.61, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
            "documents_considered": "no-num",
        },
        retrieval=RetrievalBundle(source_mode="normative_only", documents_considered="no-num"),  # type: ignore[arg-type]
        strategy=StrategyBundle(confidence_score=0.61, confidence_label="medium"),
    )

    assert final_output.documents_considered == 0


def test_no_duplicate_blocks():
    processor = ResponsePostprocessor()

    normalized = processor._normalize_final_response(  # noqa: SLF001
        "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.\n\n"
        "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.\n\n"
        "Para avanzar de forma concreta, podes hacer esto:\n1. Presentar escrito."
    )

    assert normalized.count("Con lo que me contaste hasta ahora") == 1


def test_followup_only_when_needed():
    processor = ResponsePostprocessor()

    allowed = processor._should_include_followup_question(  # noqa: SLF001
        api_payload={
            "dialogue_policy": {"action": "hybrid", "dominant_missing_purpose": "enable"},
            "conversation_state": {"progress_signals": {"case_completeness": "medium", "blocking_missing": True}},
        },
        execution_output={"execution_output": {}},
        output_mode="estrategia",
        question="¿Falta un dato clave?",
    )
    rejected = processor._should_include_followup_question(  # noqa: SLF001
        api_payload={
            "dialogue_policy": {"action": "hybrid", "dominant_missing_purpose": "enable"},
            "conversation_state": {"progress_signals": {"case_completeness": "high", "blocking_missing": False}},
        },
        execution_output={"execution_output": {}},
        output_mode="estrategia",
        question="¿Falta un dato clave?",
    )

    assert allowed is True
    assert rejected is False


def test_execution_short_and_clear():
    processor = ResponsePostprocessor()
    long_text = " ".join(
        [
            "Para avanzar de forma concreta, podes hacer esto.",
            "1. Presentar escrito.",
            "2. Reunir documentacion.",
            "3. Pedir medida provisoria.",
            "Donde ir: juzgado competente.",
            "Que presentar: partida de nacimiento y comprobantes.",
        ]
        * 20
    )

    limited = processor._apply_length_limits(long_text, output_mode="ejecucion")  # noqa: SLF001

    assert len(limited) <= 600


def test_strategy_no_repetition():
    processor = ResponsePostprocessor()

    normalized = processor._normalize_final_response(  # noqa: SLF001
        "Hoy, lo mas solido es ir por este camino: iniciar la demanda.\n\n"
        "Hoy, lo mas solido es ir por este camino: iniciar la demanda.\n\n"
        "El paso que priorizaria ahora es: presentar el escrito."
    )

    assert normalized.count("Hoy, lo mas solido es ir por este camino") == 1


def test_clean_closing():
    processor = ResponsePostprocessor()

    closed = processor._normalize_closing(  # noqa: SLF001
        "Hoy, lo mas solido es ir por este camino: iniciar la demanda.",
        has_followup=False,
    )

    assert closed.endswith("Con esto ya podés avanzar con bastante claridad.")


def test_single_followup_only():
    processor = ResponsePostprocessor()

    normalized = processor._normalize_closing(  # noqa: SLF001
        "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor. "
        "¿Falta el domicilio? El paso prioritario es presentar el escrito. "
        "¿El divorcio sería unilateral o de común acuerdo?",
        has_followup=True,
    )

    assert normalized.count("?") == 1


def test_attach_strategy_language_profile_agrega_policy_al_api_payload():
    processor = ResponsePostprocessor()
    api_payload = {
        "progression_policy": {"output_mode": "estrategia"},
        "conversation_state": {"turn_count": 2},
        "smart_strategy": {"strategy_mode": "orient_with_prudence"},
        "strategy_composition_profile": {"allow_followup": False},
    }

    processor._attach_strategy_language_profile(api_payload=api_payload)  # noqa: SLF001

    assert "strategy_language_profile" in api_payload
    assert api_payload["strategy_language_profile"]["tone_style"] == "prudent"


def test_normalize_closing_preserves_strategy_language_closing():
    processor = ResponsePostprocessor()
    processor._strategy_language_profile = {  # noqa: SLF001
        "selected_closing": "Con esta base ya se puede avanzar con cuidado y con criterio."
    }
    processor._strategy_composition_profile = {"closing_style": "clean_close"}  # noqa: SLF001

    closed = processor._normalize_closing(  # noqa: SLF001
        "Con lo que hay hoy, conviene avanzar asi: iniciar el reclamo.",
        has_followup=False,
    )

    assert closed.endswith("Con esta base ya se puede avanzar con cuidado y con criterio.")


def test_normalize_closing_avoid_tono_firme_si_progress_status_stalled():
    processor = ResponsePostprocessor()
    processor._strategy_language_profile = {  # noqa: SLF001
        "selected_closing": "Con esto ya podés avanzar con bastante claridad."
    }
    processor._strategy_composition_profile = {"closing_style": "clean_close"}  # noqa: SLF001
    processor._case_progress = {"progress_status": "stalled", "next_step_type": "ask"}  # noqa: SLF001

    closed = processor._normalize_closing(  # noqa: SLF001
        "Con lo que hay hoy, el caso se puede ordenar mejor.",
        has_followup=False,
    )

    assert "todavia conviene cerrar el dato que falta" in closed.lower()


def test_normalize_closing_permite_tono_mas_firme_si_progress_status_ready():
    processor = ResponsePostprocessor()
    processor._strategy_language_profile = {"selected_closing": ""}  # noqa: SLF001
    processor._strategy_composition_profile = {"closing_style": "action_close"}  # noqa: SLF001
    processor._case_progress = {"progress_status": "ready", "next_step_type": "execute"}  # noqa: SLF001

    closed = processor._normalize_closing(  # noqa: SLF001
        "Para avanzar de forma concreta, podes hacer esto:\n1. Presentar escrito.",
        has_followup=False,
    )

    assert "para avanzar de forma concreta" in closed.lower() or "siguiente paso concreto" in closed.lower()


def test_postprocessor_no_pisa_tono_directo_de_action_first():
    processor = ResponsePostprocessor()
    rendered = processor._render_execution_response(  # noqa: SLF001
        pipeline_payload={},
        api_payload={
            "conversation_state": {"turn_count": 2},
            "smart_strategy": {"strategy_mode": "action_first"},
            "strategy_composition_profile": {
                "strategy_mode": "action_first",
                "allow_followup": False,
                "prioritize_action": True,
            },
            "strategy_language_profile": {
                "selected_bridge": "Anda por esto:",
                "selected_followup_intro": "",
            },
            "execution_output": {
                "execution_output": {
                    "what_to_do_now": ["Presentar escrito.", "Reunir documentacion."],
                }
            },
        },
    )

    assert rendered.startswith("Anda por esto:")


def test_transform_response_by_output_mode_delega_en_response_composition_service(monkeypatch):
    processor = ResponsePostprocessor()

    monkeypatch.setattr(
        response_postprocessor_module,
        "resolve_response_composition",
        lambda **kwargs: {
            "rendered_response_text": "respuesta delegada",
            "response_sections": ["respuesta delegada"],
            "composition_metadata": {"output_mode": "estrategia"},
            "strategic_decision": {"recommended_path": "via principal"},
        },
    )

    api_payload = {
        "progression_policy": {"output_mode": "estrategia"},
        "conversation_state": {},
        "dialogue_policy": {},
        "execution_output": {},
        "smart_strategy": {"strategy_mode": "guide_next_step"},
        "strategy_composition_profile": {"strategy_mode": "guide_next_step"},
        "strategy_language_profile": {"selected_bridge": "Con lo que hay hoy, conviene avanzar asi:"},
    }

    rendered = processor._transform_response_by_output_mode(  # noqa: SLF001
        response_text="texto base",
        pipeline_payload={},
        api_payload=api_payload,
    )

    assert rendered == "respuesta delegada"
    assert api_payload["response_composition"]["composition_metadata"]["output_mode"] == "estrategia"
    assert api_payload["strategic_decision"]["recommended_path"] == "via principal"


def test_postprocess_includes_case_workspace_in_final_payload():
    processor = ResponsePostprocessor()

    final_output = processor.postprocess(
        request_id="req-case-workspace",
        normalized_input={
            "query": "Quiero iniciar alimentos",
            "metadata": {"conversation_id": "conv-case-workspace"},
        },
        pipeline_payload={
            "query": "Quiero iniciar alimentos",
            "pipeline_version": "beta-orchestrator-v1",
            "reasoning": {"short_answer": "Hay una base prudente para avanzar."},
            "classification": {"action_slug": "alimentos_hijos"},
            "case_profile": {"case_domain": "alimentos"},
            "legal_decision": {"confidence_score": 0.61, "execution_readiness": "requiere_impulso_procesal"},
            "procedural_case_state": {"blocking_factor": "none"},
            "conversation_state": {
                "conversation_id": "conv-case-workspace",
                "progress_state": "advancing",
                "known_facts": [{"key": "hay_hijos", "value": True, "status": "confirmed"}],
            },
            "case_state_snapshot": {
                "case_state": {"case_stage": "recopilacion_hechos", "primary_goal": "reclamar cuota alimentaria"},
                "confirmed_facts": {"hay_hijos": True},
                "probable_facts": {},
                "open_needs": [
                    {
                        "need_key": "hecho::ingresos_otro_progenitor",
                        "category": "hecho",
                        "priority": "critical",
                        "suggested_question": "¿Podes precisar los ingresos del otro progenitor?",
                    }
                ],
                "contradictions": [],
            },
            "progression_policy": {"output_mode": "estructuracion"},
        },
        retrieval=RetrievalBundle(source_mode="normative_only"),
        strategy=StrategyBundle(confidence_score=0.61, confidence_label="medium"),
    )

    workspace = final_output.api_payload["case_workspace"]
    assert workspace["case_id"] == "conv-case-workspace"
    assert workspace["workspace_version"] == "case_workspace_v1"
    assert "case_status" in workspace
    assert "strategy_snapshot" in workspace
    assert "professional_handoff" in workspace
    assert workspace["last_updated_at"].endswith("Z")
