from app.services.legal_reasoning_service import build_legal_reasoning, format_legal_reasoning_as_text


def _context(overrides: dict | None = None) -> dict:
    base = {
        "facts": "Las partes desean disolver el vinculo matrimonial y necesitan ordenar el conflicto.",
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


def _scenario(result: dict, needle: str) -> dict:
    return next(s for s in result["scenarios"] if needle.lower() in s["name"].lower())


def test_divorcio_sin_acuerdo_recomienda_unilateral():
    result = build_legal_reasoning(_context({"agreement_level": "none"}))

    assert result["case_summary"]
    assert result["legal_framing"]
    assert result["recommended_strategy"]
    assert 0.0 <= result["reasoning_confidence"] <= 1.0

    recommended = _recommended(result)
    assert recommended["name"] == "Divorcio unilateral"
    assert recommended["recommended"] is True
    assert recommended["score"] > _scenario(result, "consensuado")["score"]
    assert sum(1 for s in result["scenarios"] if s["recommended"]) == 1


def test_divorcio_con_acuerdo_y_sin_bloqueo_recomienda_consensuado():
    result = build_legal_reasoning(_context({"agreement_level": "full"}))

    recommended = _recommended(result)
    assert recommended["name"] == "Divorcio consensuado"
    assert recommended["viability"] == "alta"
    assert recommended["risk"] == "bajo"
    assert recommended["score"] >= _scenario(result, "unilateral")["score"]
    assert sum(1 for s in result["scenarios"] if s["recommended"]) == 1


def test_alimentos_urgente_prioriza_la_via_mas_rapida():
    result = build_legal_reasoning(
        _context(
            {
                "legal_area": "alimentos",
                "urgency_level": "high",
                "has_children": True,
            }
        )
    )

    recommended = _recommended(result)
    assert recommended["name"] == "Cuota alimentaria incidental"
    assert recommended["recommended"] is True
    assert recommended["score"] > _scenario(result, "autonomo")["score"]
    assert "urgencia" in result["recommended_strategy"].lower() or "rapida" in result["recommended_strategy"].lower()


def test_bloqueo_procesal_reduce_viabilidad_y_confianza():
    result_con_bloqueo = build_legal_reasoning(
        _context(
            {
                "agreement_level": "full",
                "blocking_factors": "medida cautelar vigente",
            }
        )
    )
    result_sin_bloqueo = build_legal_reasoning(_context({"agreement_level": "full"}))

    consensual_con_bloqueo = _scenario(result_con_bloqueo, "consensuado")
    consensual_sin_bloqueo = _scenario(result_sin_bloqueo, "consensuado")

    assert consensual_con_bloqueo["viability"] == "baja"
    assert consensual_con_bloqueo["score"] < consensual_sin_bloqueo["score"]
    assert result_con_bloqueo["reasoning_confidence"] < result_sin_bloqueo["reasoning_confidence"]
    assert sum(1 for s in result_con_bloqueo["scenarios"] if s["recommended"]) == 1


def test_conflicto_acuerdo_y_urgencia_resuelve_con_scoring_deterministico():
    result = build_legal_reasoning(
        _context(
            {
                "agreement_level": "full",
                "urgency_level": "high",
            }
        )
    )

    recommended = _recommended(result)
    assert recommended["name"] == "Divorcio consensuado"
    assert recommended["score"] > _scenario(result, "unilateral")["score"]
    assert "acuerdo" in result["recommended_strategy"].lower()
    assert "urgencia" in result["recommended_strategy"].lower() or "rapida" in result["recommended_strategy"].lower()


def test_conflicto_sin_acuerdo_y_bloqueo_sale_de_comparacion_real():
    result = build_legal_reasoning(
        _context(
            {
                "agreement_level": "none",
                "blocking_factors": "incidente pendiente",
            }
        )
    )

    recommended = _recommended(result)
    consensual = _scenario(result, "consensuado")
    mediation = _scenario(result, "mediacion")

    assert recommended["name"] == "Divorcio unilateral"
    assert recommended["score"] > consensual["score"]
    assert recommended["score"] > mediation["score"]
    assert "bloqueo" in result["recommended_strategy"].lower()


def test_exactamente_un_recommended_en_todas_las_areas_soportadas():
    for area in ("divorcio", "alimentos", "laboral", "civil"):
        result = build_legal_reasoning(_context({"legal_area": area}))
        assert len(result["scenarios"]) >= 2
        assert sum(1 for s in result["scenarios"] if s["recommended"]) == 1, f"area={area}"


def test_recommended_strategy_nunca_vacio():
    for area in ("divorcio", "alimentos", "laboral", "civil"):
        result = build_legal_reasoning(_context({"legal_area": area}))
        assert result["recommended_strategy"].strip(), f"recommended_strategy vacio para area={area}"


def test_formatter_produce_texto_claro_y_menciona_estrategia_y_escenarios():
    result = build_legal_reasoning(_context({"agreement_level": "full"}))
    text = format_legal_reasoning_as_text(result)

    assert isinstance(text, str)
    assert len(text) > 80
    assert "Estrategia recomendada" in text
    assert "Escenarios posibles" in text
    assert "Desarrollo de la estrategia recomendada" in text


def test_format_legal_reasoning_vacio_devuelve_cadena_vacia():
    assert format_legal_reasoning_as_text({}) == ""
    assert format_legal_reasoning_as_text(None) == ""  # type: ignore[arg-type]


def test_mismo_input_produce_mismo_recommended():
    context = _context(
        {
            "legal_area": "alimentos",
            "urgency_level": "high",
            "blocking_factors": "expediente conexo observado",
        }
    )

    first = build_legal_reasoning(context)
    second = build_legal_reasoning(context)

    assert _recommended(first)["name"] == _recommended(second)["name"]
    assert [scenario["score"] for scenario in first["scenarios"]] == [
        scenario["score"] for scenario in second["scenarios"]
    ]
