# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_conversation_composer_service.py
"""
Tests — Fase 8.2D + 8.3: Conversation Composer

Fase 8.2D:
a. primer turno → composición tipo initial (pass-through)
b. turno siguiente → composición tipo followup (lead_text prepended)
c. guidance_strength=low → solo pregunta, sin body de orientación
d. guidance_strength=medium → max 2 párrafos de contenido + pregunta
e. guidance_strength=high → body sin recorte
f. reduce repetición de párrafo de orientación genérica en turno > 1
g. integra question_intro como puente antes de la pregunta
h. si falla el composer, la respuesta no se rompe (test en postprocessor)
i. integración pipeline usa composed_response_text si existe

Fase 8.3:
f2. guidance_strength=low conserva 1 párrafo útil cuando orientación no fue explicada
g2. trim más agresivo cuando orientacion_base ya fue explicada
h2. lead_text varía cuando el mismo tipo se usó >= LEAD_VARY_WINDOW veces
h3. lead_text NO varía cuando el tipo se usó < LEAD_VARY_WINDOW veces
j2. estimate_repetition más agresivo con already_explained_orientation=True
k2. conversation_memory se persiste en api_payload tras turno completo
"""
from __future__ import annotations

import pytest

from app.services.conversation_composer_service import (
    build_body_bridge,
    build_question_intro,
    compose,
    detect_turn_type,
    estimate_repetition,
    resolve_lead_text,
    trim_body_for_strength,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _state(
    turn_count: int = 1,
    known_fact_count: int = 0,
    missing_fact_count: int = 0,
    case_completeness: str = "low",
    blocking_missing: bool = False,
    working_case_type: str = "alimentos_hijos",
) -> dict:
    return {
        "turn_count": turn_count,
        "working_case_type": working_case_type,
        "progress_signals": {
            "known_fact_count": known_fact_count,
            "missing_fact_count": missing_fact_count,
            "case_completeness": case_completeness,
            "blocking_missing": blocking_missing,
        },
    }


def _policy(
    action: str = "ask",
    guidance_strength: str = "medium",
    dominant_missing_key: str = "ingresos_otro_progenitor",
    dominant_missing_purpose: str = "quantify",
    dominant_missing_importance: str = "core",
) -> dict:
    return {
        "action": action,
        "guidance_strength": guidance_strength,
        "dominant_missing_key": dominant_missing_key,
        "dominant_missing_purpose": dominant_missing_purpose,
        "dominant_missing_importance": dominant_missing_importance,
    }


_ORIENTATION_PARA = (
    "De acuerdo con la normativa argentina y en base a los datos que tenés, "
    "el proceso de reclamación de alimentos se inicia ante el juzgado competente. "
    "A partir de la información disponible, el trámite requiere varios pasos."
)

_LEGAL_CONTENT_PARA = (
    "El progenitor tiene derecho a reclamar una cuota alimentaria proporcional "
    "a los ingresos del otro progenitor."
)

_QUESTION_PARA = "¿El otro progenitor está aportando algo actualmente?"


# ─── Tests: detect_turn_type ──────────────────────────────────────────────────


def test_detect_turn_type_initial_on_first_turn():
    assert detect_turn_type(_state(turn_count=1), _policy()) == "initial"


def test_detect_turn_type_initial_on_zero_turns():
    assert detect_turn_type(_state(turn_count=0), _policy()) == "initial"


def test_detect_turn_type_clarification_when_ask():
    assert detect_turn_type(_state(turn_count=2), _policy(action="ask")) == "clarification"


def test_detect_turn_type_guided_followup_when_hybrid():
    assert detect_turn_type(_state(turn_count=3), _policy(action="hybrid")) == "guided_followup"


def test_detect_turn_type_partial_closure_when_advise_high():
    state = _state(turn_count=4, case_completeness="high")
    assert detect_turn_type(state, _policy(action="advise")) == "partial_closure"


def test_detect_turn_type_followup_generic():
    state = _state(turn_count=4, case_completeness="medium")
    assert detect_turn_type(state, _policy(action="advise")) == "followup"


def test_detect_turn_type_handles_none_inputs():
    assert detect_turn_type(None, None) == "initial"


# ─── Tests: resolve_lead_text ─────────────────────────────────────────────────


def test_resolve_lead_text_empty_for_initial():
    lead = resolve_lead_text("initial", _state(), _policy())
    assert lead == ""


def test_resolve_lead_text_nonempty_for_clarification():
    lead = resolve_lead_text("clarification", _state(turn_count=2, known_fact_count=2), _policy())
    assert lead
    assert isinstance(lead, str)
    assert len(lead) > 10


def test_resolve_lead_text_nonempty_for_followup():
    lead = resolve_lead_text("followup", _state(turn_count=3, case_completeness="medium"), _policy())
    assert lead
    assert "base" in lead.lower() or "contexto" in lead.lower() or "avanzar" in lead.lower()


def test_resolve_lead_text_partial_closure():
    lead = resolve_lead_text("partial_closure", _state(turn_count=4), _policy())
    assert lead
    assert "explicaste" in lead.lower() or "contás" in lead.lower()


def test_resolve_lead_text_guided_followup_medium_completeness():
    state = _state(turn_count=3, case_completeness="medium")
    lead = resolve_lead_text("guided_followup", state, _policy())
    assert lead
    assert "detalle" in lead.lower() or "falta" in lead.lower() or "precisar" in lead.lower()


# ─── Tests: estimate_repetition ───────────────────────────────────────────────


def test_estimate_repetition_false_on_turn_1():
    assert estimate_repetition(_ORIENTATION_PARA, turn_count=1) is False


def test_estimate_repetition_true_on_turn_2_with_orientation_para():
    text = f"{_ORIENTATION_PARA}\n\n{_LEGAL_CONTENT_PARA}"
    assert estimate_repetition(text, turn_count=2) is True


def test_estimate_repetition_false_when_no_orientation_keywords():
    text = f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    assert estimate_repetition(text, turn_count=2) is False


def test_estimate_repetition_false_on_empty_text():
    assert estimate_repetition("", turn_count=2) is False


# ─── Tests: trim_body_for_strength ────────────────────────────────────────────


def test_trim_body_low_keeps_question_and_useful_para_when_no_memory():
    # Fase 8.3: guidance_strength=low SIN orientación explicada → conserva 1 útil + pregunta
    body = f"{_ORIENTATION_PARA}\n\n{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = trim_body_for_strength(body, "low", "clarification",
                                    already_explained_orientation=False)
    assert _QUESTION_PARA in result
    # _LEGAL_CONTENT_PARA es corto y útil → debe conservarse
    assert _LEGAL_CONTENT_PARA in result
    # _ORIENTATION_PARA es largo y genérico → puede o no estar (depende del orden)
    # Lo importante es que la pregunta y el contenido útil estén


def test_trim_body_low_aggressive_when_orientation_explained():
    # Fase 8.3: guidance_strength=low CON orientación ya explicada → solo pregunta
    body = f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = trim_body_for_strength(body, "low", "clarification",
                                    already_explained_orientation=True)
    assert _QUESTION_PARA in result
    assert _LEGAL_CONTENT_PARA not in result


def test_trim_body_medium_keeps_max_2_content_plus_question():
    para1 = "Párrafo de contenido uno, información jurídica relevante."
    para2 = "Párrafo de contenido dos, más información jurídica relevante."
    para3 = "Párrafo de contenido tres, información adicional de menor relevancia."
    question = "¿Tiene ingresos documentados el otro progenitor?"
    body = f"{para1}\n\n{para2}\n\n{para3}\n\n{question}"
    result = trim_body_for_strength(body, "medium", "clarification")
    assert question in result
    assert para1 in result
    assert para2 not in result
    assert para3 not in result


def test_trim_body_medium_clarification_keeps_only_one_content_para():
    para1 = "Parrafo de contenido uno, informacion juridica relevante."
    para2 = "Parrafo de contenido dos, mas informacion juridica relevante."
    question = "¿Tiene ingresos documentados el otro progenitor?"
    body = f"{para1}\n\n{para2}\n\n{question}"
    result = trim_body_for_strength(
        body,
        "medium",
        "clarification",
        output_mode="estructuracion",
    )
    assert para1 in result
    assert para2 not in result
    assert question in result


def test_trim_body_high_does_not_trim():
    body = f"{_ORIENTATION_PARA}\n\n{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = trim_body_for_strength(body, "high", "clarification")
    assert result == body


def test_trim_body_initial_does_not_trim_regardless_of_strength():
    body = f"{_ORIENTATION_PARA}\n\n{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    assert trim_body_for_strength(body, "low", "initial") == body


def test_trim_body_low_no_question_falls_back_to_full_body():
    body = f"{_ORIENTATION_PARA}\n\n{_LEGAL_CONTENT_PARA}"
    result = trim_body_for_strength(body, "low", "clarification")
    # Sin párrafos con pregunta, no recorta
    assert _LEGAL_CONTENT_PARA in result


# ─── Tests: build_question_intro ─────────────────────────────────────────────


def test_build_question_intro_quantify_low_completeness():
    policy = _policy(action="ask", dominant_missing_purpose="quantify")
    intro = build_question_intro(policy, _state(case_completeness="low"))
    assert intro
    assert "montos" in intro.lower() or "valores" in intro.lower() or "orientarte" in intro.lower()


def test_build_question_intro_quantify_medium_completeness():
    policy = _policy(action="ask", dominant_missing_purpose="quantify")
    intro = build_question_intro(policy, _state(case_completeness="medium"))
    assert intro
    assert "ajustar" in intro.lower() or "contexto" in intro.lower()


def test_build_question_intro_enable_purpose():
    policy = _policy(action="ask", dominant_missing_purpose="enable")
    intro = build_question_intro(policy, _state())
    assert intro
    assert "clave" in intro.lower() or "avanzar" in intro.lower()


def test_build_question_intro_identify_purpose():
    policy = _policy(action="ask", dominant_missing_purpose="identify")
    intro = build_question_intro(policy, _state())
    assert intro
    assert "identificar" in intro.lower() or "situación" in intro.lower()


def test_build_question_intro_empty_when_action_advise():
    policy = _policy(action="advise", dominant_missing_purpose="quantify")
    intro = build_question_intro(policy, _state())
    assert intro == ""


def test_build_question_intro_empty_when_no_dominant_key():
    policy = _policy(action="ask", dominant_missing_key="")
    intro = build_question_intro(policy, _state())
    assert intro == ""


def test_build_body_bridge_aparece_en_followup_con_contexto():
    bridge = build_body_bridge(
        "guided_followup",
        _policy(action="hybrid"),
        _state(turn_count=3, case_completeness="medium"),
    )
    assert bridge
    assert "con eso" in bridge.lower() or "a partir de" in bridge.lower()


# ─── Tests: compose — casos principales ──────────────────────────────────────


# a. Primer turno → initial, pass-through
def test_compose_initial_turn_passthrough():
    response = f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = compose(
        conversation_state=_state(turn_count=1),
        dialogue_policy=_policy(),
        response_text=response,
    )
    assert result["turn_type"] == "initial"
    assert result["lead_text"] == ""
    assert result["composed_response_text"] == response
    assert result["composition_strategy"] == "passthrough_initial"
    assert result["repetition_reduced"] is False


# b. Turno siguiente → followup, lead_text prepended
def test_compose_followup_prepends_lead_text():
    response = f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=2),
        dialogue_policy=_policy(action="ask"),
        response_text=response,
    )
    assert result["turn_type"] == "clarification"
    assert result["lead_text"] != ""
    # El lead_text debe aparecer al principio de composed_response_text
    assert result["composed_response_text"].startswith(result["lead_text"])


# c. guidance_strength=low → cuerpo reducido a solo pregunta
def test_compose_guidance_low_reduces_to_question():
    response = f"{_ORIENTATION_PARA}\n\n{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=1),
        dialogue_policy=_policy(action="ask", guidance_strength="low"),
        response_text=response,
    )
    assert _QUESTION_PARA in result["composed_response_text"]
    # El body de orientación no debe estar en la respuesta compuesta
    assert _ORIENTATION_PARA not in result["composed_response_text"]


# d. guidance_strength=medium → respuesta equilibrada
def test_compose_guidance_medium_balanced_output():
    para1 = "Contenido jurídico relevante uno, información importante para el caso."
    para2 = "Contenido jurídico relevante dos, continuación del análisis."
    para3 = "Contenido jurídico adicional tres, información de menor relevancia general."
    question = "¿Tiene el otro progenitor ingresos documentados actualmente?"
    response = f"{para1}\n\n{para2}\n\n{para3}\n\n{question}"
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=2),
        dialogue_policy=_policy(action="ask", guidance_strength="medium"),
        response_text=response,
    )
    composed = result["composed_response_text"]
    assert question in composed
    assert para1 in composed
    assert para2 not in composed
    # para3 debe haber sido recortado
    assert para3 not in composed


# e. guidance_strength=high → sin recorte
def test_compose_guidance_high_no_trimming():
    response = f"{_ORIENTATION_PARA}\n\n{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=2),
        dialogue_policy=_policy(action="ask", guidance_strength="high"),
        response_text=response,
    )
    assert _LEGAL_CONTENT_PARA in result["composed_response_text"]
    assert _QUESTION_PARA in result["composed_response_text"]


# f. Reduce repetición de párrafo de orientación genérica en turno > 1
def test_compose_reduces_orientation_repetition():
    response = f"{_ORIENTATION_PARA}\n\n{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=2),
        dialogue_policy=_policy(action="ask", guidance_strength="high"),
        response_text=response,
    )
    assert result["repetition_reduced"] is True
    assert _ORIENTATION_PARA not in result["composed_response_text"]
    # El contenido legal debe mantenerse
    assert _LEGAL_CONTENT_PARA in result["composed_response_text"]


# g. Integra question_intro como puente antes de la pregunta
def test_compose_integrates_question_intro_as_bridge():
    response = f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=2, case_completeness="medium"),
        dialogue_policy=_policy(
            action="ask",
            guidance_strength="medium",
            dominant_missing_purpose="quantify",
        ),
        response_text=response,
    )
    assert result["question_intro"] != ""
    composed = result["composed_response_text"]
    # El question_intro debe aparecer en la respuesta compuesta
    assert result["question_intro"] in composed
    # La pregunta debe aparecer después del intro
    intro_pos = composed.index(result["question_intro"])
    question_pos = composed.index("?")
    assert intro_pos < question_pos


def test_compose_humanizes_followup_prompt_without_question_mark():
    response = (
        "Ya hay una base para avanzar con lo principal.\n\n"
        "existen hijos menores o con capacidad restringida y que cuestiones de cuidado, comunicacion y alimentos deben regularse"
    )
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=1, case_completeness="medium"),
        dialogue_policy=_policy(action="ask", guidance_strength="medium", dominant_missing_purpose="identify"),
        response_text=response,
    )

    composed = result["composed_response_text"]
    assert "¿existen hijos menores" in composed.lower()
    assert result["question_intro"] in composed


def test_compose_agrega_body_bridge_entre_apertura_y_contenido():
    response = f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}"
    result = compose(
        conversation_state=_state(turn_count=3, known_fact_count=2, case_completeness="medium"),
        dialogue_policy=_policy(
            action="hybrid",
            guidance_strength="medium",
            dominant_missing_purpose="quantify",
        ),
        response_text=response,
    )
    composed = result["composed_response_text"]
    assert result["body_bridge"]
    assert result["body_bridge"] in composed
    assert composed.index(result["body_bridge"]) < composed.index(_LEGAL_CONTENT_PARA)


def test_compose_execution_question_stays_light_before_followup():
    para1 = "Primero conviene reunir la documentacion minima para que el paso siguiente no salga incompleto."
    para2 = "Tambien puede servir ordenar gastos y recibos para sostener mejor el reclamo."
    question = "¿Tenes ya los recibos o comprobantes principales?"
    response = f"{para1}\n\n{para2}\n\n{question}"
    result = compose(
        conversation_state=_state(turn_count=3, known_fact_count=3, case_completeness="high"),
        dialogue_policy=_policy(action="hybrid", guidance_strength="medium", dominant_missing_purpose="enable"),
        response_text=response,
        pipeline_payload={"output_mode": "ejecucion"},
    )
    composed = result["composed_response_text"]
    assert para1 in composed
    assert para2 not in composed
    assert question in composed


# Caso adicional: con solo un párrafo no recorta orientation (protección)
def test_compose_does_not_strip_only_paragraph():
    response = _ORIENTATION_PARA  # solo un párrafo
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=1),
        dialogue_policy=_policy(action="ask", guidance_strength="high"),
        response_text=response,
    )
    # No debe quedar vacío
    assert result["composed_response_text"].strip() != ""
    assert result["repetition_reduced"] is False


# Caso: inputs None → no rompe
def test_compose_handles_none_state_and_policy():
    response = _LEGAL_CONTENT_PARA
    result = compose(
        conversation_state=None,
        dialogue_policy=None,
        response_text=response,
    )
    assert result["turn_type"] == "initial"
    assert result["composed_response_text"] == response


# Caso: response_text vacío → no rompe
def test_compose_handles_empty_response_text():
    result = compose(
        conversation_state=_state(turn_count=2),
        dialogue_policy=_policy(),
        response_text="",
    )
    assert isinstance(result["composed_response_text"], str)


# ─── Tests de integración: ResponsePostprocessor + composer ──────────────────


def test_postprocessor_uses_composed_response_text_when_available():
    """
    i. Si el composer produce composed_response_text, el FinalOutput debe usarlo.
    Verifica que la respuesta final difiera del texto base cuando hay lead_text.
    """
    import pytest
    pytest.importorskip("sqlalchemy")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.database import Base
    import app.models.conversation_state_snapshot  # noqa: F401
    from legal_engine.orchestrator_schema import RetrievalBundle, StrategyBundle
    from legal_engine.response_postprocessor import ResponsePostprocessor

    engine = create_engine("sqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Turno 1: establecemos el estado
        processor = ResponsePostprocessor()
        normalized_input_t1 = {
            "query": "Quiero reclamar alimentos",
            "facts": {"hay_hijos": True},
            "metadata": {"conversation_id": "conv-composer-test"},
        }
        pipeline_payload_t1 = {
            "pipeline_version": "beta-v1",
            "facts": {"hay_hijos": True},
            "reasoning": {"short_answer": "Hay base para orientar el reclamo."},
            "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
            "case_profile": {
                "case_domain": "alimentos",
                "missing_critical_facts": ["ingresos_otro_progenitor"],
            },
            "case_strategy": {"strategy_mode": "conservadora"},
            "legal_decision": {
                "dominant_factor": "norma",
                "confidence_score": 0.7,
                "execution_readiness": "requiere_impulso_procesal",
            },
            "procedural_case_state": {"blocking_factor": "none"},
            "conversational": {"should_ask_first": False},
        }
        processor.postprocess(
            request_id="req-t1",
            normalized_input=normalized_input_t1,
            pipeline_payload=pipeline_payload_t1,
            retrieval=RetrievalBundle(source_mode="normative_only"),
            strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
            db=db,
        )

        # Turno 2: ahora el composer debe activarse (turn_count=2)
        normalized_input_t2 = {
            "query": "El otro progenitor trabaja en relación de dependencia",
            "facts": {"ingresos_tipo": "relacion_dependencia"},
            "metadata": {"conversation_id": "conv-composer-test"},
        }
        pipeline_payload_t2 = {
            "pipeline_version": "beta-v1",
            "facts": {"ingresos_tipo": "relacion_dependencia"},
            "reasoning": {"short_answer": "Hay base para orientar el reclamo."},
            "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
            "case_profile": {
                "case_domain": "alimentos",
                "missing_critical_facts": ["ingresos_otro_progenitor"],
            },
            "case_strategy": {"strategy_mode": "conservadora"},
            "legal_decision": {
                "dominant_factor": "norma",
                "confidence_score": 0.7,
                "execution_readiness": "requiere_impulso_procesal",
            },
            "procedural_case_state": {"blocking_factor": "none"},
            "conversational": {
                "should_ask_first": True,
                "guided_response": (
                    "Hay base para orientar el reclamo.\n\n"
                    "¿El otro progenitor está aportando algo actualmente?"
                ),
            },
        }
        result_t2 = processor.postprocess(
            request_id="req-t2",
            normalized_input=normalized_input_t2,
            pipeline_payload=pipeline_payload_t2,
            retrieval=RetrievalBundle(source_mode="normative_only"),
            strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
            db=db,
        )

        # El composer debe haberse ejecutado
        assert "composer_output" in result_t2.api_payload
        composer_out = result_t2.api_payload["composer_output"]
        assert composer_out["turn_type"] != "initial"
        assert composer_out["composed_response_text"] != ""
        # La respuesta final debe conservar la base compuesta, aunque el
        # postprocessor pueda completar el cierre estrategico despues.
        assert result_t2.response_text.startswith(composer_out["composed_response_text"])

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_postprocessor_composer_failure_does_not_break_response(monkeypatch):
    """
    h. Si el composer falla, la respuesta base no se rompe.
    """
    import pytest
    pytest.importorskip("sqlalchemy")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.database import Base
    import app.models.conversation_state_snapshot  # noqa: F401
    from legal_engine.orchestrator_schema import RetrievalBundle, StrategyBundle
    from legal_engine.response_postprocessor import ResponsePostprocessor
    import legal_engine.response_postprocessor as postprocessor_module

    # Simular fallo del módulo composer
    import app.services.conversation_composer_service as composer_module

    def _raise(*args, **kwargs):
        raise RuntimeError("composer exploded")

    monkeypatch.setattr(composer_module, "compose", _raise)

    engine = create_engine("sqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        processor = ResponsePostprocessor()
        normalized_input = {
            "query": "Quiero reclamar alimentos",
            "facts": {"hay_hijos": True},
            "metadata": {"conversation_id": "conv-composer-fail"},
        }
        pipeline_payload = {
            "pipeline_version": "beta-v1",
            "facts": {"hay_hijos": True},
            "reasoning": {"short_answer": "Respuesta base sin composer."},
            "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
            "case_profile": {
                "case_domain": "alimentos",
                "missing_critical_facts": ["ingresos_otro_progenitor"],
            },
            "case_strategy": {"strategy_mode": "conservadora"},
            "legal_decision": {"dominant_factor": "norma", "confidence_score": 0.7},
            "procedural_case_state": {"blocking_factor": "none"},
            "conversational": {"should_ask_first": False},
        }

        # Primer turno para tener estado
        processor.postprocess(
            request_id="req-fail-t1",
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            retrieval=RetrievalBundle(source_mode="normative_only"),
            strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
            db=db,
        )

        # Segundo turno — el composer falla
        normalized_input["metadata"]["conversation_id"] = "conv-composer-fail"
        result = processor.postprocess(
            request_id="req-fail-t2",
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            retrieval=RetrievalBundle(source_mode="normative_only"),
            strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
            db=db,
        )

        # La respuesta debe seguir siendo util aunque el composer falle.
        assert result.response_text
        assert len(result.response_text) > 20
        # No debe haber composer_output en el payload
        assert "composer_output" not in result.api_payload

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ─── Tests Fase 8.3: memory-aware composition ────────────────────────────────


# f2. guidance_strength=low conserva 1 párrafo útil cuando orientación no fue explicada
def test_compose_guidance_low_keeps_useful_para_when_orientation_not_explained():
    # Párrafo corto y específico (no es orientación genérica)
    useful_para = "La cuota alimentaria se calcula sobre los ingresos netos."
    question = "¿Tiene el otro progenitor ingresos documentados?"
    response = f"{_ORIENTATION_PARA}\n\n{useful_para}\n\n{question}"

    # Sin conversation_memory → orientacion_base no fue explicada
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=1),
        dialogue_policy=_policy(action="ask", guidance_strength="low"),
        response_text=response,
    )
    composed = result["composed_response_text"]
    # La pregunta debe estar
    assert question in composed
    # El párrafo útil (corto, específico) debe conservarse
    assert useful_para in composed
    # La orientación genérica debe haberse eliminado
    assert _ORIENTATION_PARA not in composed


# g2. trim más agresivo cuando orientacion_base ya fue explicada
def test_compose_guidance_low_aggressive_trim_when_orientation_explained():
    useful_para = "La cuota alimentaria se calcula sobre los ingresos netos."
    question = "¿Tiene el otro progenitor ingresos documentados?"
    response = f"{useful_para}\n\n{question}"

    # Inyectar conversation_memory con orientacion_base ya explicada
    state_with_memory = _state(turn_count=2, known_fact_count=1)
    state_with_memory["conversation_memory"] = {
        "explained_topics": ["orientacion_base"],
        "used_lead_types": [],
        "asked_missing_keys_history": [],
    }

    result = compose(
        conversation_state=state_with_memory,
        dialogue_policy=_policy(action="ask", guidance_strength="low"),
        response_text=response,
    )
    composed = result["composed_response_text"]
    # Con orientación ya explicada, trim agresivo: solo pregunta (+ lead)
    assert question in composed
    # El párrafo de contenido NO debe estar (trim agresivo)
    assert useful_para not in composed


# h2. lead_text varía cuando el mismo tipo se usó >= LEAD_VARY_WINDOW veces
def test_resolve_lead_text_varies_when_repeated():
    from app.services.conversation_memory_service import LEAD_VARY_WINDOW

    # Construir memoria con LEAD_VARY_WINDOW usos del tipo "clarification"
    memory_with_repeats = {
        "used_lead_types": ["clarification"] * LEAD_VARY_WINDOW,
        "explained_topics": [],
        "asked_missing_keys_history": [],
    }
    state = _state(turn_count=2, known_fact_count=2)
    state["conversation_memory"] = memory_with_repeats

    result = compose(
        conversation_state=state,
        dialogue_policy=_policy(action="ask", guidance_strength="medium"),
        response_text=f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}",
    )
    lead_with_variation = result["lead_text"]

    # Sin memoria (sin repetición)
    result_no_memory = compose(
        conversation_state=_state(turn_count=2, known_fact_count=2),
        dialogue_policy=_policy(action="ask", guidance_strength="medium"),
        response_text=f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}",
    )
    lead_default = result_no_memory["lead_text"]

    # Las dos aperturas deben ser distintas
    assert lead_with_variation != lead_default
    # Ambas deben ser no vacías y sustanciales
    assert len(lead_with_variation) > 10
    assert len(lead_default) > 10


# h3. lead_text NO varía cuando el tipo se usó < LEAD_VARY_WINDOW veces
def test_resolve_lead_text_does_not_vary_when_used_once():
    from app.services.conversation_memory_service import LEAD_VARY_WINDOW

    # Solo 1 uso (< LEAD_VARY_WINDOW)
    memory_one_use = {
        "used_lead_types": ["clarification"] * (LEAD_VARY_WINDOW - 1),
        "explained_topics": [],
        "asked_missing_keys_history": [],
    }
    state = _state(turn_count=2, known_fact_count=2)
    state["conversation_memory"] = memory_one_use

    result = compose(
        conversation_state=state,
        dialogue_policy=_policy(action="ask", guidance_strength="medium"),
        response_text=f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}",
    )
    lead_not_varied = result["lead_text"]

    result_no_memory = compose(
        conversation_state=_state(turn_count=2, known_fact_count=2),
        dialogue_policy=_policy(action="ask", guidance_strength="medium"),
        response_text=f"{_LEGAL_CONTENT_PARA}\n\n{_QUESTION_PARA}",
    )
    lead_default = result_no_memory["lead_text"]

    # Con menos usos que el umbral, no debe variar
    assert lead_not_varied == lead_default


# j2. estimate_repetition más agresivo con already_explained_orientation=True
def test_estimate_repetition_more_aggressive_with_orientation_explained():
    from app.services.conversation_composer_service import (
        _MIN_ORIENTATION_LEN,
        estimate_repetition,
    )

    # Párrafo que supera MIN//2 pero NO supera MIN completo ni tiene 2 keywords.
    # Por eso sin flag: False. Con flag: True.
    # ~46 chars, solo 1 keyword → no pasa criterio estándar
    short_para = "En base a la normativa vigente, hay derechos aplicables."
    assert _MIN_ORIENTATION_LEN // 2 < len(short_para) < _MIN_ORIENTATION_LEN

    result_with_flag = estimate_repetition(short_para, turn_count=2,
                                           already_explained_orientation=True)
    result_without_flag = estimate_repetition(short_para, turn_count=2,
                                              already_explained_orientation=False)

    assert result_with_flag is True
    assert result_without_flag is False


# k2. conversation_memory se persiste en api_payload tras turno completo
def test_conversation_memory_persisted_in_api_payload():
    """La api_payload debe incluir conversation_memory actualizada tras el turno."""
    import pytest
    pytest.importorskip("sqlalchemy")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    import app.models.conversation_state_snapshot  # noqa: F401
    from legal_engine.orchestrator_schema import RetrievalBundle, StrategyBundle
    from legal_engine.response_postprocessor import ResponsePostprocessor

    engine = create_engine("sqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        processor = ResponsePostprocessor()
        normalized_input = {
            "query": "Quiero reclamar alimentos",
            "facts": {"hay_hijos": True},
            "metadata": {"conversation_id": "conv-mem-persist"},
        }
        pipeline_payload = {
            "pipeline_version": "beta-v1",
            "facts": {"hay_hijos": True},
            "reasoning": {"short_answer": "Hay base para orientar."},
            "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
            "case_profile": {
                "case_domain": "alimentos",
                "missing_critical_facts": ["ingresos_otro_progenitor"],
            },
            "case_strategy": {"strategy_mode": "conservadora"},
            "legal_decision": {"dominant_factor": "norma", "confidence_score": 0.7},
            "procedural_case_state": {"blocking_factor": "none"},
            "conversational": {"should_ask_first": False},
        }

        result = processor.postprocess(
            request_id="req-mem-t1",
            normalized_input=normalized_input,
            pipeline_payload=pipeline_payload,
            retrieval=RetrievalBundle(source_mode="normative_only"),
            strategy=StrategyBundle(strategy_mode="conservadora", confidence_score=0.7),
            db=db,
        )

        # La api_payload debe tener conversation_memory actualizado tras el turno
        assert "conversation_state" in result.api_payload
        conv_state = result.api_payload["conversation_state"]
        assert "conversation_memory" in conv_state
        memory = conv_state["conversation_memory"]

        # Debe tener last_dialogue_action registrado
        assert "last_dialogue_action" in memory
        assert isinstance(memory["asked_missing_keys_history"], list)
        assert isinstance(memory["used_lead_types"], list)

    finally:
        db.close()


def test_compose_action_first_suppresses_generic_opening():
    result = compose(
        conversation_state=_state(turn_count=2, known_fact_count=2, case_completeness="medium"),
        dialogue_policy=_policy(action="hybrid", guidance_strength="medium"),
        response_text="Para avanzar de forma concreta, podes hacer esto:\n1. Presentar escrito.",
        pipeline_payload={
            "output_mode": "ejecucion",
            "strategy_composition_profile": {
                "opening_style": "none",
                "allow_followup": False,
                "prioritize_action": True,
                "content_density": "guided",
            },
            "strategy_language_profile": {
                "selected_opening": "",
                "selected_bridge": "Anda por esto:",
                "selected_followup_intro": "",
            },
        },
    )

    assert result["lead_text"] == ""
    assert result["body_bridge"] == ""
    assert "Con lo que me cont" not in result["composed_response_text"]


def test_compose_orient_with_prudence_uses_prudent_language_profile():
    result = compose(
        conversation_state=_state(turn_count=3, known_fact_count=2, case_completeness="medium"),
        dialogue_policy=_policy(action="hybrid", guidance_strength="medium"),
        response_text="Hoy conviene mirar esto con cuidado.\n\n¿Tiene recibos de sueldo?",
        pipeline_payload={
            "output_mode": "orientacion_inicial",
            "strategy_composition_profile": {
                "opening_style": "guided",
                "allow_followup": True,
                "prioritize_action": False,
                "content_density": "guided",
            },
            "strategy_language_profile": {
                "selected_opening": "Con esta base ya te puedo orientar con prudencia.",
                "selected_bridge": "Hoy conviene mirarlo asi:",
                "selected_followup_intro": "Si queres cerrar mejor este punto, me ayudaria saber:",
            },
        },
    )

    assert result["lead_text"] == "Con esta base ya te puedo orientar con prudencia."
    assert result["question_intro"] == "Si queres cerrar mejor este punto, me ayudaria saber:"

# ─── Tests: FASE 12.7 — consistency_policy integration ───────────────────────


def _base_compose_kwargs(
    *,
    turn_count: int = 3,
    case_completeness: str = "medium",
    action: str = "hybrid",
    response_text: str = "",
    strategy_mode: str = "orient_with_prudence",
    output_mode: str = "orientacion_inicial",
) -> dict:
    return {
        "conversation_state": _state(turn_count=turn_count, case_completeness=case_completeness),
        "dialogue_policy": _policy(action=action),
        "response_text": response_text or f"Orientacion del caso.\n\n{_QUESTION_PARA}",
        "pipeline_payload": {
            "output_mode": output_mode,
            "strategy_composition_profile": {
                "strategy_mode": strategy_mode,
                "opening_style": "guided",
                "allow_followup": True,
                "prioritize_action": False,
                "content_density": "guided",
            },
            "strategy_language_profile": {
                "selected_opening": "Con esta base ya te puedo orientar.",
                "selected_bridge": "Lo que conviene mirar ahora:",
                "selected_followup_intro": "Para cerrar esto, necesito saber:",
            },
        },
    }


def test_consistency_suppress_lead_removes_lead_text():
    result = compose(
        **_base_compose_kwargs(turn_count=3, case_completeness="medium"),
        consistency_policy={"suppress_lead": True},
    )
    assert result["lead_text"] == ""


def test_consistency_suppress_body_bridge_removes_bridge():
    result = compose(
        **_base_compose_kwargs(turn_count=3, case_completeness="medium"),
        consistency_policy={"suppress_body_bridge": True},
    )
    assert result["body_bridge"] == ""


def test_consistency_suppress_question_intro_removes_intro():
    result = compose(
        **_base_compose_kwargs(
            action="ask",
            response_text="Algo relevante.\n\n" + _QUESTION_PARA,
        ),
        consistency_policy={"suppress_question_intro": True},
    )
    assert result["question_intro"] == ""


def test_consistency_lead_type_whitelist_empty_removes_lead():
    result = compose(
        **_base_compose_kwargs(turn_count=3, case_completeness="medium"),
        consistency_policy={"lead_type_whitelist": []},
    )
    assert result["lead_text"] == ""


def test_consistency_lead_type_whitelist_filters_incompatible_type():
    result = compose(
        conversation_state=_state(turn_count=3, case_completeness="medium"),
        dialogue_policy=_policy(action="hybrid"),
        response_text="Orientacion.\n\n" + _QUESTION_PARA,
        pipeline_payload={
            "output_mode": "orientacion_inicial",
            "strategy_composition_profile": {
                "opening_style": "guided",
                "allow_followup": True,
                "content_density": "guided",
            },
            "strategy_language_profile": {
                "selected_opening": "Con esta base ya te puedo orientar.",
            },
        },
        consistency_policy={"lead_type_whitelist": ["clarification"]},
    )
    assert result["lead_text"] == ""


def test_consistency_max_body_paragraphs_limits_content():
    long_body = (
        "Primer punto de contenido con suficiente texto para ser un parrafo.\n\n"
        "Segundo punto de contenido con suficiente texto.\n\n"
        "Tercer punto de contenido que deberia ser cortado.\n\n"
        + _QUESTION_PARA
    )
    result = compose(
        conversation_state=_state(turn_count=3, case_completeness="medium"),
        dialogue_policy=_policy(action="ask"),
        response_text=long_body,
        pipeline_payload={
            "output_mode": "orientacion_inicial",
            "strategy_composition_profile": {
                "opening_style": "minimal",
                "allow_followup": True,
                "content_density": "guided",
            },
            "strategy_language_profile": {},
        },
        consistency_policy={"max_body_paragraphs": 1},
    )
    body = result["body_text"]
    body_paras = [p for p in body.split("\n\n") if p.strip() and "?" not in p]
    assert len(body_paras) <= 1, f"body_text tiene {len(body_paras)} parrafos de contenido, max=1"


def test_consistency_none_policy_behaves_like_no_policy():
    kwargs = _base_compose_kwargs(turn_count=2, action="ask")
    result_none = compose(**kwargs, consistency_policy=None)
    result_empty = compose(**kwargs, consistency_policy={})
    assert result_none["turn_type"] == result_empty["turn_type"]
    assert result_none["composition_strategy"] == result_empty["composition_strategy"]


def test_action_first_consistency_removes_lead_and_bridge():
    result = compose(
        conversation_state=_state(turn_count=4, case_completeness="medium"),
        dialogue_policy=_policy(action="advise"),
        response_text=(
            "Para avanzar de forma concreta, podes hacer esto:\n"
            "1. Presentar escrito.\n"
            "2. Reunir documentacion."
        ),
        pipeline_payload={
            "output_mode": "ejecucion",
            "strategy_composition_profile": {
                "strategy_mode": "action_first",
                "opening_style": "none",
                "allow_followup": False,
                "prioritize_action": True,
                "content_density": "guided",
            },
            "strategy_language_profile": {
                "selected_bridge": "Para avanzar de forma concreta:",
            },
        },
        consistency_policy={
            "suppress_lead": True,
            "suppress_body_bridge": True,
            "suppress_question_intro": True,
            "lead_type_whitelist": [],
        },
    )
    assert result["lead_text"] == ""
    assert result["body_bridge"] == ""


def test_close_without_more_questions_consistency_no_question_intro():
    result = compose(
        conversation_state=_state(turn_count=5, case_completeness="high"),
        dialogue_policy=_policy(action="hybrid"),
        response_text="Con lo que hay hoy, conviene avanzar asi: divorcio unilateral.",
        pipeline_payload={
            "output_mode": "orientacion_inicial",
            "strategy_composition_profile": {
                "strategy_mode": "close_without_more_questions",
                "opening_style": "minimal",
                "allow_followup": False,
                "prioritize_action": False,
                "content_density": "brief",
            },
            "strategy_language_profile": {
                "selected_opening": "Con esta base ya conviene cerrar.",
                "selected_closing": "Con esto ya podes avanzar.",
            },
        },
        consistency_policy={
            "suppress_lead": True,
            "suppress_body_bridge": True,
            "suppress_question_intro": True,
            "lead_type_whitelist": ["partial_closure"],
            "max_body_paragraphs": 2,
        },
    )
    assert result["lead_text"] == ""
    assert result["question_intro"] == ""


def test_clarify_critical_consistency_only_one_body_para():
    result = compose(
        conversation_state=_state(turn_count=3, case_completeness="low"),
        dialogue_policy=_policy(action="ask"),
        response_text=(
            "El dato clave que necesito es el vinculo procesal.\n\n"
            "Segundo punto que deberia cortarse.\n\n"
            + _QUESTION_PARA
        ),
        pipeline_payload={
            "output_mode": "orientacion_inicial",
            "strategy_composition_profile": {
                "strategy_mode": "clarify_critical",
                "opening_style": "minimal",
                "allow_followup": True,
                "content_density": "brief",
            },
            "strategy_language_profile": {
                "selected_followup_intro": "Necesito confirmar solo esto:",
            },
        },
        consistency_policy={
            "suppress_body_bridge": True,
            "max_body_paragraphs": 1,
            "lead_type_whitelist": ["clarification"],
        },
    )
    body = result["body_text"]
    content_paras = [p for p in body.split("\n\n") if p.strip() and "?" not in p]
    assert len(content_paras) <= 1
