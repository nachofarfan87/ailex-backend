# backend/tests/test_legal_reasoning.py
from app.services.legal_reasoning_service import build_legal_reasoning, format_legal_reasoning_as_text


# ── Helpers ────────────────────────────────────────────────────────────────────


def _context(overrides: dict | None = None) -> dict:
    base = {
        "facts": "Las partes desean disolver el vínculo matrimonial.",
        "detected_intent": "iniciar divorcio",
        "legal_area": "divorcio",
        "urgency_level": "low",
        "has_children": False,
        "agreement_level": "none",
        "blocking_factors": "",
        "procedural_posture": "",
    }
    if overrides:
        base.update(overrides)
    return base


def _recommended(result: dict) -> dict:
    return next(s for s in result["scenarios"] if s["recommended"])


# ── Caso 1: divorcio sin acuerdo → recomienda vía unilateral ──────────────────


def test_divorcio_sin_acuerdo_recomienda_unilateral():
    result = build_legal_reasoning(_context({"agreement_level": "none"}))

    assert result["case_summary"]
    assert result["legal_framing"]
    assert result["recommended_strategy"]
    assert 0.0 <= result["reasoning_confidence"] <= 1.0

    recommended = _recommended(result)
    assert recommended["name"] == "Divorcio unilateral"
    assert recommended["recommended"] is True

    # Solo 1 escenario puede ser recommended
    recommended_count = sum(1 for s in result["scenarios"] if s["recommended"])
    assert recommended_count == 1


# ── Caso 2: divorcio con acuerdo → recomienda vía consensuada ─────────────────


def test_divorcio_con_acuerdo_recomienda_consensuado():
    result = build_legal_reasoning(_context({"agreement_level": "full"}))

    recommended = _recommended(result)
    assert recommended["name"] == "Divorcio consensuado"
    assert recommended["viability"] == "alta"
    assert recommended["risk"] == "bajo"

    recommended_count = sum(1 for s in result["scenarios"] if s["recommended"])
    assert recommended_count == 1


# ── Caso 3: caso urgente → prioriza escenario rápido ─────────────────────────


def test_caso_urgente_prioriza_escenario_rapido():
    result = build_legal_reasoning(
        _context({
            "legal_area": "alimentos",
            "urgency_level": "high",
            "has_children": True,
        })
    )

    recommended = _recommended(result)
    assert recommended["name"] == "Cuota alimentaria incidental"
    assert recommended["recommended"] is True

    assert "urgencia" in result["recommended_strategy"].lower() or "rápida" in result["recommended_strategy"].lower()

    recommended_count = sum(1 for s in result["scenarios"] if s["recommended"])
    assert recommended_count == 1


# ── Caso 4: bloqueo procesal → reduce viabilidad ─────────────────────────────


def test_bloqueo_procesal_reduce_viabilidad():
    result = build_legal_reasoning(
        _context({
            "agreement_level": "full",
            "blocking_factors": "medida cautelar vigente",
        })
    )

    # El escenario consensuado debe tener viabilidad reducida por el bloqueo
    consensual = next((s for s in result["scenarios"] if "consensuado" in s["name"].lower()), None)
    assert consensual is not None
    assert consensual["viability"] == "baja"

    # La confianza debe ser menor que sin bloqueo
    result_sin_bloqueo = build_legal_reasoning(_context({"agreement_level": "full"}))
    assert result["reasoning_confidence"] < result_sin_bloqueo["reasoning_confidence"]

    recommended_count = sum(1 for s in result["scenarios"] if s["recommended"])
    assert recommended_count == 1


# ── Invariantes generales ─────────────────────────────────────────────────────


def test_siempre_al_menos_dos_escenarios():
    for area in ("divorcio", "alimentos", "laboral", "civil"):
        result = build_legal_reasoning(_context({"legal_area": area}))
        assert len(result["scenarios"]) >= 2, f"area={area} produjo menos de 2 escenarios"


def test_recommended_strategy_nunca_vacio():
    for agreement in ("none", "full", "partial"):
        result = build_legal_reasoning(_context({"agreement_level": agreement}))
        assert result["recommended_strategy"].strip(), f"recommended_strategy vacío para agreement={agreement}"


def test_format_legal_reasoning_as_text_produce_texto():
    result = build_legal_reasoning(_context())
    text = format_legal_reasoning_as_text(result)
    assert isinstance(text, str)
    assert len(text) > 50
    assert "recomendado" in text.lower()


def test_format_legal_reasoning_vacio_devuelve_cadena_vacia():
    assert format_legal_reasoning_as_text({}) == ""
    assert format_legal_reasoning_as_text(None) == ""  # type: ignore[arg-type]
