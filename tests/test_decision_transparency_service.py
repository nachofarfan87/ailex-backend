# backend/tests/test_decision_transparency_service.py
from __future__ import annotations

from app.services.decision_transparency_service import build_decision_transparency


def test_decision_transparency_separa_trace_profesional_y_usuario():
    transparency = build_decision_transparency(
        context={
            "contradiction_label": "el domicilio relevante",
            "critical_gap_label": "la jurisdiccion",
            "followup_need": "la jurisdiccion",
            "primary_step_label": "Presentar la demanda principal.",
        },
        calibration={
            "decision_intent": "block",
            "calibrated_state": "blocked",
            "dominant_signal": "contradiction",
            "dominant_signal_score": 50,
            "dominance_level": "low",
            "decision_confidence_score": 30,
            "decision_confidence_level": "low",
            "confidence_clarity_score": 34,
            "confidence_stability_score": 22,
            "blocking_severity": "hard",
            "prudence_level": "high",
            "signal_scores": {"contradiction": 50, "urgency": 0},
            "decision_trace": ["contradiction overrides urgency"],
            "rule_trace": ["state=blocked"],
        },
        judgment={
            "dominant_factor": "Lo que mas condiciona el caso hoy es aclarar el domicilio relevante.",
            "blocking_issue": "Antes de afirmar una estrategia cerrada, conviene despejar la contradiccion sobre el domicilio relevante.",
            "why_this_matters_now": "Porque mientras siga dudoso el domicilio relevante, cualquier paso posterior puede quedar mal orientado.",
        },
    )

    assert transparency["applies"] is True
    assert transparency["technical_trace"]["decision_trace"] == ["contradiction overrides urgency"]
    assert "decision_explanation" in transparency["professional_explanation"]
    assert "user_why_this" in transparency["user_explanation"]
    assert transparency["alternatives_considered"]


def test_decision_transparency_explica_accion_con_guardrails():
    transparency = build_decision_transparency(
        context={
            "critical_gap_label": "los ingresos actuales",
            "followup_need": "los ingresos actuales",
            "primary_step_label": "Pedir una medida provisoria.",
            "followup_question": "Tenes algun dato sobre los ingresos actuales?",
        },
        calibration={
            "decision_intent": "act_with_guardrails",
            "calibrated_state": "guarded_action",
            "dominant_signal": "urgency",
            "dominant_signal_score": 95,
            "dominance_level": "high",
            "decision_confidence_score": 58,
            "decision_confidence_level": "medium",
            "confidence_clarity_score": 62,
            "confidence_stability_score": 50,
            "blocking_severity": "medium",
            "prudence_level": "medium",
            "signal_scores": {"urgency": 95, "critical_missing": 35},
            "decision_trace": ["urgency enables guarded action"],
            "rule_trace": ["intent=act_with_guardrails"],
        },
        judgment={
            "best_next_move": "Pedir una medida provisoria con resguardos sobre el punto todavia abierto.",
            "practical_risk": "El riesgo practico es perder tiempo util si no se toma una medida inmediata.",
            "why_this_matters_now": "Porque hoy conviene mover una accion concreta sin esperar completitud total.",
            "followup_why": "Esto permite cerrar los ingresos actuales, que hoy condicionan el siguiente paso.",
        },
    )

    assert transparency["professional_explanation"]["decision_explanation"]
    assert transparency["user_explanation"]["user_why_this"]
    assert any(
        item["status"] == "deferred"
        for item in transparency["alternatives_considered"]
    )


def test_decision_transparency_no_fuerza_alternativas_si_no_agregan_valor():
    transparency = build_decision_transparency(
        context={
            "important_gap_label": "un detalle secundario",
            "primary_step_label": "Ordenar la base del caso.",
        },
        calibration={
            "decision_intent": "prepare",
            "calibrated_state": "prudent",
            "dominant_signal": "base_strength",
            "decision_trace": ["default prudence applied because no stronger override was triggered"],
        },
        judgment={
            "best_next_move": "Ordenar primero la base del caso.",
            "why_this_matters_now": "Todavia conviene ordenar mejor la base antes de decidir.",
        },
    )

    assert transparency["alternatives_considered"] == []


def test_decision_transparency_explica_limite_por_followup_ambiguo():
    transparency = build_decision_transparency(
        context={
            "clarification_status": "ambiguous",
            "precision_required": True,
            "followup_question": "El otro progenitor aporta algo actualmente?",
            "followup_need": "si existe algun aporte actual",
        },
        calibration={
            "decision_intent": "clarify",
            "calibrated_state": "prudent",
            "decision_confidence_level": "low",
            "confidence_clarity_score": 42,
            "confidence_stability_score": 30,
            "decision_trace": ["important missing keeps the next move in clarification mode"],
        },
        judgment={
            "followup_why": "Esto ayuda a definir un dato que todavia cambia la orientacion.",
        },
    )

    assert transparency["technical_trace"]["clarification_status"] == "ambiguous"
    assert transparency["technical_trace"]["precision_required"] is True
    assert "todavia no alcanza" in transparency["user_explanation"]["what_limits_this"].lower()
    assert "respuesta un poco mas concreta" in transparency["user_explanation"]["what_would_change_this"].lower()


def test_decision_transparency_refleja_respuesta_insuficiente_sin_sonar_tecnica():
    transparency = build_decision_transparency(
        context={
            "clarification_status": "insufficient",
            "response_quality": "insufficient",
            "response_strategy": "reformulate_question",
            "followup_question": "¿Tenés algún dato sobre los ingresos actuales del otro progenitor?",
        },
        calibration={
            "decision_intent": "clarify",
            "calibrated_state": "prudent",
            "decision_trace": ["insufficient answer triggers reformulation"],
        },
        judgment={
            "followup_why": "Esto ayuda a definir el dato que hoy más puede cambiar la orientación.",
        },
    )

    assert transparency["technical_trace"]["response_quality"] == "insufficient"
    assert transparency["technical_trace"]["response_strategy"] == "reformulate_question"
    assert "todavia no termina de aclarar" in transparency["user_explanation"]["what_limits_this"].lower()


def test_decision_transparency_degrada_seguro_si_faltan_datos():
    transparency = build_decision_transparency()

    assert transparency["applies"] is False
    assert "technical_trace" in transparency
    assert "professional_explanation" in transparency
    assert "user_explanation" in transparency
    assert transparency["alternatives_considered"] == []
