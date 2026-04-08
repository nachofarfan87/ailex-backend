# backend/tests/test_professional_judgment_service.py
from __future__ import annotations

from app.services.professional_judgment_service import build_professional_judgment


def test_professional_judgment_orienta_con_firmeza_cuando_ya_hay_base():
    judgment = build_professional_judgment(
        api_payload={
            "quick_start": "Presentar la demanda principal.",
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
                        "title": "Presentar la demanda principal.",
                        "why_it_matters": "Ya hay base suficiente para pasar a accion.",
                    }
                ]
            },
            "smart_strategy": {"strategy_mode": "action_first"},
            "case_confidence": {"confidence_level": "high", "confidence_score": 0.84},
        }
    )

    assert judgment["recommendation_stance"] == "firm_action"
    assert judgment["prudence_level"] == "low"
    assert judgment["calibration"]["calibrated_state"] == "action_ready"
    assert judgment["calibration"]["decision_intent"] == "act"
    assert judgment["calibration"]["decision_confidence_level"] == "high"
    assert judgment["calibration"]["confidence_clarity_score"] >= 70
    assert judgment["calibration"]["confidence_stability_score"] >= 70
    assert "Presentar la demanda principal" in judgment["best_next_move"]
    assert "base suficiente" in judgment["why_this_matters_now"].lower()


def test_professional_judgment_frena_y_prioriza_dato_critico_faltante():
    judgment = build_professional_judgment(
        api_payload={
            "case_progress": {
                "readiness_label": "medium",
                "progress_status": "stalled",
                "next_step_type": "ask",
                "critical_gaps": [{"key": "jurisdiccion", "label": "la jurisdiccion relevante"}],
                "important_gaps": [],
                "blocking_issues": [],
                "contradictions": [],
            },
            "case_followup": {
                "should_ask": True,
                "question": "En que jurisdiccion tramitaria esto?",
                "need_key": "hecho::jurisdiccion",
            },
            "smart_strategy": {"strategy_mode": "clarify_critical"},
        }
    )

    assert judgment["recommendation_stance"] == "clarify_before_action"
    assert judgment["prudence_level"] == "high"
    assert judgment["calibration"]["calibrated_state"] == "blocked"
    assert judgment["calibration"]["decision_intent"] == "block"
    assert judgment["calibration"]["decision_confidence_level"] == "low"
    assert any("blocked" in item or "blocking" in item for item in judgment["calibration"]["decision_trace"])
    assert "jurisdiccion relevante" in judgment["blocking_issue"].lower()
    assert "jurisdiccion relevante" in judgment["followup_why"].lower()
    assert "dato pendiente" in judgment["best_next_move"].lower()


def test_professional_judgment_detecta_factor_dominante_y_riesgo_practico():
    judgment = build_professional_judgment(
        api_payload={
            "case_progress": {
                "readiness_label": "low",
                "progress_status": "blocked",
                "next_step_type": "resolve_contradiction",
                "critical_gaps": [],
                "important_gaps": [],
                "blocking_issues": [],
                "contradictions": [
                    {"key": "domicilio_relevante", "summary": "el domicilio relevante"}
                ],
            },
            "case_followup": {
                "should_ask": True,
                "question": "Cual es el domicilio correcto?",
            },
            "smart_strategy": {"strategy_mode": "orient_with_prudence"},
        }
    )

    assert "domicilio relevante" in judgment["dominant_factor"].lower()
    assert "inconsistencia" in judgment["practical_risk"].lower()
    assert judgment["position_strength"] == "fragile"
    assert judgment["calibration"]["dominant_signal"] == "contradiction"
    assert judgment["calibration"]["dominant_signal_score"] > 0
    assert judgment["calibration"]["decision_confidence_level"] == "low"
    assert judgment["calibration"]["confidence_stability_score"] <= 35
    assert judgment["calibration"]["confidence_clarity_score"] <= 35


def test_professional_judgment_marca_urgencia_real_sin_tratarla_como_caso_limpio():
    judgment = build_professional_judgment(
        api_payload={
            "quick_start": "Pedir cuota provisoria cuanto antes.",
            "response_text": "Hay urgencia alimentaria y conviene una medida provisoria.",
            "case_progress": {
                "readiness_label": "high",
                "progress_status": "ready",
                "next_step_type": "execute",
                "critical_gaps": [],
                "important_gaps": [],
                "blocking_issues": [],
                "contradictions": [],
            },
            "smart_strategy": {"strategy_mode": "action_first"},
        }
    )

    assert judgment["recommendation_stance"] == "urgent_action"
    assert judgment["exposure_level"] == "high"
    assert judgment["calibration"]["calibrated_state"] == "action_ready"
    assert judgment["calibration"]["decision_intent"] == "act"
    assert judgment["calibration"]["decision_confidence_level"] != "high"
    assert judgment["calibration"]["confidence_stability_score"] < judgment["calibration"]["confidence_clarity_score"]
    assert "urgente" in judgment["why_this_matters_now"].lower() or "agrave" in judgment["why_this_matters_now"].lower()


def test_professional_judgment_acciona_con_prudencia_si_hay_urgencia_y_missing():
    judgment = build_professional_judgment(
        api_payload={
            "quick_start": "Pedir una medida provisoria.",
            "response_text": "Hay urgencia alimentaria actual.",
            "case_progress": {
                "readiness_label": "medium",
                "progress_status": "advancing",
                "next_step_type": "execute",
                "critical_gaps": [{"key": "ingresos", "label": "los ingresos actuales"}],
                "important_gaps": [],
                "blocking_issues": [],
                "contradictions": [],
            },
            "case_followup": {
                "should_ask": True,
                "question": "Tenes algun dato sobre los ingresos actuales?",
                "need_key": "hecho::ingresos_actuales",
            },
            "case_workspace": {
                "action_plan": [
                    {
                        "title": "Pedir una medida provisoria.",
                        "why_it_matters": "Ayuda a cubrir la urgencia mientras se completa la base.",
                    }
                ]
            },
            "smart_strategy": {"strategy_mode": "action_first"},
        }
    )

    assert judgment["calibration"]["calibrated_state"] == "guarded_action"
    assert judgment["calibration"]["decision_intent"] == "act_with_guardrails"
    assert judgment["recommendation_stance"] == "urgent_action"
    assert judgment["prudence_level"] == "medium"
    assert "resguardos" in judgment["best_next_move"].lower()
    assert "medida provisoria" in judgment["best_next_move"].lower()
    assert any("guarded action" in item for item in judgment["calibration"]["decision_trace"])


def test_professional_judgment_gobierna_best_next_move_desde_clarify():
    judgment = build_professional_judgment(
        api_payload={
            "quick_start": "Presentar la demanda principal.",
            "case_progress": {
                "readiness_label": "medium",
                "progress_status": "stalled",
                "next_step_type": "ask",
                "critical_gaps": [],
                "important_gaps": [{"key": "domicilio", "label": "el domicilio actual"}],
                "blocking_issues": [],
                "contradictions": [],
            },
            "case_followup": {
                "should_ask": True,
                "question": "Cual es el domicilio actual?",
                "need_key": "hecho::domicilio_actual",
            },
        }
    )

    assert judgment["calibration"]["decision_intent"] == "clarify"
    assert judgment["best_next_move"].lower().startswith("precisar ahora")
    assert "domicilio actual" in judgment["best_next_move"].lower()


def test_professional_judgment_recalibra_el_next_move_por_bloqueo_real():
    judgment = build_professional_judgment(
        api_payload={
            "quick_start": "Presentar la demanda principal.",
            "case_progress": {
                "readiness_label": "medium",
                "progress_status": "stalled",
                "next_step_type": "ask",
                "critical_gaps": [{"key": "vinculo", "label": "el vinculo filial acreditable"}],
                "important_gaps": [],
                "blocking_issues": [],
                "contradictions": [],
            },
            "case_followup": {
                "should_ask": True,
                "question": "Tenes la partida de nacimiento?",
                "need_key": "hecho::vinculo_filial",
            },
            "case_workspace": {
                "action_plan": [
                    {
                        "title": "Presentar la demanda principal.",
                        "why_it_matters": "Es el paso natural si la base documental ya estuviera cerrada.",
                    }
                ]
            },
            "smart_strategy": {"strategy_mode": "clarify_critical"},
        }
    )

    assert judgment["calibration"]["calibrated_state"] == "blocked"
    assert judgment["calibration"]["decision_intent"] == "block"
    assert judgment["best_next_move"].lower().startswith("cerrar primero")
    assert "vinculo filial" in judgment["best_next_move"].lower()


def test_professional_judgment_no_rompe_compatibilidad_y_agrega_calibration_enriquecida():
    judgment = build_professional_judgment(
        api_payload={
            "case_progress": {
                "readiness_label": "medium",
                "progress_status": "advancing",
                "next_step_type": "decide",
                "critical_gaps": [],
                "important_gaps": [],
                "blocking_issues": [],
                "contradictions": [],
            },
            "case_workspace": {
                "action_plan": [
                    {"title": "Ordenar la documentacion basica."}
                ]
            },
        }
    )

    assert "dominant_factor" in judgment
    assert "best_next_move" in judgment
    assert "recommendation_stance" in judgment
    assert "calibration" in judgment
    assert "decision_intent" in judgment["calibration"]
    assert "dominant_signal_score" in judgment["calibration"]
    assert "decision_confidence_score" in judgment["calibration"]
    assert "confidence_clarity_score" in judgment["calibration"]
    assert "confidence_stability_score" in judgment["calibration"]
    assert "decision_trace" in judgment["calibration"]


def test_professional_judgment_acepta_override_de_prioridad_por_dominio():
    judgment = build_professional_judgment(
        api_payload={
            "case_domain": "laboral",
            "response_text": "Hay riesgo actual de perdida del empleo y conviene actuar cuanto antes.",
            "case_progress": {
                "readiness_label": "medium",
                "progress_status": "advancing",
                "next_step_type": "execute",
                "critical_gaps": [],
                "important_gaps": [],
                "blocking_issues": [],
                "contradictions": [],
            },
            "case_workspace": {
                "action_plan": [
                    {"title": "Enviar intimacion laboral inmediata."}
                ]
            },
        }
    )

    assert judgment["calibration"]["dominant_signal"] == "urgency"
    assert judgment["calibration"]["decision_trace"]
