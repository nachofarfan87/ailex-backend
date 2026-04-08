from __future__ import annotations

from app.services.case_followup_service import build_case_followup
from app.services.conversation_integrity_service import build_integrity_state


def _snapshot(
    *,
    open_needs: list[dict] | None = None,
    confirmed_facts: dict | None = None,
    probable_facts: dict | None = None,
    case_stage: str = "recopilacion_hechos",
) -> dict:
    return {
        "case_state": {"case_stage": case_stage},
        "confirmed_facts": confirmed_facts or {},
        "probable_facts": probable_facts or {},
        "open_needs": open_needs or [],
        "contradictions": [],
        "recommended_followup": None,
    }


def _api_payload(
    *,
    completeness: str = "medium",
    blocking_missing: bool = False,
    execution_output: dict | None = None,
    case_progress: dict | None = None,
) -> dict:
    return {
        "conversation_state": {
            "progress_signals": {
                "case_completeness": completeness,
                "blocking_missing": blocking_missing,
            }
        },
        "execution_output": execution_output or {},
        "case_progress": case_progress or {},
    }


def test_no_pregunta_si_no_hay_open_needs():
    followup = build_case_followup(
        _snapshot(open_needs=[]),
        _api_payload(),
        "estrategia",
    )

    assert followup["should_ask"] is False
    assert followup["question"] == ""


def test_elige_need_critical_antes_que_high():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {"need_key": "hecho::ingresos", "category": "economico", "priority": "high", "suggested_question": "¿Cuáles son los ingresos?"},
                {"need_key": "procesal::jurisdiccion", "category": "procesal", "priority": "critical", "suggested_question": "¿En qué provincia tramitarías esto?"},
            ]
        ),
        _api_payload(blocking_missing=True),
        "estrategia",
    )

    assert followup["should_ask"] is True
    assert followup["need_key"] == "procesal::jurisdiccion"


def test_prioriza_need_con_suggested_question_valida():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {"need_key": "hecho::ingresos", "category": "hecho", "priority": "high", "suggested_question": ""},
                {"need_key": "hecho::domicilio", "category": "hecho", "priority": "high", "suggested_question": "¿Cuál es el domicilio actual?"},
            ]
        ),
        _api_payload(),
        "recopilacion_hechos",
    )

    assert followup["should_ask"] is True
    assert "domicilio actual" in followup["question"].lower()


def test_no_pregunta_en_ejecucion_si_no_hay_blocking():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {"need_key": "procesal::jurisdiccion", "category": "procesal", "priority": "critical", "suggested_question": "¿En qué provincia tramitarías esto?"},
            ],
            case_stage="ejecucion",
        ),
        _api_payload(blocking_missing=False),
        "ejecucion",
    )

    assert followup["should_ask"] is False


def test_genera_pregunta_desde_need_key_si_falta_suggested_question():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high", "suggested_question": ""},
            ]
        ),
        _api_payload(),
        "recopilacion_hechos",
    )

    assert followup["should_ask"] is True
    assert followup["question"] == "¿Podés precisar los ingresos del otro progenitor?"


def test_prioriza_need_procesal_sobre_economico_si_misma_prioridad():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {"need_key": "hecho::ingresos", "category": "economico", "priority": "high", "suggested_question": "¿Cuáles son los ingresos?"},
                {"need_key": "procesal::jurisdiccion", "category": "procesal", "priority": "high", "suggested_question": "¿En qué provincia tramitarías esto?"},
            ]
        ),
        _api_payload(),
        "estrategia",
    )

    assert followup["need_key"] == "procesal::jurisdiccion"


def test_retorna_estructura_completa_incluso_cuando_no_pregunta():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {"need_key": "hecho::ingresos", "category": "economico", "priority": "normal", "suggested_question": "¿Cuáles son los ingresos?"},
            ]
        ),
        _api_payload(completeness="high"),
        "estrategia",
    )

    assert followup == {
        "should_ask": False,
        "question": "",
        "reason": "Hay suficiente información para avanzar sin follow-up.",
        "source": "none",
        "priority": "",
        "need_key": "",
    }


def test_case_progress_reduce_preguntas_innecesarias_en_ejecucion_lista():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {"need_key": "procesal::jurisdiccion", "category": "procesal", "priority": "critical", "suggested_question": "¿En qué provincia tramitarías esto?"},
            ],
            case_stage="analisis_estrategico",
        ),
        _api_payload(
            blocking_missing=True,
            case_progress={
                "stage": "ejecucion",
                "readiness_label": "high",
                "progress_status": "ready",
                "next_step_type": "execute",
                "critical_gaps": [],
                "blocking_issues": [],
            },
        ),
        "ejecucion",
    )

    assert followup["should_ask"] is False


def test_case_progress_prioriza_resolver_contradiccion():
    followup = build_case_followup(
        _snapshot(
            open_needs=[],
            case_stage="recopilacion_hechos",
        ),
        _api_payload(
            case_progress={
                "stage": "inconsistente",
                "next_step_type": "resolve_contradiction",
                "progress_status": "blocked",
                "blocking_issues": [{"type": "contradictions"}],
                "basis": {
                    "contradictions": [
                        {"key": "domicilio_relevante", "prev_value": "Jujuy", "new_value": "Salta"},
                    ]
                },
            }
        ),
        "estructuracion",
    )

    assert followup["should_ask"] is True
    assert "domicilio relevante" in followup["question"].lower()


# ── Ajustes finos 13C ─────────────────────────────────────────────────────────


def test_decision_sin_critical_con_important_procesal_permite_pregunta_estrategica():
    """
    AJUSTE 3: En stage=decision sin critical_gaps pero con important_gap de tipo
    procesal, debe permitirse una única pregunta estratégica.
    """
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {
                    "need_key": "procesal::jurisdiccion",
                    "category": "procesal",
                    "priority": "high",
                    "suggested_question": "¿En qué provincia tramitarías esto?",
                },
            ],
            case_stage="analisis_estrategico",
        ),
        _api_payload(
            blocking_missing=False,
            case_progress={
                "stage": "decision",
                "next_step_type": "decide",
                "progress_status": "advancing",
                "readiness_label": "medium",
                "critical_gaps": [],
                "important_gaps": [{"key": "jurisdiccion", "purpose": "procesal", "priority": "high"}],
                "blocking_issues": [],
                "contradiction_count": 0,
            },
        ),
        "estrategia",
    )

    assert followup["should_ask"] is True, (
        "En decision con important procesal, debe permitirse pregunta estratégica"
    )
    assert "provincia" in followup["question"].lower()


def test_decision_sin_critical_sin_important_alto_impacto_no_pregunta():
    """
    AJUSTE 3 complementario: En stage=decision sin critical_gaps y solo con
    important_gaps de bajo impacto (economico), no se debe preguntar.
    """
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {
                    "need_key": "hecho::monto_estimado",
                    "category": "economico",
                    "priority": "high",
                    "suggested_question": "¿Cuál sería el monto estimado?",
                },
            ],
            case_stage="analisis_estrategico",
        ),
        _api_payload(
            blocking_missing=False,
            case_progress={
                "stage": "decision",
                "next_step_type": "decide",
                "progress_status": "advancing",
                "readiness_label": "medium",
                "critical_gaps": [],
                "important_gaps": [{"key": "monto_estimado", "purpose": "economico", "priority": "high"}],
                "blocking_issues": [],
                "contradiction_count": 0,
            },
        ),
        "estrategia",
    )

    assert followup["should_ask"] is False, (
        "En decision con solo important económico, no se debe preguntar"
    )


def test_backward_compat_sin_case_progress_no_explota():
    """
    Backward compat: si case_progress está vacío o ausente,
    _should_ask_followup no debe lanzar excepción.
    """
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {
                    "need_key": "procesal::jurisdiccion",
                    "category": "procesal",
                    "priority": "critical",
                    "suggested_question": "¿En qué provincia tramitarías esto?",
                },
            ],
        ),
        _api_payload(blocking_missing=True, case_progress={}),
        "estrategia",
    )

    # No debe explotar; el resultado puede ser should_ask True o False pero sin excepción
    assert isinstance(followup, dict)
    assert "should_ask" in followup


def test_no_repite_followup_si_el_fact_ya_esta_resuelto_en_case_memory():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {
                    "need_key": "hecho::aportes_actuales",
                    "resolved_by_fact_key": "aportes_actuales",
                    "category": "hecho",
                    "priority": "critical",
                    "suggested_question": "¿El otro progenitor esta aportando algo actualmente?",
                },
            ]
        ),
        {
            **_api_payload(blocking_missing=True),
            "case_memory": {
                "facts": {
                    "aportes_actuales": {"value": False, "source": "confirmed", "confidence": 1.0},
                }
            },
        },
        "estructuracion",
    )

    assert followup["should_ask"] is False
    assert followup["question"] == ""


def test_no_repite_followup_equivalente_por_alias_semantico():
    followup = build_case_followup(
        _snapshot(
            open_needs=[
                {
                    "need_key": "hecho::pagos_actuales",
                    "category": "hecho",
                    "priority": "critical",
                    "suggested_question": "¿El otro progenitor esta aportando algo actualmente?",
                },
            ]
        ),
        {
            **_api_payload(blocking_missing=True),
            "conversation_state": {
                "progress_signals": {
                    "case_completeness": "medium",
                    "blocking_missing": True,
                },
                "asked_questions": ["¿El otro padre o madre le pasa algo de plata actualmente?"],
            },
            "case_memory": {
                "facts": {
                    "aportes_actuales": {"value": False, "source": "confirmed", "confidence": 1.0},
                }
            },
        },
        "estructuracion",
    )

    assert followup["should_ask"] is False
    assert followup["question"] == ""


def test_asked_slot_solo_no_cuenta_como_resuelto():
    integrity = build_integrity_state(
        conversation_state={
            "asked_questions": ["¿El otro progenitor está aportando algo actualmente?"],
        },
        case_memory={},
    )

    assert integrity["slot_statuses"]["aportes_actuales"] == "unknown"
    assert "aportes_actuales" not in integrity["blocked_slots"]
