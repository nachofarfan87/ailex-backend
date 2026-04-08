# backend/tests/test_case_confidence_service.py
from __future__ import annotations

from app.services.case_confidence_service import resolve_case_confidence


def test_caso_con_pocos_facts_y_muchos_critical_missing_da_confidence_low():
    result = resolve_case_confidence(
        known_facts={"hay_hijos": True},
        missing_facts=[
            {"key": "jurisdiccion", "importance": "critical", "impact_on_strategy": True},
            {"key": "modalidad_divorcio", "importance": "critical", "impact_on_strategy": True},
        ],
        conversation_state={},
        case_followup={"should_ask": True, "adaptive_progress_state": "advancing"},
    )

    assert result["confidence_level"] == "low"
    assert result["case_stage"] in {"insufficient", "developing"}


def test_caso_con_facts_suficientes_y_sin_critical_missing_da_confidence_media_o_alta():
    result = resolve_case_confidence(
        known_facts={
            "jurisdiccion": "Jujuy",
            "hay_hijos": True,
            "domicilio_relevante": "San Salvador de Jujuy",
            "fecha_separacion": "2024-03-10",
            "ingresos_otro_progenitor": 300000,
        },
        missing_facts=[
            {"key": "documentacion_base", "importance": "low", "impact_on_strategy": False},
        ],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
    )

    assert result["confidence_level"] in {"medium", "high"}
    assert result["completeness_score"] >= 0.5


def test_caso_blocked_y_user_cannot_answer_no_necesita_mas_preguntas():
    result = resolve_case_confidence(
        known_facts={"hay_hijos": True, "jurisdiccion": "Jujuy"},
        missing_facts=[
            {"key": "ingresos_otro_progenitor", "importance": "critical", "impact_on_strategy": True},
        ],
        conversation_state={"progress_state": "blocked", "user_cannot_answer": True},
        case_followup={"should_ask": False, "user_cannot_answer": True, "adaptive_progress_state": "blocked"},
    )

    assert result["needs_more_questions"] is False
    assert result["closure_readiness"] in {"medium", "high"}


def test_caso_stalled_pero_con_base_razonable_tiene_closure_medium_o_high():
    result = resolve_case_confidence(
        known_facts={
            "hay_hijos": True,
            "jurisdiccion": "Jujuy",
            "domicilio_relevante": "San Pedro",
            "fecha_separacion": "2024-03-10",
        },
        missing_facts=[
            {"key": "gastos_extraordinarios", "importance": "medium", "impact_on_strategy": False},
        ],
        conversation_state={"progress_state": "stalled"},
        case_followup={"should_ask": False, "adaptive_progress_state": "stalled"},
    )

    assert result["closure_readiness"] in {"medium", "high"}


def test_caso_mature_recomienda_extended():
    result = resolve_case_confidence(
        known_facts={
            "jurisdiccion": "Jujuy",
            "hay_hijos": True,
            "domicilio_relevante": "San Salvador de Jujuy",
            "fecha_separacion": "2024-03-10",
            "convivencia_actual": False,
            "ingresos_otro_progenitor": 350000,
            "documentacion_base": True,
        },
        missing_facts=[],
        conversation_state={"progress_state": "complete"},
        case_followup={"should_ask": False, "adaptive_progress_state": "complete"},
    )

    assert result["case_stage"] == "mature"
    assert result["recommended_depth"] == "extended"


def test_caso_insufficient_recomienda_minimal():
    result = resolve_case_confidence(
        known_facts={},
        missing_facts=[
            {"key": "jurisdiccion", "importance": "critical", "impact_on_strategy": True},
            {"key": "hay_hijos", "importance": "high", "impact_on_strategy": True},
        ],
        conversation_state={},
        case_followup={"should_ask": True},
    )

    assert result["case_stage"] == "insufficient"
    assert result["recommended_depth"] == "minimal"


def test_dict_de_retorno_es_compatible():
    result = resolve_case_confidence(
        known_facts={"hay_hijos": True},
        missing_facts=[],
        conversation_state={},
        case_followup=None,
    )

    assert "completeness_score" in result
    assert "confidence_score" in result
    assert "confidence_level" in result
    assert "case_stage" in result
    assert "needs_more_questions" in result
    assert "recommended_depth" in result
    assert "closure_readiness" in result
    assert "reason" in result


def test_stage_correcto_segun_senales():
    developing = resolve_case_confidence(
        known_facts={"hay_hijos": True, "jurisdiccion": "Jujuy"},
        missing_facts=[
            {"key": "modalidad_divorcio", "importance": "critical", "impact_on_strategy": True},
        ],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": True},
    )
    substantive = resolve_case_confidence(
        known_facts={
            "hay_hijos": True,
            "jurisdiccion": "Jujuy",
            "fecha_separacion": "2024-03-10",
            "domicilio_relevante": "Jujuy",
        },
        missing_facts=[
            {"key": "documentacion_base", "importance": "medium", "impact_on_strategy": False},
        ],
        conversation_state={"progress_state": "advancing"},
        case_followup={"should_ask": False},
    )

    assert developing["case_stage"] == "developing"
    assert substantive["case_stage"] in {"substantive", "mature"}
