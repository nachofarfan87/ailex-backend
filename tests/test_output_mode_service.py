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
