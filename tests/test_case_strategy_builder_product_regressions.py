from __future__ import annotations

from types import SimpleNamespace

from legal_engine.case_strategy_builder import build_case_strategy
from legal_engine.procedural_strategy import ProceduralPlan, ProceduralStep


def _procedural_plan() -> ProceduralPlan:
    return ProceduralPlan(
        query="divorcio",
        domain="family",
        jurisdiction="jujuy",
        steps=[
            ProceduralStep(
                order=1,
                action="Presentar divorcio",
                deadline_hint=None,
                urgency="normal",
                notes="",
            )
        ],
        risks=[],
        missing_info=[],
        strategic_notes="",
        citations_used=[],
        warnings=[],
    )


def test_divorce_with_children_places_children_axis_before_housing_in_recommended_actions():
    strategy = build_case_strategy(
        query="Quiero divorciarme, tengo un bebe y tambien hay vivienda familiar.",
        case_profile={
            "case_domain": "divorcio",
            "scenarios": {"unilateral", "hijos", "bienes"},
            "strategic_focus": [],
            "vulnerability": False,
        },
        case_theory={
            "primary_theory": "Divorcio con bebe y efectos familiares a ordenar.",
            "objective": "Resolver primero el eje hijos y luego lo patrimonial.",
        },
        conflict={
            "core_dispute": "Divorcio con bebe y desacuerdo sobre organizacion familiar.",
            "most_vulnerable_point": "Falta ordenar cuidado y alimentos del bebe.",
        },
        case_evaluation={},
        procedural_plan=_procedural_plan(),
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=SimpleNamespace(
            short_answer="Hay base para orientar el divorcio.",
            applied_analysis="La estrategia debe ordenar primero el eje familiar.",
        ),
        legal_decision={"strategic_posture": "conservadora"},
    )

    assert "cuidado personal" in strategy["recommended_actions"][0].lower()
