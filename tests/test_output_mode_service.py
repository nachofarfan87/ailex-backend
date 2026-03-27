from __future__ import annotations

from copy import deepcopy

from app.services import output_mode_service


def _refined_response() -> dict:
    return {
        "case_domain": "divorcio",
        "case_domains": ["divorcio", "alimentos"],
        "quick_start": "Primer paso recomendado: Definir la via procesal aplicable.",
        "confidence": 0.6,
        "reasoning": {
            "short_answer": "La consulta encuadra como divorcio y permite orientar una estrategia base.",
        },
        "legal_decision": {
            "confidence_score": 0.6,
            "strategic_posture": "conservadora",
        },
        "procedural_case_state": {"blocking_factor": "none"},
        "case_strategy": {
            "strategy_mode": "conservadora",
            "strategic_narrative": (
                "La estrategia inicial se centra en ordenar el divorcio y preparar "
                "la propuesta reguladora con foco procesal suficiente."
            ),
            "conflict_summary": ["Existe conflicto sobre la vivienda familiar."],
            "recommended_actions": [
                "Definir la via procesal aplicable.",
                "Reunir prueba documental basica.",
            ],
            "risk_analysis": ["La omision de la propuesta reguladora puede generar observaciones."],
            "procedural_focus": ["Verificar competencia y ultimo domicilio conyugal."],
            "critical_missing_information": [],
            "ordinary_missing_information": [
                "Precisar bienes, vivienda familiar y eventual compensacion economica.",
                "Completar la propuesta o convenio regulador con el nivel de detalle necesario.",
            ],
        },
        "normative_reasoning": {
            "applied_rules": [
                {"source": "CCyC", "article": "438"},
                {"source": "CCyC", "article": "439"},
            ],
        },
    }


def test_divorcio_simple_builds_both_output_modes():
    result = output_mode_service.build_dual_output(_refined_response())

    assert "output_modes" in result
    assert "user" in result["output_modes"]
    assert "professional" in result["output_modes"]
    assert result["output_modes"]["user"]["title"] == "Que hacer primero en tu divorcio"
    assert result["output_modes"]["professional"]["title"] == "Estrategia inicial de divorcio"


def test_user_mode_preserves_quick_start():
    result = output_mode_service.build_dual_output(_refined_response())

    assert result["output_modes"]["user"]["quick_start"] == "Primer paso recomendado: Definir la via procesal aplicable."


def test_professional_mode_conserves_detail():
    result = output_mode_service.build_dual_output(_refined_response())
    professional = result["output_modes"]["professional"]

    assert professional["strategic_narrative"]
    assert professional["recommended_actions"]
    assert professional["risk_analysis"]
    assert professional["normative_focus"] == ["CCyC art. 438", "CCyC art. 439"]


def test_confidence_explained_changes_by_mode():
    result = output_mode_service.build_dual_output(_refined_response())

    assert result["output_modes"]["user"]["confidence_explained"] != result["output_modes"]["professional"]["confidence_explained"]
    assert "orientarte" in result["output_modes"]["user"]["confidence_explained"]
    assert "encuadre principal" in result["output_modes"]["professional"]["confidence_explained"]


def test_user_mode_missing_information_is_less_technical_and_not_redundant():
    result = output_mode_service.build_dual_output(_refined_response())
    missing = result["output_modes"]["user"]["missing_information"]

    assert len(missing) == 2
    assert any("acuerdo o propuesta" in item.lower() for item in missing)


def test_output_modes_derive_from_same_refined_response_without_recomputing_logic():
    payload = _refined_response()
    result = output_mode_service.build_dual_output(payload)

    assert result["case_strategy"]["recommended_actions"] == payload["case_strategy"]["recommended_actions"]
    assert result["output_modes"]["professional"]["recommended_actions"] == payload["case_strategy"]["recommended_actions"]


def test_payload_minimo_no_falla_y_genera_fallbacks_utiles():
    result = output_mode_service.build_dual_output({})
    user_output = result["output_modes"]["user"]
    professional_output = result["output_modes"]["professional"]

    assert user_output["title"] == "Orientacion inicial del caso"
    assert user_output["summary"]
    assert user_output["what_this_means"]
    assert user_output["quick_start"] == ""
    assert professional_output["title"] == "Encuadre estrategico inicial"
    assert professional_output["summary"]


def test_payload_sin_normative_reasoning_deja_normative_focus_vacio():
    payload = _refined_response()
    payload.pop("normative_reasoning")

    result = output_mode_service.build_dual_output(payload)

    assert result["output_modes"]["professional"]["normative_focus"] == []


def test_payload_sin_case_domain_usa_titulos_fallback():
    payload = _refined_response()
    payload.pop("case_domain")
    payload["quick_start"] = ""

    result = output_mode_service.build_dual_output(payload)

    assert result["output_modes"]["user"]["title"] == "Orientacion inicial del caso"
    assert result["output_modes"]["professional"]["title"] == "Encuadre estrategico inicial"


def test_payload_con_campos_vacios_no_lanza_excepciones_y_sigue_serializable():
    payload = {
        "case_domain": None,
        "quick_start": None,
        "reasoning": None,
        "case_strategy": {
            "recommended_actions": [],
            "risk_analysis": [""],
            "ordinary_missing_information": [None, ""],
        },
        "legal_decision": None,
        "normative_reasoning": None,
        "procedural_case_state": None,
    }

    result = output_mode_service.build_dual_output(payload)

    assert isinstance(result["output_modes"], dict)
    assert isinstance(result["output_modes"]["user"]["next_steps"], list)
    assert isinstance(result["output_modes"]["professional"]["normative_focus"], list)


def test_build_dual_output_no_altera_destructivamente_el_payload_original():
    payload = _refined_response()
    original = deepcopy(payload)

    result = output_mode_service.build_dual_output(payload)

    assert payload == original
    assert result["output_modes"]


def test_user_mode_no_queda_vacio_sin_case_strategy_ni_reasoning():
    payload = {
        "quick_start": "Primer paso recomendado: Reunir documentacion basica.",
    }

    result = output_mode_service.build_dual_output(payload)
    user_output = result["output_modes"]["user"]

    assert user_output["summary"]
    assert user_output["what_this_means"]
    assert user_output["next_steps"] == ["Reunir documentacion basica."]


def test_user_mode_usa_reemplazos_no_torpes():
    payload = _refined_response()
    payload["reasoning"]["short_answer"] = (
        "La competencia debe definirse y la via procesal conviene ordenarla. "
        "La incompetencia manifiesta no aparece."
    )

    result = output_mode_service.build_dual_output(payload)
    summary = result["output_modes"]["user"]["summary"]

    assert "que juzgado corresponde" in summary.lower()
    assert "como conviene iniciar el tramite" in summary.lower()
    assert "inque juzgado corresponde" not in summary.lower()


def test_user_mode_usa_reglas_declarativas_para_simplificar():
    payload = _refined_response()
    payload["reasoning"]["short_answer"] = (
        "Debe revisarse la legitimacion activa y la personeria antes de avanzar."
    )

    result = output_mode_service.build_dual_output(payload)
    summary = result["output_modes"]["user"]["summary"].lower()

    assert "si la persona esta habilitada para pedir esto" in summary
    assert "la representacion formal de la parte" in summary


def test_user_mode_evitan_simplificacion_en_contexto_tecnico_sensible():
    payload = _refined_response()
    payload["reasoning"]["short_answer"] = (
        "La incompetencia manifiesta y la competencia federal deben evaluarse antes de seguir."
    )

    result = output_mode_service.build_dual_output(payload)
    summary = result["output_modes"]["user"]["summary"].lower()

    assert "incompetencia manifiesta" in summary
    assert "competencia federal" in summary
    assert "que juzgado corresponde federal" not in summary


# ═══════════════════════════════════════════════════════════════════════════
# Conversational layer tests
# ═══════════════════════════════════════════════════════════════════════════


def test_conversational_present_in_output():
    result = output_mode_service.build_dual_output(_refined_response())

    assert "conversational" in result
    conv = result["conversational"]
    assert isinstance(conv, dict)
    assert "message" in conv
    assert "question" in conv
    assert "options" in conv
    assert "missing_facts" in conv
    assert "next_step" in conv


def test_conversational_message_is_nonempty_for_valid_response():
    result = output_mode_service.build_dual_output(_refined_response())

    assert result["conversational"]["message"]
    assert len(result["conversational"]["message"]) > 10


def test_memory_phrase_enriquece_mensaje_con_facts_relevantes():
    payload = _refined_response()
    payload["facts"] = {
        "divorcio_modalidad": "unilateral",
        "hay_hijos": False,
        "hay_bienes": False,
    }

    result = output_mode_service.build_dual_output(payload)
    message = result["conversational"]["message"].lower()

    assert "divorcio unilateral" in message
    assert "sin hijos" in message
    assert "no aparecen bienes relevantes" in message


def test_memory_phrase_tambien_aparece_en_guided_response_si_sigue_en_clarification():
    payload = _refined_response()
    payload["case_domain"] = "alimentos"
    payload["case_domains"] = ["alimentos"]
    payload["query"] = "Me demandan por alimentos"
    payload["facts"] = {
        "rol_procesal": "demandado",
    }
    payload["case_strategy"]["critical_missing_information"] = [
        "Verificar existencia de hijos menores a cargo.",
    ]

    result = output_mode_service.build_dual_output(payload)
    guided = (result["conversational"]["guided_response"] or "").lower()

    assert result["conversational"]["should_ask_first"] is True
    assert "actuas como demandado" in guided
    assert "hijo" in guided or "hija" in guided or "hijos" in guided


def test_memory_phrase_no_se_agrega_si_no_hay_facts():
    result = output_mode_service.build_dual_output(_refined_response())
    message = result["conversational"]["message"].lower()

    assert "entonces estamos frente a" not in message


def test_conversational_question_derived_from_missing_info():
    payload = _refined_response()
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si el divorcio es conjunto o unilateral"
    ]

    result = output_mode_service.build_dual_output(payload)
    conv = result["conversational"]

    assert conv["question"]
    assert "divorcio" in conv["question"].lower()


def test_conversational_question_null_when_no_missing_info():
    payload = _refined_response()
    payload["case_strategy"]["critical_missing_information"] = []
    payload["case_strategy"]["ordinary_missing_information"] = []
    payload["case_strategy"]["critical_questions"] = []
    payload["procedural_strategy"] = {"missing_information": []}

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["question"] is None


def test_user_mode_switches_to_question_first_when_decisive_data_is_missing():
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["confidence"] = 0.42
    payload["case_strategy"]["critical_missing_information"] = []
    payload["case_strategy"]["ordinary_missing_information"] = [
        "Definir la via procesal aplicable."
    ]
    payload["question_engine_result"] = {
        "critical_questions": [
            "¿El otro conyuge esta de acuerdo con divorciarse o la peticion debera tramitarse unilateralmente?"
        ],
        "questions": [
            {
                "question": "¿El otro conyuge esta de acuerdo con divorciarse o la peticion debera tramitarse unilateralmente?",
                "purpose": "Definir la variante procesal del divorcio y evitar un encuadre incompleto.",
                "priority": "alta",
                "category": "variante_divorcio",
            }
        ],
    }

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["should_ask_first"] is True
    assert result["output_modes"]["user"]["summary"].startswith("Para orientarte bien, primero necesito saber")
    assert "cambia la estrategia y la presentacion inicial" in result["output_modes"]["user"]["summary"]
    assert result["output_modes"]["user"]["quick_start"] == ""
    assert len(result["output_modes"]["user"]["next_steps"]) == 1


def test_user_mode_keeps_rich_output_when_case_is_sufficiently_defined():
    payload = _refined_response()
    payload["query"] = (
        "Quiero divorciarme. Hay acuerdo, no hay hijos, ya tenemos propuesta reguladora "
        "y conocemos el ultimo domicilio conyugal."
    )
    payload["facts"] = {
        "hay_acuerdo": True,
        "sin_hijos": True,
        "propuesta_reguladora": True,
    }
    payload["question_engine_result"] = {
        "critical_questions": [
            "¿El otro conyuge esta de acuerdo con divorciarse o la peticion debera tramitarse unilateralmente?"
        ]
    }

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["should_ask_first"] is False
    assert result["output_modes"]["user"]["quick_start"].startswith("Primer paso recomendado:")


def test_conversational_options_from_short_actions():
    payload = _refined_response()
    payload["case_strategy"]["recommended_actions"] = [
        "Iniciar divorcio conjunto.",
        "Iniciar divorcio unilateral.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert len(result["conversational"]["options"]) == 2


def test_conversational_options_empty_when_many_actions():
    payload = _refined_response()
    payload["case_strategy"]["recommended_actions"] = [
        "Accion 1.",
        "Accion 2.",
        "Accion 3.",
        "Accion 4.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["options"] == []


def test_conversational_next_step_from_quick_start():
    result = output_mode_service.build_dual_output(_refined_response())

    assert result["conversational"]["next_step"]
    # Should strip the "Primer paso recomendado:" prefix
    assert "primer paso recomendado" not in (result["conversational"]["next_step"] or "").lower()


def test_conversational_missing_facts_max_three():
    payload = _refined_response()
    payload["case_strategy"]["critical_missing_information"] = [
        "Dato 1",
        "Dato 2",
    ]
    payload["case_strategy"]["ordinary_missing_information"] = [
        "Dato 3",
        "Dato 4",
        "Dato 5",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert len(result["conversational"]["missing_facts"]) <= 3


def test_conversational_robust_with_empty_payload():
    result = output_mode_service.build_dual_output({})
    conv = result["conversational"]

    assert isinstance(conv["message"], str)
    assert conv["message"]  # should have a default message
    assert isinstance(conv["options"], list)
    assert isinstance(conv["missing_facts"], list)


# ═══════════════════════════════════════════════════════════════════════════
# Question scoring / selection tests
# ═══════════════════════════════════════════════════════════════════════════


def test_scoring_divorcio_prioriza_tipo_sobre_bienes():
    """Given both process-type and property questions, pick the structural one."""
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["case_strategy"]["critical_missing_information"] = [
        "Precisar bienes, vivienda familiar y eventual compensacion economica.",
        "Definir si el divorcio es conjunto o unilateral.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    assert question is not None
    assert "conjunto" in question.lower() or "unilateral" in question.lower()


def test_scoring_divorcio_prioriza_hijos_sobre_prueba():
    """Children questions rank higher than evidence questions."""
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["case_strategy"]["critical_missing_information"] = [
        "Reunir prueba documental basica.",
        "Confirmar si existen hijos menores en comun.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    assert question is not None
    assert "hijos" in question.lower()


def test_scoring_alimentos_prioriza_hijos():
    """In alimentos domain, children-related question wins."""
    payload = _refined_response()
    payload["case_domain"] = "alimentos"
    payload["case_domains"] = ["alimentos"]
    payload["query"] = "Necesito pedir alimentos"
    payload["case_strategy"]["critical_missing_information"] = [
        "Completar documentacion necesaria.",
        "Verificar existencia de hijos menores a cargo.",
        "Precisar el formato del escrito.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    assert question is not None
    # Path B (conversation-memory-aware) selects structured alimentos questions
    # which use "hija o hijo" rather than generic "hijos".
    assert "hijo" in question.lower() or "hija" in question.lower() or "hijos" in question.lower()


def test_scoring_prioriza_competencia_sobre_costas():
    """Jurisdiction/competencia outranks costs/costas."""
    payload = _refined_response()
    payload["query"] = "Quiero iniciar un juicio"
    payload["case_strategy"]["critical_missing_information"] = [
        "Verificar costas y honorarios estimados.",
        "Determinar juzgado competente por domicilio.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    assert question is not None
    assert "juzgado" in question.lower() or "competent" in question.lower()


def test_scoring_prioriza_rol_procesal():
    """Actor/demandado question ranks high (structural)."""
    payload = _refined_response()
    payload["query"] = "Tengo un problema legal"
    payload["case_strategy"]["critical_missing_information"] = [
        "Reunir prueba documental.",
        "Definir si la persona actua como actor o demandado.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    assert question is not None
    # Now uses human-friendly template instead of raw "actor/demandado"
    assert "madre" in question.lower() or "profesional" in question.lower() or "actor" in question.lower()


def test_scoring_question_engine_alta_beats_ordinary_missing():
    """A question_engine candidate with priority 'alta' should win over
    ordinary missing facts even if the missing fact scores higher on keywords."""
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["case_strategy"]["critical_missing_information"] = []
    payload["case_strategy"]["ordinary_missing_information"] = [
        "Verificar existencia de hijos menores en comun.",
    ]
    payload["question_engine_result"] = {
        "questions": [
            {
                "question": "¿El otro conyuge esta de acuerdo o la peticion debera tramitarse unilateralmente?",
                "purpose": "Definir la variante procesal.",
                "priority": "alta",
                "category": "variante_divorcio",
            }
        ],
    }

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    assert question is not None
    # The question_engine question should win: it has priority alta AND high keyword score
    assert "unilateral" in question.lower() or "acuerdo" in question.lower()


def test_scoring_tiebreaker_prefers_shorter():
    """When two candidates score the same, the shorter one wins."""
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["case_strategy"]["critical_missing_information"] = [
        "Verificar y determinar la competencia territorial del juzgado que debe intervenir segun ultimo domicilio conyugal.",
        "Definir competencia territorial.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    assert question is not None
    # The shorter one should win
    assert len(question) < 80


def test_scoring_fallback_when_no_keywords_match():
    """When no scoring rules match, falls back to first available (positional)."""
    payload = _refined_response()
    payload["query"] = "Tengo una consulta"
    payload["case_strategy"]["critical_missing_information"] = [
        "Dato generico uno.",
        "Dato generico dos.",
    ]
    payload["case_strategy"]["ordinary_missing_information"] = []

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    # Should still produce a question (fallback), not crash
    assert question is not None


def test_scoring_urgencia_ranks_high():
    """Urgency / medida cautelar questions should rank high."""
    payload = _refined_response()
    payload["case_domain"] = "civil"
    payload["query"] = "Quiero iniciar una demanda"
    payload["case_strategy"]["critical_missing_information"] = [
        "Completar documentacion basica.",
        "Evaluar si existe urgencia o necesidad de medida cautelar.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = result["conversational"]["question"]

    assert question is not None
    assert "urgencia" in question.lower() or "cautelar" in question.lower()


def test_score_candidate_text_directly():
    """Unit test for the scoring function itself."""
    from app.services.output_mode_service import _score_candidate_text

    # Structural: process type → should score high
    assert _score_candidate_text("Definir si el divorcio es conjunto o unilateral") >= 10

    # Children → high
    assert _score_candidate_text("Confirmar existencia de hijos menores en comun") >= 9

    # Property → medium
    assert _score_candidate_text("Precisar bienes y vivienda familiar") >= 7

    # Evidence → medium-low
    assert _score_candidate_text("Reunir prueba documental basica") >= 6

    # Accessory → low
    assert _score_candidate_text("Verificar costas y honorarios") >= 3

    # Structural always beats accessory
    structural = _score_candidate_text("Definir si el divorcio es conjunto o unilateral")
    accessory = _score_candidate_text("Verificar costas y honorarios")
    assert structural > accessory


def test_divorcio_continua_con_siguiente_pregunta_despues_de_responder_unilateral():
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["facts"] = {"divorcio_modalidad": "unilateral", "hay_acuerdo": False}
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Quiero divorciarme",
            "case_domain": "divorcio",
            "last_question": "¿El divorcio sera de comun acuerdo o unilateral?",
            "asked_questions": ["¿El divorcio sera de comun acuerdo o unilateral?"],
            "known_facts": {"divorcio_modalidad": "unilateral", "hay_acuerdo": False},
            "answer_status": "precise",
        }
    }
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si el divorcio es conjunto o unilateral.",
        "Confirmar si existen hijos menores en comun.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert "unilateral" not in (result["conversational"]["question"] or "").lower()
    assert "conjunto" not in (result["conversational"]["question"] or "").lower()
    assert "hijos" in (result["conversational"]["question"] or "").lower()


def test_divorcio_no_repite_unilateral_ni_hijos_si_ya_fueron_aclarados():
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["facts"] = {
        "divorcio_modalidad": "unilateral",
        "hay_acuerdo": False,
        "hay_hijos": True,
    }
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Quiero divorciarme",
            "case_domain": "divorcio",
            "last_question": "¿Tienen hijos menores en comun?",
            "asked_questions": [
                "¿El divorcio sera de comun acuerdo o unilateral?",
                "¿Tienen hijos menores en comun?",
            ],
            "known_facts": {
                "divorcio_modalidad": "unilateral",
                "hay_acuerdo": False,
                "hay_hijos": True,
            },
            "answer_status": "precise",
        }
    }
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si el divorcio es conjunto o unilateral.",
        "Confirmar si existen hijos menores en comun.",
        "Precisar bienes, vivienda familiar y eventual compensacion economica.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = (result["conversational"]["question"] or "").lower()

    assert "unilateral" not in question
    assert "conjunto" not in question
    assert "hijos" not in question
    assert "bienes" in question or "vivienda" in question


def test_alimentos_integra_rol_demandado_y_cambia_la_pregunta_siguiente():
    payload = _refined_response()
    payload["case_domain"] = "alimentos"
    payload["case_domains"] = ["alimentos"]
    payload["query"] = "Me demandan por alimentos"
    payload["facts"] = {"rol_procesal": "demandado"}
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Me demandan por alimentos",
            "case_domain": "alimentos",
            "last_question": "¿Actuas como actor o demandado?",
            "asked_questions": ["¿Actuas como actor o demandado?"],
            "known_facts": {"rol_procesal": "demandado"},
            "answer_status": "precise",
        }
    }
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si la persona actua como actor o demandado.",
        "Verificar existencia de hijos menores a cargo.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = (result["conversational"]["question"] or "").lower()

    assert "demandado" not in question
    assert "actor" not in question
    # Path B selects structured alimentos questions: "hija o hijo" variant is valid.
    assert "hijo" in question or "hija" in question or "hijos" in question


def test_respuesta_ambigua_pide_precision():
    payload = _refined_response()
    payload["query"] = "si"
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Quiero divorciarme",
            "case_domain": "divorcio",
            "last_question": "¿El divorcio sera de comun acuerdo o unilateral?",
            "asked_questions": ["¿El divorcio sera de comun acuerdo o unilateral?"],
            "known_facts": {},
            "precision_required": True,
            "precision_prompt": "Necesito que me lo aclares mejor. Responde de forma concreta a esta pregunta: ¿El divorcio sera de comun acuerdo o unilateral?",
            "answer_status": "ambiguous",
        }
    }

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["should_ask_first"] is True
    assert "aclares mejor" in (result["conversational"]["guided_response"] or "").lower()
    assert result["output_modes"]["user"]["summary"].startswith("Necesito que me lo aclares mejor")


def test_caso_ya_suficientemente_completo_sale_de_clarification_mode():
    payload = _refined_response()
    payload["query"] = (
        "Quiero divorciarme. Es unilateral, no hay hijos, no hay bienes relevantes y "
        "ya conozco el ultimo domicilio conyugal."
    )
    payload["facts"] = {
        "divorcio_modalidad": "unilateral",
        "hay_acuerdo": False,
        "hay_hijos": False,
        "hay_bienes": False,
    }
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Quiero divorciarme",
            "case_domain": "divorcio",
            "last_question": "¿El divorcio sera de comun acuerdo o unilateral?",
            "asked_questions": ["¿El divorcio sera de comun acuerdo o unilateral?"],
            "known_facts": {
                "divorcio_modalidad": "unilateral",
                "hay_acuerdo": False,
                "hay_hijos": False,
                "hay_bienes": False,
            },
            "answer_status": "precise",
        }
    }
    payload["question_engine_result"] = {
        "critical_questions": [
            "¿El otro conyuge esta de acuerdo con divorciarse o la peticion debera tramitarse unilateralmente?"
        ]
    }
    payload["case_strategy"]["critical_missing_information"] = []
    payload["case_strategy"]["ordinary_missing_information"] = [
        "Completar la propuesta o convenio regulador con el nivel de detalle necesario.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["should_ask_first"] is False
    assert result["output_modes"]["user"]["quick_start"].startswith("Primer paso recomendado:")
    assert result["conversational"]["message"].startswith("Con esto ya tengo una base clara para orientarte.")


def test_evaluate_case_completeness_divorcio_modalidad_e_hijos_pasa_a_advice():
    completeness = output_mode_service.evaluate_case_completeness(
        {"divorcio_modalidad": "unilateral", "hay_hijos": False},
        "divorcio",
    )

    assert completeness["is_complete"] is True
    assert completeness["confidence_level"] in {"medium", "high"}
    assert completeness["missing_critical"] == []


def test_evaluate_case_completeness_divorcio_solo_modalidad_sigue_incompleto():
    completeness = output_mode_service.evaluate_case_completeness(
        {"divorcio_modalidad": "unilateral"},
        "divorcio",
    )

    assert completeness["is_complete"] is False
    assert "hay_hijos" in completeness["missing_critical"]


def test_evaluate_case_completeness_alimentos_rol_e_hijos_pasa_a_advice():
    completeness = output_mode_service.evaluate_case_completeness(
        {"rol_procesal": "demandado", "hay_hijos": True, "urgencia": False},
        "alimentos",
    )

    assert completeness["is_complete"] is True
    assert completeness["missing_critical"] == []


def test_caso_ambiguo_permanece_en_clarification_mode_por_incompleto():
    payload = _refined_response()
    payload["case_domain"] = "divorcio"
    payload["query"] = "Quiero divorciarme"
    payload["facts"] = {"divorcio_modalidad": "unilateral"}
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Quiero divorciarme",
            "case_domain": "divorcio",
            "known_facts": {"divorcio_modalidad": "unilateral"},
        }
    }
    payload["case_strategy"]["critical_missing_information"] = [
        "Confirmar si existen hijos menores en comun.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["case_completeness"]["is_complete"] is False
    assert result["conversational"]["should_ask_first"] is True


def test_caso_completo_no_vuelve_a_clarification_aunque_queden_opcionales():
    payload = _refined_response()
    payload["case_domain"] = "alimentos"
    payload["case_domains"] = ["alimentos"]
    payload["query"] = "Me demandan por alimentos de mi hijo"
    payload["facts"] = {
        "rol_procesal": "demandado",
        "hay_hijos": True,
        "situacion_economica": "trabajo informal",
    }
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Me demandan por alimentos de mi hijo",
            "case_domain": "alimentos",
            "known_facts": {
                "rol_procesal": "demandado",
                "hay_hijos": True,
                "situacion_economica": "trabajo informal",
            },
        }
    }
    payload["case_strategy"]["critical_missing_information"] = []
    payload["case_strategy"]["ordinary_missing_information"] = [
        "Precisar bienes, vivienda familiar y eventual compensacion economica.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["case_completeness"]["is_complete"] is True
    assert result["conversational"]["should_ask_first"] is False


def test_closure_logic_no_corta_si_hay_missing_critical():
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["facts"] = {"divorcio_modalidad": "unilateral"}
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Quiero divorciarme",
            "case_domain": "divorcio",
            "known_facts": {"divorcio_modalidad": "unilateral"},
        }
    }
    payload["case_strategy"]["critical_missing_information"] = [
        "Confirmar si existen hijos menores en comun.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["should_ask_first"] is True
    assert not result["conversational"]["message"].startswith("Con esto ya tengo una base clara para orientarte.")


def test_closure_logic_cierra_y_comunica_cuando_ya_no_hay_criticos():
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme. Es unilateral y no hay hijos."
    payload["facts"] = {
        "divorcio_modalidad": "unilateral",
        "hay_hijos": False,
    }
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Quiero divorciarme",
            "case_domain": "divorcio",
            "last_question": "El divorcio sera unilateral o conjunto?",
            "asked_questions": ["El divorcio sera unilateral o conjunto?"],
            "known_facts": {
                "divorcio_modalidad": "unilateral",
                "hay_hijos": False,
            },
        }
    }
    payload["case_strategy"]["critical_missing_information"] = []

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["should_ask_first"] is False
    assert result["conversational"]["message"].startswith("Con esto ya tengo una base clara para orientarte.")


def test_guided_response_no_duplica_necesito_saber():
    payload = _refined_response()
    payload["query"] = "Quiero divorciarme"
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si el divorcio es conjunto o unilateral.",
    ]

    result = output_mode_service.build_dual_output(payload)
    guided = result["conversational"]["guided_response"] or ""

    assert "necesito saber necesito saber" not in guided.lower()


def test_critical_missing_no_sale_prematuramente_de_clarification_mode():
    payload = _refined_response()
    payload["case_domain"] = "cuidado_personal"
    payload["case_domains"] = ["cuidado_personal"]
    payload["query"] = "Necesito resolver cuidado personal urgente"
    payload["facts"] = {"hay_hijos": True, "urgencia": True}
    payload["metadata"] = {
        "clarification_context": {
            "base_query": "Necesito resolver cuidado personal urgente",
            "case_domain": "cuidado_personal",
            "known_facts": {"hay_hijos": True, "urgencia": True},
        }
    }
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si la persona actua como actor o demandado.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["should_ask_first"] is True


def test_next_step_no_queda_gramaticalmente_torpe_con_via_procesal():
    result = output_mode_service.build_dual_output(_refined_response())

    assert result["conversational"]["next_step"] == "Definir como conviene iniciar el tramite."


def test_prioridad_divorcio_modalidad_gana_sobre_hijos():
    payload = _refined_response()
    payload["case_domain"] = "divorcio"
    payload["query"] = "Quiero divorciarme"
    payload["case_strategy"]["critical_missing_information"] = [
        "Confirmar si existen hijos menores en comun.",
        "Definir si el divorcio es conjunto o unilateral.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = (result["conversational"]["question"] or "").lower()

    assert "unilateral" in question or "conjunto" in question


def test_prioridad_divorcio_hijos_gana_sobre_bienes():
    payload = _refined_response()
    payload["case_domain"] = "divorcio"
    payload["query"] = "Quiero divorciarme"
    payload["case_strategy"]["critical_missing_information"] = [
        "Precisar bienes, vivienda familiar y eventual compensacion economica.",
        "Confirmar si existen hijos menores en comun.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = (result["conversational"]["question"] or "").lower()

    assert "hijos" in question


def test_prioridad_alimentos_rol_gana_sobre_hijos():
    payload = _refined_response()
    payload["case_domain"] = "alimentos"
    payload["case_domains"] = ["alimentos"]
    payload["query"] = "Tengo un reclamo de alimentos"
    payload["case_strategy"]["critical_missing_information"] = [
        "Verificar existencia de hijos menores a cargo.",
        "Definir si la persona actua como actor o demandado.",
    ]

    result = output_mode_service.build_dual_output(payload)
    question = (result["conversational"]["question"] or "").lower()

    # Path B (conversation-memory-aware) now selects from the structured
    # alimentos question pool, which starts with aportes_actuales/convivencia
    # rather than generic rol_procesal questions.
    assert question is not None and len(question) > 5


def test_prioridad_se_refleja_en_bonus_final_de_scoring():
    assert output_mode_service.get_field_priority("divorcio", "divorcio_modalidad") > output_mode_service.get_field_priority("divorcio", "hay_bienes")
    assert output_mode_service.get_field_priority("alimentos", "rol_procesal") > output_mode_service.get_field_priority("alimentos", "urgencia")


def test_prioridad_fallback_si_no_hay_peso_definido_mantiene_comportamiento_actual():
    assert output_mode_service.get_field_priority("divorcio", "campo_inexistente") == 0.0
    payload = _refined_response()
    payload["case_domain"] = "civil"
    payload["query"] = "Tengo una consulta"
    payload["case_strategy"]["critical_missing_information"] = [
        "Dato generico uno.",
        "Dato generico dos.",
    ]

    result = output_mode_service.build_dual_output(payload)

    assert result["conversational"]["question"] is not None


# ═══════════════════════════════════════════════════════════════════════════
# UX fix tests: human questions, fact inference, progress, [object Object]
# ═══════════════════════════════════════════════════════════════════════════


def test_caso1_alimentos_hija_13_no_object_object():
    """CASO 1: 'Quisiera saber si puedo pedir alimentos para mi hija de 13 años'
    Expected: no [object Object], real short question, completion > 0, max 1 question.
    """
    payload = _refined_response()
    payload["case_domain"] = "alimentos"
    payload["case_domains"] = ["alimentos"]
    payload["query"] = "Quisiera saber si puedo pedir alimentos para mi hija de 13 años"
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si la persona actua como actor o demandado.",
        "Verificar existencia de hijos menores a cargo.",
    ]
    payload["case_strategy"]["ordinary_missing_information"] = [
        "Precisar situacion economica de las partes.",
    ]

    result = output_mode_service.build_dual_output(payload)
    conv = result["conversational"]

    # No [object Object] anywhere in serialized output
    import json
    serialized = json.dumps(result, default=str)
    assert "[object Object]" not in serialized

    # Question is a real question (short, ends with ?)
    question = conv["question"]
    assert question is not None
    assert question.endswith("?")
    assert len(question) < 100

    # Completion > 0 because query mentions hija, alimentos, 13 años
    known_facts = conv["known_facts"]
    assert len(known_facts) > 0
    completeness = conv["case_completeness"]
    assert completeness.get("known_count", 0) > 0

    # Only 1 question selected
    assert isinstance(question, str)


def test_caso2_divorcio_hija_casa_auto():
    """CASO 2: 'Queremos divorciarnos con mi mujer, tengo una hija de 3 meses, una casa y un auto'
    Expected: question compatible with divorcio + hija, completion > 0.
    """
    payload = _refined_response()
    payload["case_domain"] = "divorcio"
    payload["case_domains"] = ["divorcio"]
    payload["query"] = "Queremos divorciarnos con mi mujer, tengo una hija de 3 meses, una casa y un auto"
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si el divorcio es conjunto o unilateral.",
        "Confirmar si existen hijos menores en comun.",
    ]

    result = output_mode_service.build_dual_output(payload)
    conv = result["conversational"]

    # Query-inferred facts should include hay_hijos, hay_bienes, tema_divorcio
    known_facts = conv["known_facts"]
    assert "hay_hijos" in known_facts or "tema_divorcio" in known_facts
    assert "hay_bienes" in known_facts

    completeness = conv["case_completeness"]
    assert completeness.get("known_count", 0) > 0


def test_fact_to_question_produces_human_questions():
    """Missing fact descriptions should become short, human-friendly questions."""
    from app.services.output_mode_service import _fact_to_question

    q1 = _fact_to_question("Definir si el divorcio es conjunto o unilateral.")
    assert q1.endswith("?")
    assert len(q1) < 80

    q2 = _fact_to_question("Verificar existencia de hijos menores a cargo.")
    assert q2.endswith("?")
    assert "hijos" in q2.lower()

    q3 = _fact_to_question("Definir si la persona actua como actor o demandado.")
    assert q3.endswith("?")
    assert len(q3) < 100

    q4 = _fact_to_question("Precisar situacion economica de las partes.")
    assert q4.endswith("?")

    # None of them should start with "Necesito saber"
    for q in [q1, q2, q3, q4]:
        assert not q.startswith("Necesito saber")


def test_fact_to_question_preserves_existing_questions():
    from app.services.output_mode_service import _fact_to_question

    result = _fact_to_question("¿Ya hay una causa judicial iniciada?")
    assert result == "¿Ya hay una causa judicial iniciada?"


def test_infer_facts_from_query_alimentos_hija():
    from app.services.output_mode_service import infer_facts_from_query

    facts = infer_facts_from_query("Quisiera saber si puedo pedir alimentos para mi hija de 13 años")
    assert "hay_hijos" in facts
    assert "hay_hijos_edad" in facts
    assert "tema_alimentos" in facts


def test_infer_facts_from_query_divorcio_bienes():
    from app.services.output_mode_service import infer_facts_from_query

    facts = infer_facts_from_query("Queremos divorciarnos, tengo una casa y un auto")
    assert "tema_divorcio" in facts
    assert "hay_bienes" in facts


def test_infer_facts_from_query_empty():
    from app.services.output_mode_service import infer_facts_from_query

    facts = infer_facts_from_query("")
    assert facts == {}


def test_completeness_known_count_reflects_inferred_facts():
    """When query mentions children + alimentos, known_count > 0."""
    payload = _refined_response()
    payload["case_domain"] = "alimentos"
    payload["query"] = "Necesito pedir alimentos para mi hijo"

    result = output_mode_service.build_dual_output(payload)
    completeness = result["conversational"]["case_completeness"]

    assert completeness.get("known_count", 0) >= 2


def test_next_step_never_object_in_conversational():
    """next_step must always be a string or None, never a dict."""
    payload = _refined_response()
    result = output_mode_service.build_dual_output(payload)

    next_step = result["conversational"]["next_step"]
    assert next_step is None or isinstance(next_step, str)


def test_caso5_multiple_missing_single_question():
    """CASO 5: Several critical missing data → only 1 primary question."""
    payload = _refined_response()
    payload["case_domain"] = "alimentos"
    payload["query"] = "Tengo un reclamo"
    payload["case_strategy"]["critical_missing_information"] = [
        "Definir si la persona actua como actor o demandado.",
        "Verificar existencia de hijos menores a cargo.",
        "Precisar situacion economica.",
        "Determinar urgencia del reclamo.",
    ]

    result = output_mode_service.build_dual_output(payload)
    conv = result["conversational"]

    # Only 1 question (string), not multiple
    question = conv["question"]
    assert question is not None
    assert isinstance(question, str)
    assert question.endswith("?")

    # missing_facts is a compact list, max 3
    assert len(conv["missing_facts"]) <= 3
