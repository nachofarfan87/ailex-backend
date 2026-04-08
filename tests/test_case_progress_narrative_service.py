# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_case_progress_narrative_service.py
from __future__ import annotations

from app.services.case_progress_narrative_service import build_case_progress_narrative


def _snapshot(
    *,
    confirmed_facts: dict | None = None,
    open_needs: list[dict] | None = None,
    contradictions: list[dict] | None = None,
    case_stage: str = "recopilacion_hechos",
    primary_goal: str = "",
) -> dict:
    return {
        "case_state": {
            "case_stage": case_stage,
            "primary_goal": primary_goal,
        },
        "confirmed_facts": confirmed_facts or {},
        "probable_facts": {},
        "open_needs": open_needs or [],
        "contradictions": contradictions or [],
        "recommended_followup": None,
    }


def _api_payload(
    execution_output: dict | None = None,
    case_followup: dict | None = None,
    blocking_missing: bool = False,
) -> dict:
    return {
        "execution_output": execution_output or {},
        "case_followup": case_followup or {},
        "conversation_state": {
            "progress_signals": {
                "blocking_missing": blocking_missing,
            }
        },
    }


def test_no_aplica_si_no_hay_facts_ni_needs_utiles():
    narrative = build_case_progress_narrative(
        _snapshot(),
        _api_payload(),
        "estructuracion",
    )

    assert narrative["applies"] is False


def test_genera_bloque_de_facts_confirmados():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            primary_goal="reclamar cuota alimentaria",
        ),
        _api_payload(),
        "estructuracion",
    )

    assert narrative["applies"] is True
    assert "hijos involucrados" in narrative["known_block"].lower()


def test_genera_bloque_de_needs_abiertos():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            open_needs=[
                {"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high"},
            ],
        ),
        _api_payload(),
        "estructuracion",
    )

    assert "ingresos del otro progenitor" in narrative["missing_block"].lower()


def test_limita_facts_y_needs_mostrados():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={
                "hay_hijos": True,
                "hay_acuerdo": False,
                "domicilio_relevante": "Cordoba",
            },
            open_needs=[
                {"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high"},
                {"need_key": "procesal::jurisdiccion", "category": "procesal", "priority": "high"},
                {"need_key": "economico::gastos", "category": "economico", "priority": "normal"},
            ],
        ),
        _api_payload(),
        "estructuracion",
    )

    assert narrative["known_block"].count(" y que ") <= 1
    assert narrative["missing_block"].count(" y ") <= 1


def test_cambia_comportamiento_segun_output_mode():
    structuring = build_case_progress_narrative(
        _snapshot(confirmed_facts={"hay_hijos": True}),
        _api_payload(),
        "estructuracion",
    )
    strategy = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            open_needs=[{"need_key": "estrategia::modalidad_divorcio", "category": "estrategia", "priority": "high"}],
            case_stage="analisis_estrategico",
        ),
        _api_payload(),
        "estrategia",
    )

    assert "ordenar mejor el caso" in structuring["progress_block"].lower()
    assert "via principal" in strategy["progress_block"].lower()


def test_en_ejecucion_aplica_solo_si_suma_claridad():
    applies = build_case_progress_narrative(
        _snapshot(confirmed_facts={"hay_hijos": True}, case_stage="ejecucion"),
        _api_payload(
            execution_output={
                "applies": True,
                "execution_output": {"what_to_do_now": ["Presentar escrito.", "Reunir documentacion."]},
            }
        ),
        "ejecucion",
    )
    not_applies = build_case_progress_narrative(
        _snapshot(confirmed_facts={"hay_hijos": True}, case_stage="ejecucion"),
        _api_payload(),
        "ejecucion",
    )

    assert applies["applies"] is False
    assert applies["progress_block"] == ""
    assert not_applies["applies"] is False


def test_no_devuelve_texto_tecnico_tipo_key_value():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            open_needs=[{"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high"}],
        ),
        _api_payload(),
        "estructuracion",
    )

    rendered = " ".join(
        [
            narrative["opening"],
            narrative["known_block"],
            narrative["missing_block"],
            narrative["progress_block"],
            narrative["priority_block"],
        ]
    ).lower()
    assert "hay_hijos" not in rendered
    assert "ingresos_otro_progenitor" not in rendered


def test_opening_variants_are_stable():
    first_snapshot = _snapshot(
        confirmed_facts={"hay_hijos": True},
        open_needs=[{"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high"}],
        primary_goal="reclamar cuota alimentaria",
    )
    second_snapshot = _snapshot(
        confirmed_facts={"hay_hijos": True, "hay_acuerdo": False},
        open_needs=[
            {"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high"},
            {"need_key": "procesal::jurisdiccion", "category": "procesal", "priority": "high"},
        ],
        primary_goal="iniciar divorcio unilateral",
    )

    first = build_case_progress_narrative(first_snapshot, _api_payload(), "estructuracion")
    first_again = build_case_progress_narrative(first_snapshot, _api_payload(), "estructuracion")
    second = build_case_progress_narrative(second_snapshot, _api_payload(), "estructuracion")

    assert first["opening"] == first_again["opening"]
    assert first["opening"] != second["opening"]


def test_opening_estrategia_puede_usar_variante_decisional():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            open_needs=[
                {"need_key": "estrategia::modalidad_divorcio", "category": "estrategia", "priority": "high"},
                {"need_key": "procesal::jurisdiccion", "category": "procesal", "priority": "high"},
            ],
            primary_goal="definir la estrategia del divorcio y alimentos",
        ),
        _api_payload(),
        "estrategia",
    )

    assert narrative["opening"] in {
        "Con la informacion reunida hasta aca...",
        "Con la base que ya esta reunida...",
        "Con lo que ya esta definido en el caso...",
        "Con lo que ya quedo claro en el caso...",
    }


def test_priority_block_removed_when_followup_equivalent():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            open_needs=[{"need_key": "hecho::ingresos_otro_progenitor", "category": "hecho", "priority": "high"}],
        ),
        _api_payload(
            case_followup={
                "should_ask": True,
                "question": "¿Podés precisar los ingresos del otro progenitor?",
                "need_key": "hecho::ingresos_otro_progenitor",
            }
        ),
        "estructuracion",
    )

    assert narrative["priority_block"] == ""


def test_contradiction_block_applies_in_structuring():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            contradictions=[{"fact_key": "ingresos_otro_progenitor"}],
        ),
        _api_payload(),
        "estructuracion",
    )

    assert "aspecto clave" in narrative["contradiction_block"].lower() or "aspectos relevantes" in narrative["contradiction_block"].lower()


def test_contradiction_block_not_forced_in_execution():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            contradictions=[{"fact_key": "ingresos_otro_progenitor"}],
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

    assert narrative["contradiction_block"] == ""


def test_no_technical_contradiction_text():
    narrative = build_case_progress_narrative(
        _snapshot(
            confirmed_facts={"hay_hijos": True},
            contradictions=[{"fact_key": "hay_hijos", "event_type": "fact_contradiction_detected"}],
        ),
        _api_payload(),
        "estructuracion",
    )

    rendered = narrative["contradiction_block"].lower()
    assert "fact_key" not in rendered
    assert "contradicted" not in rendered
    assert "hay_hijos" not in rendered
