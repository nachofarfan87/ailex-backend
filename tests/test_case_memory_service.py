# backend/tests/test_case_memory_service.py
"""
Tests — FASE 13A: Case Memory

Cubre:
1.  build_case_memory con inputs vacíos → estructura completa con defaults
2.  build_case_memory carga confirmed_facts con confidence=1.0
3.  build_case_memory carga probable_facts con confidence=0.6
4.  build_case_memory confirmed_facts tienen precedencia sobre probable_facts para la misma key
5.  build_case_memory extrae parties de los hechos
6.  build_case_memory extrae case_topics desde conversation_state
7.  build_case_memory extrae detected_objectives desde api_payload
8.  build_case_memory clasifica missing_facts correctamente
9.  build_case_memory excluye de missing los hechos ya conocidos
10. build_case_memory integra open_needs del snapshot como faltantes
11. classify_missing_fields: priority=critical → critical
12. classify_missing_fields: purpose=identify → critical
13. classify_missing_fields: key contiene patron critico → critical
14. classify_missing_fields: priority=optional → optional
15. classify_missing_fields: importance=accessory → optional
16. classify_missing_fields: key contiene patron opcional → optional
17. classify_missing_fields: sin criterio → important
18. classify_missing_fields: deduplication por key
19. detect_memory_contradictions: valores distintos no-falsy → contradiccion
20. detect_memory_contradictions: valor nuevo None → no contradiccion
21. detect_memory_contradictions: valores iguales → no contradiccion
22. detect_memory_contradictions: key solo en current → no contradiccion
23. merge_case_memory sin previous → equivale a build_case_memory
24. merge_case_memory preserva hechos anteriores no presentes en el nuevo
25. merge_case_memory hechos con mayor confidence reemplazan a menores
26. merge_case_memory acumula contradicciones sin duplicar por key
27. extract_case_memory_snapshot tiene todas las keys requeridas
28. extract_case_memory_snapshot confirmed_fact_count solo cuenta confidence >= 0.9
29. memory_confidence=high cuando hay >= 5 confirmados y 0 críticos faltantes
30. memory_confidence=low cuando hay pocos hechos y muchos críticos faltantes
"""
from __future__ import annotations

import pytest

from app.services.case_memory_service import (
    build_case_memory,
    classify_missing_fields,
    detect_memory_contradictions,
    extract_case_memory_snapshot,
    merge_case_memory,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _snapshot(
    confirmed: dict | None = None,
    probable: dict | None = None,
    open_needs: list | None = None,
    contradictions: list | None = None,
) -> dict:
    return {
        "confirmed_facts": confirmed or {},
        "probable_facts": probable or {},
        "open_needs": open_needs or [],
        "contradictions": contradictions or [],
    }


def _state(
    working_case_type: str = "",
    working_domain: str = "",
    known_facts: list | None = None,
    missing_facts: list | None = None,
    turn_count: int = 1,
) -> dict:
    return {
        "turn_count": turn_count,
        "working_case_type": working_case_type,
        "working_domain": working_domain,
        "known_facts": known_facts or [],
        "missing_facts": missing_facts or [],
    }


def _missing_item(key: str, priority: str = "medium", purpose: str = "", importance: str = "") -> dict:
    return {"key": key, "priority": priority, "purpose": purpose, "importance": importance}


# ── 1. Inputs vacíos → estructura completa con defaults ───────────────────────

def test_build_case_memory_empty_inputs_returns_full_structure():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=None,
        api_payload=None,
    )
    for key in ("facts", "parties", "case_topics", "detected_objectives",
                "missing", "contradictions", "memory_confidence"):
        assert key in memory, f"Falta clave requerida: {key!r}"


def test_build_case_memory_empty_inputs_parties_shape():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=None,
        api_payload=None,
    )
    assert "claimant" in memory["parties"]
    assert "respondent" in memory["parties"]
    assert "other" in memory["parties"]


def test_build_case_memory_empty_inputs_missing_shape():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=None,
        api_payload=None,
    )
    assert "critical" in memory["missing"]
    assert "important" in memory["missing"]
    assert "optional" in memory["missing"]


# ── 2. confirmed_facts → confidence=1.0 ──────────────────────────────────────

def test_build_case_memory_confirmed_facts_have_full_confidence():
    memory = build_case_memory(
        case_state_snapshot=_snapshot(confirmed={"hay_hijos": True}),
        conversation_state=None,
        api_payload=None,
    )
    assert "hay_hijos" in memory["facts"]
    assert memory["facts"]["hay_hijos"]["confidence"] == 1.0
    assert memory["facts"]["hay_hijos"]["source"] == "confirmed"


# ── 3. probable_facts → confidence=0.6 ───────────────────────────────────────

def test_build_case_memory_probable_facts_have_partial_confidence():
    memory = build_case_memory(
        case_state_snapshot=_snapshot(probable={"vinculo": "progenitor"}),
        conversation_state=None,
        api_payload=None,
    )
    assert "vinculo" in memory["facts"]
    assert memory["facts"]["vinculo"]["confidence"] == 0.6
    assert memory["facts"]["vinculo"]["source"] == "probable"


# ── 4. confirmed tiene precedencia sobre probable para la misma key ───────────

def test_build_case_memory_confirmed_overrides_probable():
    memory = build_case_memory(
        case_state_snapshot=_snapshot(
            confirmed={"rol_procesal": "actor"},
            probable={"rol_procesal": "demandado"},
        ),
        conversation_state=None,
        api_payload=None,
    )
    assert memory["facts"]["rol_procesal"]["value"] == "actor"
    assert memory["facts"]["rol_procesal"]["confidence"] == 1.0


# ── 5. Extrae parties de los hechos ─────────────────────────────────────────

def test_build_case_memory_extracts_claimant_from_facts():
    memory = build_case_memory(
        case_state_snapshot=_snapshot(confirmed={"nombre_actor": "Juan Perez"}),
        conversation_state=None,
        api_payload=None,
    )
    assert memory["parties"]["claimant"] == "Juan Perez"


def test_build_case_memory_extracts_respondent_from_facts():
    memory = build_case_memory(
        case_state_snapshot=_snapshot(confirmed={"nombre_demandado": "Maria Lopez"}),
        conversation_state=None,
        api_payload=None,
    )
    assert memory["parties"]["respondent"] == "Maria Lopez"


# ── 6. Extrae case_topics desde conversation_state ────────────────────────────

def test_build_case_memory_extracts_case_type_as_topic():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=_state(working_case_type="alimentos"),
        api_payload=None,
    )
    assert "alimentos" in memory["case_topics"]


def test_build_case_memory_extracts_domain_as_topic_if_different():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=_state(working_case_type="alimentos", working_domain="familia"),
        api_payload=None,
    )
    assert "alimentos" in memory["case_topics"]
    assert "familia" in memory["case_topics"]


def test_build_case_memory_domain_not_duplicated_if_same_as_case_type():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=_state(working_case_type="laboral", working_domain="laboral"),
        api_payload=None,
    )
    assert memory["case_topics"].count("laboral") == 1


# ── 7. Extrae detected_objectives desde api_payload ──────────────────────────

def test_build_case_memory_extracts_objective_from_dialogue_policy():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=None,
        api_payload={"dialogue_policy": {"dominant_missing_purpose": "quantify"}},
    )
    assert "quantify" in memory["detected_objectives"]


def test_build_case_memory_extracts_action_bias_from_smart_strategy():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=None,
        api_payload={"smart_strategy": {"action_bias": "litigate"}},
    )
    assert "litigate" in memory["detected_objectives"]


# ── 8. Clasifica missing_facts ────────────────────────────────────────────────

def test_build_case_memory_classifies_missing_facts_into_three_buckets():
    state = _state(missing_facts=[
        _missing_item("hay_hijos", priority="critical"),  # → critical
        _missing_item("ingresos", priority="medium"),     # → important
        _missing_item("frecuencia_contacto", priority="low"),  # → optional
    ])
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=state,
        api_payload=None,
    )
    critical_keys = [i["key"] for i in memory["missing"]["critical"]]
    optional_keys = [i["key"] for i in memory["missing"]["optional"]]
    assert "hay_hijos" in critical_keys
    assert "ingresos" in [i["key"] for i in memory["missing"]["important"]]
    assert "frecuencia_contacto" in optional_keys


# ── 9. Excluye de missing los hechos ya conocidos ────────────────────────────

def test_build_case_memory_known_facts_excluded_from_missing():
    state = _state(missing_facts=[
        _missing_item("hay_hijos", priority="critical"),
    ])
    memory = build_case_memory(
        case_state_snapshot=_snapshot(confirmed={"hay_hijos": True}),
        conversation_state=state,
        api_payload=None,
    )
    critical_keys = [i["key"] for i in memory["missing"]["critical"]]
    assert "hay_hijos" not in critical_keys


# ── 10. open_needs del snapshot como faltantes ────────────────────────────────

def test_build_case_memory_open_needs_included_in_missing():
    snapshot = _snapshot(open_needs=[
        {"need_key": "domicilio", "priority": "critical", "reason": "Se necesita domicilio", "category": ""},
    ])
    memory = build_case_memory(
        case_state_snapshot=snapshot,
        conversation_state=None,
        api_payload=None,
    )
    critical_keys = [i["key"] for i in memory["missing"]["critical"]]
    assert "domicilio" in critical_keys


# ── 11–18. classify_missing_fields ────────────────────────────────────────────

def test_classify_critical_by_priority():
    result = classify_missing_fields([_missing_item("alguna_key", priority="critical")])
    assert len(result["critical"]) == 1
    assert result["critical"][0]["key"] == "alguna_key"


def test_classify_critical_by_purpose_identify():
    result = classify_missing_fields([_missing_item("cualquier_key", priority="medium", purpose="identify")])
    assert len(result["critical"]) == 1


def test_classify_critical_by_key_pattern():
    result = classify_missing_fields([_missing_item("vinculo_familiar", priority="medium")])
    assert len(result["critical"]) == 1


def test_classify_optional_by_priority():
    result = classify_missing_fields([_missing_item("x", priority="optional")])
    assert len(result["optional"]) == 1


def test_classify_optional_by_importance_accessory():
    result = classify_missing_fields([_missing_item("x", priority="medium", importance="accessory")])
    assert len(result["optional"]) == 1


def test_classify_optional_by_key_pattern():
    result = classify_missing_fields([_missing_item("frecuencia_contacto_x")])
    assert len(result["optional"]) == 1


def test_classify_important_fallback():
    result = classify_missing_fields([_missing_item("ingresos_netos", priority="medium")])
    assert len(result["important"]) == 1


def test_classify_deduplication_by_key():
    items = [
        _missing_item("hay_hijos", priority="critical"),
        _missing_item("hay_hijos", priority="critical"),
    ]
    result = classify_missing_fields(items)
    assert len(result["critical"]) == 1


# ── 19–22. detect_memory_contradictions ──────────────────────────────────────

def test_detect_contradictions_different_nonfaly_values():
    result = detect_memory_contradictions(
        previous_facts={"rol_procesal": "actor"},
        current_facts={"rol_procesal": "demandado"},
        turn_count=3,
    )
    assert len(result) == 1
    assert result[0]["key"] == "rol_procesal"
    assert result[0]["detected_at"] == 3


def test_detect_contradictions_new_none_not_a_contradiction():
    result = detect_memory_contradictions(
        previous_facts={"nombre": "Juan"},
        current_facts={"nombre": None},
    )
    assert len(result) == 0


def test_detect_contradictions_same_values_no_contradiction():
    result = detect_memory_contradictions(
        previous_facts={"hay_hijos": "si"},
        current_facts={"hay_hijos": "si"},
    )
    assert len(result) == 0


def test_detect_contradictions_key_only_in_current_no_contradiction():
    result = detect_memory_contradictions(
        previous_facts={},
        current_facts={"nuevo_hecho": "valor"},
    )
    assert len(result) == 0


# ── 23–26. merge_case_memory ──────────────────────────────────────────────────

def test_merge_without_previous_equals_build():
    snapshot = _snapshot(confirmed={"hay_hijos": True})
    merged = merge_case_memory(
        previous_memory=None,
        case_state_snapshot=snapshot,
        conversation_state=None,
    )
    assert "hay_hijos" in merged["facts"]
    assert merged["facts"]["hay_hijos"]["confidence"] == 1.0


def test_merge_preserves_facts_not_in_new_snapshot():
    previous = {
        "facts": {"dato_viejo": {"value": "X", "source": "confirmed", "confidence": 1.0}},
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {"critical": [], "important": [], "optional": []},
        "contradictions": [],
        "memory_confidence": "medium",
    }
    merged = merge_case_memory(
        previous_memory=previous,
        case_state_snapshot=_snapshot(),
        conversation_state=None,
    )
    assert "dato_viejo" in merged["facts"]


def test_merge_higher_confidence_replaces_lower():
    previous = {
        "facts": {"vinculo": {"value": "incierto", "source": "probable", "confidence": 0.6}},
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {"critical": [], "important": [], "optional": []},
        "contradictions": [],
        "memory_confidence": "low",
    }
    merged = merge_case_memory(
        previous_memory=previous,
        case_state_snapshot=_snapshot(confirmed={"vinculo": "progenitor"}),
        conversation_state=None,
    )
    assert merged["facts"]["vinculo"]["value"] == "progenitor"
    assert merged["facts"]["vinculo"]["confidence"] == 1.0


def test_merge_accumulates_contradictions_without_duplicating():
    prev_contradiction = {"key": "rol_procesal", "prev_value": "actor", "new_value": "demandado", "detected_at": 1}
    previous = {
        "facts": {},
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {"critical": [], "important": [], "optional": []},
        "contradictions": [prev_contradiction],
        "memory_confidence": "low",
    }
    new_snapshot = _snapshot(contradictions=[prev_contradiction])
    merged = merge_case_memory(
        previous_memory=previous,
        case_state_snapshot=new_snapshot,
        conversation_state=None,
    )
    # El mismo key no debe aparecer dos veces
    contradiction_keys = [c["key"] for c in merged["contradictions"]]
    assert contradiction_keys.count("rol_procesal") == 1


# ── 27–28. extract_case_memory_snapshot ──────────────────────────────────────

def test_extract_snapshot_has_all_required_keys():
    memory = build_case_memory(
        case_state_snapshot=None,
        conversation_state=None,
        api_payload=None,
    )
    snapshot = extract_case_memory_snapshot(memory)
    for key in (
        "confirmed_fact_keys", "confirmed_fact_count", "total_fact_count",
        "missing_critical_count", "missing_important_count", "missing_optional_count",
        "memory_confidence", "has_parties", "case_topics", "contradiction_count",
    ):
        assert key in snapshot, f"Falta clave en snapshot: {key!r}"


def test_extract_snapshot_confirmed_count_only_high_confidence():
    memory = {
        "facts": {
            "hecho_a": {"value": "x", "source": "confirmed", "confidence": 1.0},
            "hecho_b": {"value": "y", "source": "probable", "confidence": 0.6},
        },
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {"critical": [], "important": [], "optional": []},
        "contradictions": [],
        "memory_confidence": "medium",
    }
    snapshot = extract_case_memory_snapshot(memory)
    assert snapshot["confirmed_fact_count"] == 1
    assert snapshot["total_fact_count"] == 2


# ── 29–30. memory_confidence ──────────────────────────────────────────────────

def test_memory_confidence_high_when_enough_confirmed_and_no_critical_missing():
    confirmed = {f"hecho_{i}": f"valor_{i}" for i in range(6)}
    memory = build_case_memory(
        case_state_snapshot=_snapshot(confirmed=confirmed),
        conversation_state=_state(missing_facts=[]),
        api_payload=None,
    )
    assert memory["memory_confidence"] == "high"


def test_memory_confidence_low_when_few_facts_and_many_critical_missing():
    state = _state(missing_facts=[
        _missing_item(f"hecho_critico_{i}", priority="critical") for i in range(5)
    ])
    memory = build_case_memory(
        case_state_snapshot=_snapshot(),
        conversation_state=state,
        api_payload=None,
    )
    assert memory["memory_confidence"] == "low"


# ── 31. merge acumula missing (no sobreescribe) ───────────────────────────────

def test_merge_accumulates_missing_from_both_turns():
    """Missing del turno anterior se preserva si el key no aparece en el nuevo."""
    previous = {
        "facts": {},
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {
            "critical": [_missing_item("vinculo", priority="critical")],
            "important": [],
            "optional": [],
        },
        "contradictions": [],
        "memory_confidence": "low",
    }
    # El nuevo turno trae un faltante diferente, no menciona vinculo
    new_state = _state(missing_facts=[_missing_item("ingresos", priority="medium")])
    merged = merge_case_memory(
        previous_memory=previous,
        case_state_snapshot=_snapshot(),
        conversation_state=new_state,
    )
    all_missing_keys = (
        [i["key"] for i in merged["missing"]["critical"]]
        + [i["key"] for i in merged["missing"]["important"]]
        + [i["key"] for i in merged["missing"]["optional"]]
    )
    assert "vinculo" in all_missing_keys, "vinculo del turno anterior debe preservarse"
    assert "ingresos" in all_missing_keys, "ingresos del turno nuevo debe estar presente"


def test_merge_missing_escalates_to_most_critical_category():
    """Si el mismo key aparece como 'important' en prev y 'critical' en new, queda critical."""
    previous = {
        "facts": {},
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {
            "critical": [],
            "important": [_missing_item("vinculo", priority="medium")],
            "optional": [],
        },
        "contradictions": [],
        "memory_confidence": "low",
    }
    new_state = _state(missing_facts=[_missing_item("vinculo", priority="critical")])
    merged = merge_case_memory(
        previous_memory=previous,
        case_state_snapshot=_snapshot(),
        conversation_state=new_state,
    )
    critical_keys = [i["key"] for i in merged["missing"]["critical"]]
    important_keys = [i["key"] for i in merged["missing"]["important"]]
    assert "vinculo" in critical_keys, "vinculo debe escalar a critical"
    assert "vinculo" not in important_keys, "vinculo no debe quedar en important"


def test_merge_missing_removes_resolved_keys():
    """Un key que ya está en facts no debe aparecer en ninguna categoría de missing."""
    previous = {
        "facts": {},
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {
            "critical": [_missing_item("hay_hijos", priority="critical")],
            "important": [],
            "optional": [],
        },
        "contradictions": [],
        "memory_confidence": "low",
    }
    # El nuevo turno confirma hay_hijos
    merged = merge_case_memory(
        previous_memory=previous,
        case_state_snapshot=_snapshot(confirmed={"hay_hijos": True}),
        conversation_state=None,
    )
    all_missing_keys = (
        [i["key"] for i in merged["missing"]["critical"]]
        + [i["key"] for i in merged["missing"]["important"]]
        + [i["key"] for i in merged["missing"]["optional"]]
    )
    assert "hay_hijos" not in all_missing_keys, "hay_hijos ya conocido no debe estar en missing"


# ── 32. merge respeta api_payload para objetivos ─────────────────────────────

def test_merge_uses_api_payload_for_objectives():
    """merge_case_memory pasa api_payload a build_case_memory para preservar objetivos."""
    previous = {
        "facts": {},
        "parties": {"claimant": None, "respondent": None, "other": []},
        "case_topics": [],
        "detected_objectives": [],
        "missing": {"critical": [], "important": [], "optional": []},
        "contradictions": [],
        "memory_confidence": "low",
    }
    merged = merge_case_memory(
        previous_memory=previous,
        case_state_snapshot=_snapshot(),
        conversation_state=None,
        api_payload={"dialogue_policy": {"dominant_missing_purpose": "quantify"}},
    )
    assert "quantify" in merged["detected_objectives"]


# ── 33. memory_confidence degradada por contradicciones ──────────────────────

def test_memory_confidence_degraded_by_contradictions():
    """Con muchas contradicciones, la confianza baja aunque haya hechos confirmados."""
    confirmed = {f"hecho_{i}": f"valor_{i}" for i in range(6)}
    memory = build_case_memory(
        case_state_snapshot=_snapshot(
            confirmed=confirmed,
            contradictions=[
                {"key": "rol_procesal", "prev_value": "actor", "new_value": "demandado"},
                {"key": "vinculo", "prev_value": "x", "new_value": "y"},
            ],
        ),
        conversation_state=_state(missing_facts=[]),
        api_payload=None,
    )
    # Con 2 contradicciones, no debe llegar a "high" aunque tenga suficientes confirmados
    assert memory["memory_confidence"] != "high"


# ── 34. fact key canonicalization ────────────────────────────────────────────

def test_build_case_memory_canonicalizes_fact_keys():
    """Las keys se normalizan a minúsculas para evitar duplicación semántica."""
    memory = build_case_memory(
        case_state_snapshot=_snapshot(confirmed={"Hay_Hijos": True}),
        conversation_state=None,
        api_payload=None,
    )
    assert "hay_hijos" in memory["facts"]
    assert "Hay_Hijos" not in memory["facts"]
