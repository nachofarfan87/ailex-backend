# backend/tests/test_professional_judgment_rules.py
from __future__ import annotations

import inspect

import app.services.professional_judgment_rules as professional_judgment_rules
from app.services.professional_judgment_constants import (
    ACTION_READY_SCORE_MIN,
    PRACTICAL_RISK_SCORE_HIGH,
    SIGNAL_PRIORITY_BY_DOMAIN,
    SIGNAL_PRIORITY,
    URGENCY_SCORE_HIGH,
)
from app.services.professional_judgment_rules import calibrate_judgment


def test_thresholds_y_prioridad_salen_de_constants():
    source = inspect.getsource(professional_judgment_rules)

    assert "URGENCY_SCORE_HIGH" in source
    assert "PRACTICAL_RISK_SCORE_HIGH" in source
    assert "ACTION_READY_SCORE_MIN" in source
    assert "SIGNAL_PRIORITY" in source
    assert SIGNAL_PRIORITY[0] == "contradiction"
    assert "laboral" in SIGNAL_PRIORITY_BY_DOMAIN
    assert f">= {URGENCY_SCORE_HIGH}" not in source
    assert f">= {PRACTICAL_RISK_SCORE_HIGH}" not in source
    assert f">= {ACTION_READY_SCORE_MIN}" not in source


def test_prioridad_explicita_resuelve_conflicto_a_favor_de_contradiccion():
    calibration = calibrate_judgment(
        {
            "urgency_score": 95,
            "practical_risk_score": 80,
            "contradiction_count": 1,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 0,
            "base_strength_score": 70,
            "action_ready_score": 84,
            "has_action_candidate": True,
            "followup_present": True,
            "followup_usefulness": "blocking",
            "next_step_type": "resolve_contradiction",
        }
    )

    assert calibration["dominant_signal"] == "contradiction"
    assert calibration["calibrated_state"] == "blocked"
    assert calibration["decision_intent"] == "block"


def test_calibration_firmeza_correcta_con_base_suficiente():
    calibration = calibrate_judgment(
        {
            "urgency_score": 0,
            "practical_risk_score": 20,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 0,
            "base_strength_score": 76,
            "action_ready_score": 88,
            "has_action_candidate": True,
            "followup_present": False,
            "followup_usefulness": "none",
            "next_step_type": "execute",
        }
    )

    assert calibration["calibrated_state"] == "action_ready"
    assert calibration["decision_intent"] == "act"
    assert calibration["recommendation_stance"] == "firm_action"
    assert calibration["prudence_level"] == "low"
    assert calibration["decision_confidence_level"] == "high"
    assert calibration["confidence_clarity_score"] >= calibration["confidence_stability_score"]
    assert calibration["decision_trace"]


def test_calibration_prudencia_correcta_con_base_parcial():
    calibration = calibrate_judgment(
        {
            "urgency_score": 0,
            "practical_risk_score": 30,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 1,
            "base_strength_score": 48,
            "action_ready_score": 42,
            "has_action_candidate": True,
            "followup_present": True,
            "followup_usefulness": "refinement",
            "next_step_type": "decide",
        }
    )

    assert calibration["calibrated_state"] == "prudent"
    assert calibration["decision_intent"] == "clarify"
    assert calibration["recommendation_stance"] == "clarify_before_action"
    assert calibration["blocking_severity"] == "soft"
    assert calibration["decision_confidence_level"] in {"low", "medium"}
    assert calibration["confidence_stability_score"] <= 72


def test_calibration_bloqueo_real_por_missing_decisivo():
    calibration = calibrate_judgment(
        {
            "urgency_score": 0,
            "practical_risk_score": 40,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 1,
            "important_gap_count": 0,
            "base_strength_score": 52,
            "action_ready_score": 30,
            "has_action_candidate": False,
            "followup_present": True,
            "followup_usefulness": "critical",
            "next_step_type": "ask",
        }
    )

    assert calibration["calibrated_state"] == "blocked"
    assert calibration["decision_intent"] == "block"
    assert calibration["blocking_severity"] == "hard"
    assert calibration["decision_confidence_level"] == "low"
    assert any("blocked" in item or "blocking" in item for item in calibration["decision_trace"])


def test_calibration_identifica_act_with_guardrails():
    calibration = calibrate_judgment(
        {
            "urgency_score": 95,
            "practical_risk_score": 62,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 1,
            "important_gap_count": 0,
            "base_strength_score": 58,
            "action_ready_score": 74,
            "has_action_candidate": True,
            "followup_present": True,
            "followup_usefulness": "critical",
            "next_step_type": "execute",
        }
    )

    assert calibration["calibrated_state"] == "guarded_action"
    assert calibration["decision_intent"] == "act_with_guardrails"
    assert calibration["recommendation_stance"] == "urgent_action"
    assert calibration["prudence_level"] == "medium"
    assert any("guarded action" in item for item in calibration["decision_trace"])


def test_calibration_baja_firmeza_y_confianza_con_contradiccion_relevante():
    calibration = calibrate_judgment(
        {
            "urgency_score": 0,
            "practical_risk_score": 60,
            "contradiction_count": 1,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 0,
            "base_strength_score": 70,
            "action_ready_score": 82,
            "has_action_candidate": True,
            "followup_present": True,
            "followup_usefulness": "blocking",
            "next_step_type": "resolve_contradiction",
        }
    )

    assert calibration["calibrated_state"] == "blocked"
    assert calibration["decision_intent"] == "block"
    assert calibration["dominant_signal"] == "contradiction"
    assert calibration["prudence_level"] == "high"
    assert calibration["decision_confidence_level"] == "low"
    assert calibration["confidence_stability_score"] <= 35
    assert calibration["confidence_clarity_score"] <= 35


def test_calibration_prioriza_riesgo_practico_sobre_detalle_secundario():
    calibration = calibrate_judgment(
        {
            "urgency_score": 0,
            "practical_risk_score": 78,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 2,
            "base_strength_score": 61,
            "action_ready_score": 66,
            "has_action_candidate": True,
            "followup_present": False,
            "followup_usefulness": "none",
            "next_step_type": "decide",
        }
    )

    assert calibration["calibrated_state"] == "guarded_action"
    assert calibration["decision_intent"] == "act_with_guardrails"
    assert calibration["dominant_signal"] == "practical_risk"
    assert calibration["dominant_signal_score"] == 78
    assert calibration["dominance_level"] == "medium"
    assert any("practical risk" in item for item in calibration["decision_trace"])


def test_calibration_es_estable_entre_inputs_parecidos():
    first = calibrate_judgment(
        {
            "urgency_score": 0,
            "practical_risk_score": 20,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 0,
            "base_strength_score": 73,
            "action_ready_score": 84,
            "has_action_candidate": True,
            "followup_present": False,
            "followup_usefulness": "none",
            "next_step_type": "execute",
        }
    )
    second = calibrate_judgment(
        {
            "urgency_score": 0,
            "practical_risk_score": 24,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 0,
            "base_strength_score": 72,
            "action_ready_score": 82,
            "has_action_candidate": True,
            "followup_present": False,
            "followup_usefulness": "none",
            "next_step_type": "execute",
        }
    )

    assert first["calibrated_state"] == second["calibrated_state"] == "action_ready"
    assert first["decision_intent"] == second["decision_intent"] == "act"
    assert first["recommendation_stance"] == second["recommendation_stance"] == "firm_action"


def test_calibration_degrada_seguro_si_faltan_senales():
    calibration = calibrate_judgment({})

    assert calibration["calibrated_state"] == "prudent"
    assert calibration["decision_intent"] == "prepare"
    assert calibration["recommendation_stance"] == "orient_with_prudence"
    assert calibration["actionability"] == "needs_definition"


def test_urgencia_alta_no_equivale_automaticamente_a_riesgo_practico_alto():
    calibration = calibrate_judgment(
        {
            "urgency_score": URGENCY_SCORE_HIGH + 5,
            "practical_risk_score": 0,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 0,
            "base_strength_score": 60,
            "action_ready_score": 80,
            "has_action_candidate": True,
            "followup_present": False,
            "followup_usefulness": "none",
            "next_step_type": "execute",
        }
    )

    assert calibration["signal_scores"]["urgency"] > calibration["signal_scores"]["practical_risk"]
    assert calibration["dominant_signal"] == "urgency"
    assert calibration["decision_confidence_level"] != "high"
    assert calibration["confidence_clarity_score"] > calibration["confidence_stability_score"]


def test_recommendation_stance_deriva_desde_decision_intent_y_contexto():
    calibration = calibrate_judgment(
        {
            "urgency_score": 0,
            "practical_risk_score": 20,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 1,
            "base_strength_score": 52,
            "action_ready_score": 40,
            "has_action_candidate": True,
            "followup_present": False,
            "followup_usefulness": "none",
            "next_step_type": "decide",
        }
    )

    assert calibration["decision_intent"] == "prepare"
    assert calibration["recommendation_stance"] == "orient_with_prudence"


def test_decision_confidence_es_baja_en_caso_tenso_por_senales_competidoras():
    calibration = calibrate_judgment(
        {
            "urgency_score": 76,
            "practical_risk_score": 72,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 1,
            "important_gap_count": 1,
            "base_strength_score": 70,
            "action_ready_score": 74,
            "has_action_candidate": True,
            "followup_present": True,
            "followup_usefulness": "critical",
            "next_step_type": "execute",
        }
    )

    assert calibration["decision_confidence_score"] < 52
    assert calibration["decision_confidence_level"] == "low"
    assert calibration["confidence_clarity_score"] < 60


def test_prioridad_por_dominio_puede_reordenar_senales_sin_romper_default():
    calibration = calibrate_judgment(
        {
            "case_domain": "laboral",
            "urgency_score": 90,
            "practical_risk_score": 82,
            "contradiction_count": 0,
            "blocking_issue_count": 0,
            "critical_gap_count": 0,
            "important_gap_count": 0,
            "base_strength_score": 66,
            "action_ready_score": 70,
            "has_action_candidate": True,
            "followup_present": False,
            "followup_usefulness": "none",
            "next_step_type": "execute",
        }
    )

    assert calibration["dominant_signal"] == "urgency"
    assert calibration["decision_trace"]
