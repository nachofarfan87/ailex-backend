from __future__ import annotations

from app.services.case_progress_service import (
    build_case_progress,
    compute_case_readiness,
    detect_progress_delta,
    extract_case_progress_snapshot,
)


def _case_memory(
    *,
    confirmed: int = 0,
    probable: int = 0,
    critical_missing: list[dict] | None = None,
    important_missing: list[dict] | None = None,
    contradictions: list[dict] | None = None,
    memory_confidence: str = "low",
) -> dict:
    facts: dict[str, dict] = {}
    for index in range(confirmed):
        facts[f"confirmed_{index}"] = {"value": f"value_{index}", "source": "confirmed", "confidence": 1.0}
    for index in range(probable):
        facts[f"probable_{index}"] = {"value": f"value_{index}", "source": "probable", "confidence": 0.6}
    return {
        "facts": facts,
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {
            "critical": critical_missing or [],
            "important": important_missing or [],
            "optional": [],
        },
        "contradictions": contradictions or [],
        "memory_confidence": memory_confidence,
    }


def _gap(key: str, *, priority: str = "medium", purpose: str = "") -> dict:
    return {
        "key": key,
        "label": key.replace("_", " "),
        "priority": priority,
        "purpose": purpose,
        "source": "test",
    }


def _previous_progress(
    *,
    confirmed_fact_count: int,
    missing_critical_count: int,
    contradiction_count: int,
    readiness_level: float,
) -> dict:
    return {
        "stage": "estructuracion",
        "readiness_level": readiness_level,
        "readiness_label": "medium",
        "progress_status": "advancing",
        "blocking_issues": [],
        "critical_gaps": [],
        "important_gaps": [],
        "contradiction_count": contradiction_count,
        "has_contradictions": contradiction_count > 0,
        "next_step_type": "orient",
        "progress_delta": "neutral",
        "basis": {
            "confirmed_fact_count": confirmed_fact_count,
            "total_fact_count": confirmed_fact_count,
            "missing_critical_count": missing_critical_count,
            "missing_important_count": 0,
            "contradiction_count": contradiction_count,
            "memory_confidence": "medium",
            "blocking_factor": "none",
            "progress_state": "advancing",
            "output_mode": "estructuracion",
            "strategy_mode": "",
            "has_execution_steps": False,
            "should_ask_followup": False,
        },
    }


def test_build_case_progress_empty_inputs_returns_stable_structure():
    progress = build_case_progress(
        case_memory=None,
        conversation_state=None,
        case_state_snapshot=None,
        api_payload=None,
    )

    assert progress["stage"] == "exploracion"
    assert progress["readiness_label"] == "low"
    assert progress["progress_status"] == "initial"
    assert progress["next_step_type"] == "orient"
    assert progress["progress_delta"] == "unknown"
    assert progress["blocking_issues"] == []
    assert progress["critical_gaps"] == []
    assert progress["important_gaps"] == []


def test_stage_exploracion_when_few_facts_and_critical_missing():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=1,
            critical_missing=[_gap("ingresos_otro_progenitor", priority="critical", purpose="quantify")],
        ),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )

    assert progress["stage"] == "exploracion"


def test_stage_inconsistente_when_relevant_contradictions_exist():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=3,
            contradictions=[{"key": "hay_hijos", "prev_value": True, "new_value": False, "detected_at": 2}],
            memory_confidence="medium",
        ),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )

    assert progress["stage"] == "inconsistente"
    assert progress["next_step_type"] == "resolve_contradiction"


def test_stage_bloqueado_when_blocking_factor_is_strong():
    progress = build_case_progress(
        case_memory=_case_memory(confirmed=3, memory_confidence="medium"),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={"blocking_factor": "service"},
    )

    assert progress["stage"] == "bloqueado"
    assert progress["progress_status"] == "blocked"


def test_stage_decision_when_base_is_sufficient_and_gaps_are_small():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=4,
            important_missing=[_gap("detalle_adicional")],
            memory_confidence="high",
        ),
        conversation_state={"progress_signals": {"case_completeness": "medium"}},
        case_state_snapshot=None,
        api_payload={"case_confidence": {"confidence_score": 0.72}},
    )

    assert progress["stage"] == "decision"
    assert progress["next_step_type"] == "decide"


def test_stage_decision_requires_new_minimum_base():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=3,
            probable=0,
            memory_confidence="high",
        ),
        conversation_state={"progress_signals": {"case_completeness": "medium"}},
        case_state_snapshot=None,
        api_payload={"case_confidence": {"confidence_score": 0.78}},
    )

    assert progress["stage"] != "decision"


def test_stage_ejecucion_when_readiness_is_high_and_no_blockers():
    progress = build_case_progress(
        case_memory=_case_memory(confirmed=6, memory_confidence="high"),
        conversation_state={"progress_signals": {"case_completeness": "high"}},
        case_state_snapshot=None,
        api_payload={
            "case_confidence": {"confidence_score": 0.85},
            "execution_output": {
                "applies": True,
                "execution_output": {
                    "what_to_do_now": ["Presentar escrito.", "Reunir prueba."],
                    "where_to_go": ["Juzgado competente."],
                },
            },
        },
    )

    assert progress["stage"] == "ejecucion"
    assert progress["readiness_label"] == "high"
    assert progress["next_step_type"] == "execute"


def test_readiness_increases_when_confirmed_facts_increase():
    low = compute_case_readiness(
        case_memory=_case_memory(confirmed=1, memory_confidence="low"),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )
    high = compute_case_readiness(
        case_memory=_case_memory(confirmed=4, memory_confidence="medium"),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )

    assert high > low


def test_readiness_drops_with_critical_missing():
    clean = compute_case_readiness(
        case_memory=_case_memory(confirmed=3, memory_confidence="medium"),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )
    blocked = compute_case_readiness(
        case_memory=_case_memory(
            confirmed=3,
            critical_missing=[_gap("domicilio_relevante", priority="critical", purpose="identify")],
            memory_confidence="medium",
        ),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )

    assert blocked < clean


def test_readiness_drops_with_contradictions():
    clean = compute_case_readiness(
        case_memory=_case_memory(confirmed=4, memory_confidence="high"),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )
    inconsistent = compute_case_readiness(
        case_memory=_case_memory(
            confirmed=4,
            contradictions=[{"key": "vinculo", "prev_value": "padre", "new_value": "tio"}],
            memory_confidence="high",
        ),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )

    assert inconsistent < clean


def test_readiness_is_capped_with_one_contradiction():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=6,
            contradictions=[{"key": "vinculo", "prev_value": "padre", "new_value": "tio"}],
            memory_confidence="high",
        ),
        conversation_state={"progress_signals": {"case_completeness": "high"}},
        case_state_snapshot=None,
        api_payload={"case_confidence": {"confidence_score": 0.92}},
    )

    assert progress["readiness_level"] <= 0.55


def test_readiness_is_more_capped_with_two_contradictions():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=6,
            contradictions=[
                {"key": "vinculo", "prev_value": "padre", "new_value": "tio"},
                {"key": "domicilio", "prev_value": "Jujuy", "new_value": "Salta"},
            ],
            memory_confidence="high",
        ),
        conversation_state={"progress_signals": {"case_completeness": "high"}},
        case_state_snapshot=None,
        api_payload={"case_confidence": {"confidence_score": 0.92}},
    )

    assert progress["readiness_level"] <= 0.4


def test_next_step_type_is_resolve_contradiction_when_needed():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=2,
            contradictions=[{"key": "vinculo", "prev_value": "padre", "new_value": "tio"}],
        ),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )

    assert progress["next_step_type"] == "resolve_contradiction"


def test_next_step_type_is_ask_when_critical_gaps_remain():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=2,
            critical_missing=[_gap("jurisdiccion", priority="critical", purpose="identify")],
            memory_confidence="medium",
        ),
        conversation_state={},
        case_state_snapshot=None,
        api_payload={},
    )

    assert progress["next_step_type"] == "ask"


def test_next_step_type_is_execute_when_preparation_is_high():
    progress = build_case_progress(
        case_memory=_case_memory(confirmed=6, memory_confidence="high"),
        conversation_state={"progress_signals": {"case_completeness": "high"}},
        case_state_snapshot=None,
        api_payload={
            "case_confidence": {"confidence_score": 0.88},
            "execution_output": {
                "applies": True,
                "execution_output": {
                    "what_to_do_now": ["Presentar escrito.", "Acompañar documentación."],
                    "where_to_go": ["Juzgado de familia."],
                },
            },
        },
    )

    assert progress["next_step_type"] == "execute"


def test_next_step_type_does_not_execute_or_decide_when_strong_blocker_exists():
    progress = build_case_progress(
        case_memory=_case_memory(confirmed=6, memory_confidence="high"),
        conversation_state={"progress_signals": {"case_completeness": "high"}},
        case_state_snapshot=None,
        api_payload={
            "blocking_factor": "service",
            "case_confidence": {"confidence_score": 0.9},
            "execution_output": {
                "applies": True,
                "execution_output": {
                    "what_to_do_now": ["Presentar escrito.", "Acompañar prueba."],
                    "where_to_go": ["Juzgado competente."],
                },
            },
        },
    )

    assert progress["next_step_type"] == "ask"


def test_progress_status_is_stalled_when_critical_missing_exists():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=4,
            critical_missing=[_gap("jurisdiccion", priority="critical", purpose="identify")],
            memory_confidence="medium",
        ),
        conversation_state={"progress_signals": {"case_completeness": "medium"}},
        case_state_snapshot=None,
        api_payload={},
    )

    assert progress["progress_status"] == "stalled"


def test_critical_followup_penalty_reduces_readiness():
    without_followup = build_case_progress(
        case_memory=_case_memory(
            confirmed=4,
            critical_missing=[_gap("jurisdiccion", priority="critical", purpose="identify")],
            memory_confidence="medium",
        ),
        conversation_state={"progress_signals": {"case_completeness": "medium"}},
        case_state_snapshot=None,
        api_payload={},
    )
    with_followup = build_case_progress(
        case_memory=_case_memory(
            confirmed=4,
            critical_missing=[_gap("jurisdiccion", priority="critical", purpose="identify")],
            memory_confidence="medium",
        ),
        conversation_state={"progress_signals": {"case_completeness": "medium"}},
        case_state_snapshot=None,
        api_payload={
            "case_followup": {
                "should_ask": True,
            }
        },
    )

    assert with_followup["readiness_level"] < without_followup["readiness_level"]


def test_progress_delta_positive_when_facts_improve_and_gaps_drop():
    progress = build_case_progress(
        case_memory=_case_memory(confirmed=4, memory_confidence="medium"),
        conversation_state={
            "case_progress": _previous_progress(
                confirmed_fact_count=2,
                missing_critical_count=2,
                contradiction_count=0,
                readiness_level=0.31,
            )
        },
        case_state_snapshot=None,
        api_payload={},
    )

    assert progress["progress_delta"] == "positive"


def test_progress_delta_negative_when_contradictions_appear():
    progress = build_case_progress(
        case_memory=_case_memory(
            confirmed=4,
            contradictions=[{"key": "hay_hijos", "prev_value": True, "new_value": False}],
            memory_confidence="medium",
        ),
        conversation_state={
            "case_progress": _previous_progress(
                confirmed_fact_count=4,
                missing_critical_count=0,
                contradiction_count=0,
                readiness_level=0.62,
            )
        },
        case_state_snapshot=None,
        api_payload={},
    )

    assert progress["progress_delta"] == "negative"


def test_extract_case_progress_snapshot_has_expected_keys():
    snapshot = extract_case_progress_snapshot(
        {
            "stage": "decision",
            "readiness_level": 0.64,
            "progress_status": "advancing",
            "next_step_type": "decide",
            "critical_gaps": [_gap("domicilio")],
            "important_gaps": [_gap("detalle_adicional")],
            "blocking_issues": [{"type": "blocking_factor"}],
            "contradiction_count": 1,
            "has_contradictions": True,
            "progress_delta": "neutral",
        }
    )

    assert set(snapshot.keys()) == {
        "stage",
        "readiness_label",
        "progress_status",
        "next_step_type",
        "critical_gap_count",
        "important_gap_count",
        "blocking_issue_count",
        "contradiction_count",
        "has_contradictions",
        "progress_delta",
    }


def test_backward_compatibility_without_case_memory_uses_snapshot_safely():
    progress = build_case_progress(
        case_memory=None,
        conversation_state={"known_facts": [{"key": "hay_hijos", "value": True, "status": "confirmed"}]},
        case_state_snapshot={
            "confirmed_facts": {"hay_hijos": True},
            "open_needs": [{"need_key": "hecho::ingresos_otro_progenitor", "priority": "critical", "category": "hecho"}],
            "contradictions": [],
        },
        api_payload={},
    )

    assert progress["stage"] in {"exploracion", "estructuracion"}
    assert progress["critical_gaps"]


def test_progress_delta_unknown_without_previous_progress():
    result = detect_progress_delta(
        current_progress={"readiness_level": 0.4, "contradiction_count": 0, "basis": {"confirmed_fact_count": 2}},
        previous_progress=None,
    )

    assert result == "unknown"
