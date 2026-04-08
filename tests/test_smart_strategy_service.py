# backend/tests/test_smart_strategy_service.py
from __future__ import annotations

from app.services.smart_strategy_service import resolve_smart_strategy


def test_critical_missing_y_posibilidad_de_avanzar_da_clarify_critical():
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True},
        missing_facts=[
            {"key": "jurisdiccion", "importance": "critical", "impact_on_strategy": True},
        ],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": True, "adaptive_progress_state": "advancing"},
        case_confidence={
            "confidence_level": "low",
            "confidence_score": 0.28,
            "case_stage": "developing",
            "needs_more_questions": True,
            "closure_readiness": "low",
            "recommended_depth": "minimal",
        },
        output_mode="estructuracion",
    )

    assert result["strategy_mode"] == "clarify_critical"
    assert result["should_prioritize_clarification"] is True


def test_blocked_y_user_cannot_answer_da_orient_with_prudence_o_close():
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True, "jurisdiccion": "Jujuy"},
        missing_facts=[
            {"key": "ingresos", "importance": "critical", "impact_on_strategy": True},
        ],
        conversation_state={"progress_state": "blocked", "user_cannot_answer": True},
        case_followup={"should_ask": False, "adaptive_progress_state": "blocked", "user_cannot_answer": True},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.51,
            "case_stage": "developing",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="estrategia",
    )

    assert result["strategy_mode"] in {"orient_with_prudence", "close_without_more_questions"}


def test_case_stage_mature_y_confidence_high_da_substantive_analysis():
    result = resolve_smart_strategy(
        known_facts={
            "jurisdiccion": "Jujuy",
            "hay_hijos": True,
            "domicilio": "Jujuy",
            "fecha_separacion": "2024-03-10",
            "ingresos": 200000,
        },
        missing_facts=[],
        conversation_state={"progress_state": "complete"},
        case_followup={"should_ask": False, "adaptive_progress_state": "complete"},
        case_confidence={
            "confidence_level": "high",
            "confidence_score": 0.89,
            "case_stage": "mature",
            "needs_more_questions": False,
            "closure_readiness": "high",
            "recommended_depth": "extended",
        },
        output_mode="estrategia",
    )

    assert result["strategy_mode"] == "substantive_analysis"
    assert result["recommended_structure"] == "extended"


def test_urgencia_real_da_action_first():
    result = resolve_smart_strategy(
        known_facts={"urgencia_medida": True, "hay_hijos": True},
        missing_facts=[],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.52,
            "case_stage": "developing",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="orientacion_inicial",
    )

    assert result["strategy_mode"] == "action_first"
    assert result["should_prioritize_action"] is True, "urgencia debe priorizar acción"


def test_output_mode_ejecucion_no_fuerza_action_first_si_no_hay_base():
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True},
        missing_facts=[
            {"key": "jurisdiccion", "importance": "critical", "impact_on_strategy": True},
        ],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": True},
        case_confidence={
            "confidence_level": "low",
            "confidence_score": 0.30,
            "case_stage": "developing",
            "needs_more_questions": True,
            "closure_readiness": "low",
            "recommended_depth": "minimal",
        },
        output_mode="ejecucion",
    )

    assert result["strategy_mode"] != "action_first"


def test_case_developing_con_base_util_da_guide_next_step():
    result = resolve_smart_strategy(
        known_facts={
            "jurisdiccion": "Jujuy",
            "hay_hijos": True,
            "domicilio": "Jujuy",
        },
        missing_facts=[
            {"key": "documentacion_base", "importance": "medium", "impact_on_strategy": False},
        ],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.58,
            "case_stage": "developing",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="estructuracion",
    )

    assert result["strategy_mode"] == "guide_next_step"


def test_guide_next_step_no_dispara_si_hay_critical_missing():
    result = resolve_smart_strategy(
        known_facts={
            "jurisdiccion": "Jujuy",
            "hay_hijos": True,
            "domicilio": "Jujuy",
        },
        missing_facts=[
            {"key": "modalidad_divorcio", "importance": "critical", "impact_on_strategy": True},
        ],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": True},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.57,
            "case_stage": "developing",
            "needs_more_questions": True,
            "closure_readiness": "low",
            "recommended_depth": "standard",
        },
        output_mode="estructuracion",
    )

    assert result["strategy_mode"] != "guide_next_step"


def test_closure_high_y_no_mas_preguntas_da_close_without_more_questions():
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True, "jurisdiccion": "Jujuy"},
        missing_facts=[],
        conversation_state={"progress_state": "complete"},
        case_followup={"should_ask": False},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.66,
            "case_stage": "substantive",
            "needs_more_questions": False,
            "closure_readiness": "high",
            "recommended_depth": "standard",
        },
        output_mode="estructuracion",
    )

    assert result["strategy_mode"] == "close_without_more_questions"
    assert result["recommended_structure"] == "brief"


def test_recommended_structure_es_coherente_con_strategy_mode():
    result = resolve_smart_strategy(
        known_facts={"urgencia_salud": True},
        missing_facts=[],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.60,
            "case_stage": "developing",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="ejecucion",
    )

    assert result["strategy_mode"] == "action_first"
    assert result["recommended_structure"] == "guided"


def test_dict_de_retorno_es_compatible():
    result = resolve_smart_strategy(
        known_facts={},
        missing_facts=[],
        conversation_state={},
        case_followup=None,
        case_confidence=None,
        output_mode=None,
    )

    assert "strategy_mode" in result
    assert "response_goal" in result
    assert "recommended_tone" in result
    assert "recommended_structure" in result
    assert "should_prioritize_action" in result
    assert "should_prioritize_clarification" in result
    assert "should_limit_analysis" in result
    assert "should_offer_next_step" in result
    assert "reason" in result


def test_case_progress_inconsistente_vuelve_estrategia_mas_prudente():
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True, "domicilio": "Jujuy"},
        missing_facts=[],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
        case_confidence={
            "confidence_level": "high",
            "confidence_score": 0.82,
            "case_stage": "substantive",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="estrategia",
        case_progress={
            "stage": "inconsistente",
            "progress_status": "blocked",
            "next_step_type": "resolve_contradiction",
            "readiness_label": "medium",
            "blocking_issues": [{"type": "contradictions"}],
            "critical_gaps": [],
        },
    )

    assert result["strategy_mode"] == "orient_with_prudence"
    assert result["recommended_tone"] == "prudente"


def test_case_progress_ejecucion_alta_favorece_accion():
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True, "domicilio": "Jujuy", "jurisdiccion": "Jujuy"},
        missing_facts=[],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.62,
            "case_stage": "developing",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="ejecucion",
        case_progress={
            "stage": "ejecucion",
            "progress_status": "ready",
            "next_step_type": "execute",
            "readiness_label": "high",
            "blocking_issues": [],
            "critical_gaps": [],
        },
    )

    assert result["strategy_mode"] == "action_first"
    assert result["should_prioritize_action"] is True


# ── Ajustes finos 13C ─────────────────────────────────────────────────────────


def test_ejecucion_con_critical_gaps_no_bloqueantes_da_tono_prudente():
    """
    AJUSTE 2: Si stage=ejecucion tiene critical_gaps pero sin bloqueadores fuertes,
    la estrategia puede ser action_first pero el tono debe bajar a 'prudente'.
    No sonar 100% cerrado cuando queda un dato sensible.
    """
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True, "domicilio": "Jujuy", "jurisdiccion": "Jujuy"},
        missing_facts=[],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.65,
            "case_stage": "developing",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="ejecucion",
        case_progress={
            "stage": "ejecucion",
            "readiness_label": "high",
            "progress_status": "ready",
            "next_step_type": "execute",
            "blocking_issues": [],
            "critical_gaps": [{"key": "ingresos_otro_progenitor", "priority": "medium"}],
            "important_gaps": [],
        },
    )

    assert result["strategy_mode"] == "action_first"
    assert result["recommended_tone"] == "prudente", (
        "Con critical_gaps no bloqueantes, el tono no debe ser 'ejecutivo'"
    )
    assert "prudencia" in result["reason"].lower() or "gap" in result["reason"].lower()


def test_ejecucion_sin_critical_gaps_da_tono_ejecutivo():
    """
    AJUSTE 2 complementario: sin critical_gaps, action_first sigue dando tono ejecutivo.
    """
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True, "domicilio": "Jujuy", "jurisdiccion": "Jujuy"},
        missing_facts=[],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.65,
            "case_stage": "developing",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="ejecucion",
        case_progress={
            "stage": "ejecucion",
            "readiness_label": "high",
            "progress_status": "ready",
            "next_step_type": "execute",
            "blocking_issues": [],
            "critical_gaps": [],
            "important_gaps": [],
        },
    )

    assert result["strategy_mode"] == "action_first"
    assert result["recommended_tone"] == "ejecutivo"


def test_respuesta_ambigua_activa_clarify_critical_si_hay_followup():
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True},
        missing_facts=[{"key": "ingresos", "importance": "critical", "impact_on_strategy": True}],
        conversation_state={"progress_state": "advancing", "response_quality": "ambiguous", "response_strategy": "clarify"},
        case_followup={"should_ask": True, "response_quality": "ambiguous", "response_strategy": "clarify"},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.45,
            "case_stage": "developing",
            "needs_more_questions": True,
            "closure_readiness": "low",
            "recommended_depth": "standard",
        },
        output_mode="estructuracion",
    )

    assert result["strategy_mode"] == "clarify_critical"


def test_respuesta_que_permite_avanzar_con_prudencia_no_fuerza_loop():
    result = resolve_smart_strategy(
        known_facts={"hay_hijos": True, "aportes_actuales": False},
        missing_facts=[{"key": "ingresos", "importance": "high", "impact_on_strategy": True}],
        conversation_state={"progress_state": "advancing", "response_strategy": "advance_with_prudence"},
        case_followup={"should_ask": False, "response_strategy": "advance_with_prudence"},
        case_confidence={
            "confidence_level": "medium",
            "confidence_score": 0.53,
            "case_stage": "developing",
            "needs_more_questions": False,
            "closure_readiness": "medium",
            "recommended_depth": "standard",
        },
        output_mode="estrategia",
    )

    assert result["strategy_mode"] == "orient_with_prudence"
