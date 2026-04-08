# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_case_summary_service.py
from __future__ import annotations

from app.services.case_summary_service import build_case_summary


def _snapshot(
    *,
    primary_goal: str = "",
    case_type: str = "",
    case_stage: str = "recopilacion_hechos",
    confirmed_facts: dict | None = None,
    open_needs: list[dict] | None = None,
) -> dict:
    return {
        "case_state": {
            "primary_goal": primary_goal,
            "case_type": case_type,
            "case_stage": case_stage,
        },
        "confirmed_facts": confirmed_facts or {},
        "probable_facts": {},
        "open_needs": open_needs or [],
        "contradictions": [],
        "recommended_followup": None,
    }


def _api_payload(execution_output: dict | None = None) -> dict:
    return {
        "execution_output": execution_output or {},
    }


def test_no_aplica_si_no_hay_senal_suficiente():
    summary = build_case_summary(
        _snapshot(),
        _api_payload(),
        "estructuracion",
    )

    assert summary["applies"] is False
    assert summary["summary_text"] == ""


def test_incluye_primary_goal_si_existe():
    summary = build_case_summary(
        _snapshot(primary_goal="reclamar cuota alimentaria"),
        _api_payload(),
        "orientacion_inicial",
    )

    assert "reclamo de alimentos" in summary["summary_text"].lower()


def test_incluye_facts_humanizados():
    summary = build_case_summary(
        _snapshot(
            primary_goal="reclamar cuota alimentaria",
            confirmed_facts={"hay_hijos": True},
        ),
        _api_payload(),
        "estructuracion",
    )

    assert "hijos involucrados" in summary["summary_text"].lower()


def test_incluye_need_dominante_pendiente():
    summary = build_case_summary(
        _snapshot(
            case_type="divorcio_unilateral",
            open_needs=[
                {"need_key": "economico::ingresos_otro_progenitor", "category": "economico", "priority": "high"},
                {"need_key": "estrategia::modalidad_divorcio", "category": "estrategia", "priority": "critical"},
            ],
        ),
        _api_payload(),
        "estrategia",
    )

    assert "unilateral o de comun acuerdo" in summary["summary_text"].lower()


def test_no_usa_formato_tecnico():
    summary = build_case_summary(
        _snapshot(
            primary_goal="reclamar cuota alimentaria",
            confirmed_facts={"hay_hijos": True},
            open_needs=[{"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high"}],
        ),
        _api_payload(),
        "estructuracion",
    )

    rendered = summary["summary_text"].lower()
    assert "fact_key" not in rendered
    assert "need_key" not in rendered
    assert "confirmed_facts" not in rendered
    assert "open_needs" not in rendered
    assert "hay_hijos" not in rendered


def test_respeta_limite_de_longitud():
    summary = build_case_summary(
        _snapshot(
            primary_goal="iniciar divorcio unilateral con reclamo de alimentos y orden integral del caso",
            confirmed_facts={
                "hay_hijos": True,
                "hay_acuerdo": False,
                "ingresos_otro_progenitor": 200000,
            },
            open_needs=[
                {"need_key": "estrategia::modalidad_divorcio", "category": "estrategia", "priority": "critical"},
                {"need_key": "procesal::jurisdiccion", "category": "procesal", "priority": "high"},
            ],
        ),
        _api_payload(),
        "estrategia",
    )

    assert len(summary["summary_text"]) <= 280


def test_cambia_razonablemente_segun_output_mode():
    strategy = build_case_summary(
        _snapshot(
            case_type="divorcio_unilateral",
            open_needs=[{"need_key": "estrategia::modalidad_divorcio", "category": "estrategia", "priority": "critical"}],
        ),
        _api_payload(),
        "estrategia",
    )
    execution = build_case_summary(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            open_needs=[{"need_key": "hecho::domicilio_relevante", "category": "procesal", "priority": "high"}],
            case_stage="ejecucion",
        ),
        _api_payload(
            execution_output={
                "applies": True,
                "execution_output": {"what_to_do_now": ["Presentar escrito.", "Reunir documentacion."]},
            }
        ),
        "ejecucion",
    )

    assert "estrategia" in strategy["summary_text"].lower() or "via principal" in strategy["summary_text"].lower()
    assert "avanzar" in execution["summary_text"].lower()
