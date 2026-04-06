# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_strategic_decision_service.py
from __future__ import annotations

from app.services.strategic_decision_service import _score_candidate, resolve_strategic_decision


def _conversation_state(*, known_facts: list[dict] | None = None) -> dict:
    return {
        "conversation_id": "conv-strategic",
        "known_facts": known_facts or [],
    }


def _resolve(*, query: str, facts: dict, action_slug: str, case_domain: str, topics: list[str]) -> dict:
    known_facts = [{"key": key, "value": value} for key, value in facts.items()]
    return resolve_strategic_decision(
        conversation_state=_conversation_state(known_facts=known_facts),
        pipeline_payload={
            "query": query,
            "facts": facts,
            "classification": {"action_slug": action_slug, "case_domain": case_domain},
            "case_profile": {"case_domain": case_domain},
        },
        progression_policy={"topics_covered": topics},
    )


def test_divorcio_con_hijos_alimentos_y_sin_acuerdo_prioriza_unilateral_y_alimentos():
    result = _resolve(
        query="Quiero divorciarme y pedir alimentos para mi hija de 3 meses",
        facts={
            "hay_hijos": True,
            "edad_hija": 0,
            "hay_acuerdo": False,
            "tema_alimentos": True,
        },
        action_slug="divorcio_unilateral",
        case_domain="divorcio",
        topics=["divorcio", "alimentos"],
    )

    assert "divorcio unilateral" in result["recommended_path"].lower()
    assert "alimentos provisorios" in result["recommended_path"].lower()
    assert "no hay acuerdo suficiente" in result["justification"].lower()
    assert "hijos" in result["justification"].lower()
    assert result["alternative_path"]
    assert result["alternative_path"] != result["recommended_path"]
    assert result["alternative_reason"]


def test_divorcio_con_hijos_y_acuerdo_claro_prioriza_via_consensuada():
    result = _resolve(
        query="Queremos divorciarnos de comun acuerdo y ordenar todo lo de nuestros hijos",
        facts={
            "divorcio_modalidad": "comun_acuerdo",
            "hay_hijos": True,
            "hay_acuerdo": True,
        },
        action_slug="divorcio",
        case_domain="divorcio",
        topics=["divorcio"],
    )

    assert "comun acuerdo" in result["recommended_path"].lower()
    assert "acuerdo suficiente" in result["justification"].lower()
    assert "hijos" in result["justification"].lower()
    assert "litigio" in result["alternative_reason"].lower() or "friccion" in result["alternative_reason"].lower()


def test_alimentos_sin_aporte_actual_prioriza_reclamo_inmediato():
    result = _resolve(
        query="No me pasa alimentos para mi hija",
        facts={
            "hay_hijos": True,
            "aporte_actual": False,
            "tema_alimentos": True,
        },
        action_slug="alimentos_hijos",
        case_domain="alimentos",
        topics=["alimentos"],
    )

    assert "cuota provisoria" in result["recommended_path"].lower()
    assert "no hay aporte actual suficiente" in result["justification"].lower()
    assert "respuesta economica" in result["justification"].lower()
    assert "sin respuesta inmediata" in result["alternative_reason"].lower()


def test_divorcio_con_bienes_o_vivienda_y_poco_acuerdo_ordena_lo_patrimonial_desde_el_inicio():
    result = _resolve(
        query="Quiero divorciarme, no hay acuerdo y tenemos casa y bienes para dividir",
        facts={
            "hay_hijos": True,
            "hay_acuerdo": False,
            "hay_bienes": True,
            "vivienda_familiar": True,
        },
        action_slug="divorcio_unilateral",
        case_domain="divorcio",
        topics=["divorcio"],
    )

    assert "efectos patrimoniales" in result["recommended_path"].lower()
    assert "vivienda o bienes" in result["justification"].lower() or "bienes sensibles" in result["justification"].lower()
    assert "vivienda o bienes" in result["alternative_reason"].lower() or "bienes" in result["alternative_reason"].lower()


def test_confidence_sube_con_mas_base_decisoria():
    rich_result = _resolve(
        query="Quiero divorciarme y reclamar alimentos porque no hay acuerdo y no aporta",
        facts={
            "hay_hijos": True,
            "hay_acuerdo": False,
            "tema_alimentos": True,
            "aporte_actual": False,
            "hay_bienes": True,
            "urgencia": True,
        },
        action_slug="divorcio_unilateral",
        case_domain="divorcio",
        topics=["divorcio", "alimentos"],
    )
    light_result = _resolve(
        query="Quiero divorciarme",
        facts={},
        action_slug="divorcio",
        case_domain="divorcio",
        topics=["divorcio"],
    )

    assert rich_result["confidence"] in {"medium", "high"}
    assert light_result["confidence"] in {"low", "medium"}
    assert rich_result["confidence"] != "low"


def test_mismo_input_da_misma_decision():
    kwargs = {
        "query": "Quiero divorciarme y pedir alimentos para mi hija",
        "facts": {
            "hay_hijos": True,
            "tema_alimentos": True,
            "hay_acuerdo": False,
            "aporte_actual": False,
        },
        "action_slug": "divorcio_unilateral",
        "case_domain": "divorcio",
        "topics": ["divorcio", "alimentos"],
    }

    first = _resolve(**kwargs)
    second = _resolve(**kwargs)

    assert first["recommended_path"] == second["recommended_path"]
    assert first["justification"] == second["justification"]
    assert first["alternative_path"] == second["alternative_path"]


def test_score_reasons_limit():
    score, score_reasons = _score_candidate(
        candidate={
            "id": "divorcio_unilateral_alimentos_provisorios",
            "profiles": {
                "agreement": "low",
                "children": "strong",
                "alimentos": "strong",
                "assets": "supports",
                "urgency": "strong",
                "support_gap": "strong",
            },
        },
        signals={
            "involves_divorce": True,
            "involves_alimentos": True,
            "has_children": True,
            "has_minor_children": True,
            "clear_agreement": False,
            "high_conflict": True,
            "no_current_support": True,
            "has_assets_or_home": True,
            "simple_urgency": True,
            "ended_cohabitation": True,
        },
    )

    assert isinstance(score, int)
    assert len(score_reasons) <= 4


def test_query_not_overriding_facts():
    result = _resolve(
        query="No hay acuerdo y esto va a ser conflictivo",
        facts={
            "divorcio_modalidad": "comun_acuerdo",
            "hay_acuerdo": True,
            "hay_hijos": True,
        },
        action_slug="divorcio",
        case_domain="divorcio",
        topics=["divorcio"],
    )

    assert "comun acuerdo" in result["recommended_path"].lower()
