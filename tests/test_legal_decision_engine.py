from __future__ import annotations

from legal_engine.legal_decision_engine import LegalDecisionEngine


def _build_inputs(
    *,
    reasoning_confidence: float = 0.75,
    normative_confidence: float = 0.78,
    strength_score: float = 0.72,
    risk_score: float = 0.28,
    evidence_confidence: float = 0.74,
    precedent_trend: str = "neutral",
    precedent_delta: float = 0.0,
    unresolved_issues: list[str] | None = None,
    evidence_gaps: list[str] | None = None,
    procedural_timeline: dict | None = None,
    procedural_case_state: dict | None = None,
):
    return {
        "reasoning": {"confidence_score": reasoning_confidence},
        "normative_reasoning": {
            "confidence_score": normative_confidence,
            "applied_rules": [{}, {}, {}, {}],
            "unresolved_issues": unresolved_issues or [],
        },
        "case_evaluation": {
            "strength_score": strength_score,
            "risk_score": risk_score,
            "legal_risk_level": "alto" if risk_score >= 0.7 else "medio" if risk_score >= 0.45 else "bajo",
        },
        "evidence_reasoning_links": {
            "confidence_score": evidence_confidence,
            "requirement_links": [
                {"support_level": "alto"},
                {"support_level": "alto"},
                {"support_level": "medio"},
            ],
            "critical_evidentiary_gaps": evidence_gaps or [],
        },
        "jurisprudence_analysis": {
            "precedent_trend": precedent_trend,
            "confidence_delta": precedent_delta,
        },
        "conflict_evidence": {"most_vulnerable_point": ""},
        "procedural_timeline": procedural_timeline or {},
        "procedural_case_state": procedural_case_state or {},
    }


def test_strong_norms_and_favorable_precedent_enable_aggressive_posture():
    engine = LegalDecisionEngine()
    result = engine.decide(**_build_inputs(precedent_trend="favorable", precedent_delta=0.05))

    assert result.case_strength_label == "alto"
    assert result.strategic_posture == "agresiva"
    assert result.confidence_score >= 0.72


def test_high_risk_and_weak_evidence_block_aggressive_posture():
    engine = LegalDecisionEngine()
    result = engine.decide(
        **_build_inputs(
            risk_score=0.82,
            evidence_confidence=0.34,
            evidence_gaps=["falta prueba de ingresos", "falta documental basica"],
        )
    )

    assert result.strategic_posture == "cautelosa"
    assert result.case_strength_label != "alto"
    assert result.dominant_factor in {"riesgo", "prueba"}


def test_adverse_precedent_penalty_is_visible_but_not_terminal():
    engine = LegalDecisionEngine()
    favorable = engine.decide(**_build_inputs(precedent_trend="neutral"))
    adverse = engine.decide(**_build_inputs(precedent_trend="adverse", precedent_delta=-0.04))

    assert adverse.confidence_score < favorable.confidence_score
    assert adverse.confidence_score > 0.18
    assert any("jurisprudencia adversa" in note.lower() for note in adverse.decision_notes)


def test_severe_unresolved_issues_drop_case_strength():
    engine = LegalDecisionEngine()
    result = engine.decide(
        **_build_inputs(
            unresolved_issues=[
                "falta competencia",
                "falta legitimacion",
                "falta prueba de ingresos",
                "falta notificacion",
                "falta partida",
            ],
            evidence_gaps=["falta prueba documental critica"],
        )
    )

    assert result.case_strength_label == "bajo"
    assert result.strategic_posture == "cautelosa"


def test_final_confidence_is_stable_and_clamped():
    engine = LegalDecisionEngine()
    result = engine.decide(
        **_build_inputs(
            reasoning_confidence=0.98,
            normative_confidence=0.99,
            strength_score=0.98,
            evidence_confidence=0.99,
            precedent_trend="favorable",
            precedent_delta=0.09,
        )
    )

    assert 0.18 <= result.confidence_score <= 0.92


def test_strong_case_with_pending_service_keeps_merit_high_and_execution_blocked():
    engine = LegalDecisionEngine()
    result = engine.decide(
        **_build_inputs(
            procedural_case_state={
                "procedural_phase": "service",
                "blocking_factor": "service",
                "service_status": "pending",
                "enforcement_signal": "none",
                "defense_status": "unknown",
                "litigation_friction_score": 0.18,
            }
        )
    )

    assert result.case_strength_label == "alto"
    assert result.signal_summary["merit_score"] >= 0.72
    assert result.execution_score <= 0.30
    assert result.execution_readiness == "bloqueado_procesalmente"


def test_defaulted_defense_boosts_execution_score():
    engine = LegalDecisionEngine()
    base = engine.decide(
        **_build_inputs(
            procedural_case_state={
                "procedural_phase": "pre_judgment",
                "blocking_factor": "administrative_delay",
                "service_status": "completed",
                "enforcement_signal": "none",
                "defense_status": "unknown",
                "litigation_friction_score": 0.1,
            }
        )
    )
    defaulted = engine.decide(
        **_build_inputs(
            procedural_case_state={
                "procedural_phase": "pre_judgment",
                "blocking_factor": "administrative_delay",
                "service_status": "completed",
                "enforcement_signal": "none",
                "defense_status": "defaulted",
                "litigation_friction_score": 0.1,
            }
        )
    )

    assert defaulted.execution_score > base.execution_score
    assert defaulted.execution_readiness in {"requiere_impulso_procesal", "listo_para_avanzar"}


def test_judgment_with_enforcement_signal_has_high_execution_score():
    engine = LegalDecisionEngine()
    result = engine.decide(
        **_build_inputs(
            procedural_case_state={
                "procedural_phase": "enforcement",
                "blocking_factor": "execution",
                "service_status": "completed",
                "enforcement_signal": "active",
                "defense_status": "defaulted",
                "litigation_friction_score": 0.08,
            }
        )
    )

    assert result.execution_score >= 0.65
    assert result.execution_readiness == "listo_para_avanzar"
    assert result.dominant_factor == "procesal"


def test_competence_issue_drives_execution_score_very_low():
    engine = LegalDecisionEngine()
    result = engine.decide(
        **_build_inputs(
            procedural_case_state={
                "procedural_phase": "initial",
                "blocking_factor": "competence",
                "service_status": "unknown",
                "enforcement_signal": "none",
                "defense_status": "unknown",
                "litigation_friction_score": 0.25,
            }
        )
    )

    assert result.case_strength_label == "alto"
    assert result.execution_score <= 0.25
    assert result.execution_readiness == "bloqueado_procesalmente"
    assert result.dominant_factor == "procesal"
