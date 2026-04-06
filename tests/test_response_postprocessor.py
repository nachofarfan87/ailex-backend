from __future__ import annotations

from legal_engine.orchestrator_schema import RetrievalBundle, StrategyBundle
from legal_engine.response_postprocessor import ResponsePostprocessor


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
                    "blocking_missing": False,
                    "case_completeness": "medium",
                }
            },
        },
        {"execution_output": {"followup_question": "¿Tenes la partida de nacimiento a mano?"}},
        output_mode="ejecucion",
    )

    assert "partida de nacimiento" in question.lower()


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
