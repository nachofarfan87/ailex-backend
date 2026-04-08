# backend/tests/test_legal_reasoning.py
from app.services.legal_reasoning_service import build_legal_reasoning, format_legal_reasoning_as_text


def _context(overrides: dict | None = None) -> dict:
    base = {
        # Exactamente 82 chars → has_facts=True (>50)
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


# ---------------------------------------------------------------------------
# Tests existentes (mantenidos)
# ---------------------------------------------------------------------------


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


def test_formatter_produce_texto_claro_y_menciona_secciones_principales():
    # agreement_level="full" + base facts (82 chars) → standard (simplicity=2)
    result = build_legal_reasoning(_context({"agreement_level": "full"}))
    text = format_legal_reasoning_as_text(result)

    assert isinstance(text, str)
    assert len(text) > 80
    assert "Estrategia recomendada" in text
    assert "Escenarios posibles" in text
    assert "Fundamento de la recomendacion" in text


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
    assert [s["score"] for s in first["scenarios"]] == [s["score"] for s in second["scenarios"]]


# ---------------------------------------------------------------------------
# Tests: procedural_posture (mantenidos)
# ---------------------------------------------------------------------------


def test_postura_inicio_favorece_via_directa():
    result = build_legal_reasoning(
        _context({"procedural_posture": "inicio", "agreement_level": "none"})
    )

    recommended = _recommended(result)
    assert recommended["name"] == "Divorcio unilateral"

    unilateral = _scenario(result, "unilateral")
    consensuado = _scenario(result, "consensuado")
    assert unilateral["score"] > consensuado["score"]


def test_postura_inicio_otorga_bonus_a_escenario_de_baja_dependencia():
    result_con = build_legal_reasoning(
        _context({"procedural_posture": "inicio", "agreement_level": "none"})
    )
    result_sin = build_legal_reasoning(
        _context({"procedural_posture": "", "agreement_level": "none"})
    )

    unilateral_con = _scenario(result_con, "unilateral")
    unilateral_sin = _scenario(result_sin, "unilateral")
    assert unilateral_con["score"] > unilateral_sin["score"]


def test_postura_bloqueado_penaliza_acuerdo_dependiente():
    result_con = build_legal_reasoning(
        _context({"procedural_posture": "bloqueado", "agreement_level": "full"})
    )
    result_sin = build_legal_reasoning(
        _context({"procedural_posture": "", "agreement_level": "full"})
    )

    consensuado_con = _scenario(result_con, "consensuado")
    consensuado_sin = _scenario(result_sin, "consensuado")
    assert consensuado_con["score"] < consensuado_sin["score"]


def test_postura_bloqueado_penaliza_pero_no_invalida_escape_potencial():
    result = build_legal_reasoning(
        _context({"procedural_posture": "bloqueado", "agreement_level": "none"})
    )

    unilateral = _scenario(result, "unilateral")
    consensuado = _scenario(result, "consensuado")
    assert unilateral["score"] > consensuado["score"]


def test_postura_incumplimiento_favorece_vias_rapidas():
    result = build_legal_reasoning(
        _context(
            {
                "legal_area": "alimentos",
                "procedural_posture": "incumplimiento",
                "agreement_level": "none",
            }
        )
    )

    cuota = _scenario(result, "incidental")
    intimacion = _scenario(result, "intimacion")
    assert cuota["score"] > intimacion["score"]


# ---------------------------------------------------------------------------
# Tests: blocking_escape_potential (mantenidos)
# ---------------------------------------------------------------------------


def test_escenarios_tienen_campo_blocking_escape_potential():
    for area in ("divorcio", "alimentos", "laboral", "civil"):
        result = build_legal_reasoning(_context({"legal_area": area}))
        for scenario in result["scenarios"]:
            assert "blocking_escape_potential" in scenario, (
                f"Falta blocking_escape_potential en '{scenario.get('name')}' (area={area})"
            )
            assert scenario["blocking_escape_potential"] in ("alta", "media", "baja"), (
                f"Valor invalido: {scenario['blocking_escape_potential']}"
            )


def test_bloqueo_premia_mayor_escape_potential():
    result = build_legal_reasoning(
        _context({"agreement_level": "none", "blocking_factors": "medida cautelar vigente"})
    )

    unilateral = _scenario(result, "unilateral")
    consensuado = _scenario(result, "consensuado")

    assert unilateral.get("blocking_escape_potential") == "alta"
    assert consensuado.get("blocking_escape_potential") == "baja"
    assert unilateral["score"] > consensuado["score"]


def test_bloqueo_con_escape_alta_tiene_mejor_score_que_sin_escape():
    result = build_legal_reasoning(
        _context(
            {
                "legal_area": "alimentos",
                "blocking_factors": "expediente paralelo bloqueado",
                "agreement_level": "none",
            }
        )
    )

    cuota = _scenario(result, "incidental")
    intimacion = _scenario(result, "intimacion")

    assert cuota.get("blocking_escape_potential") == "alta"
    assert intimacion.get("blocking_escape_potential") == "baja"
    assert cuota["score"] > intimacion["score"]


# ---------------------------------------------------------------------------
# Tests: agreement_level gradado (mantenidos)
# ---------------------------------------------------------------------------


def test_agreement_level_partial_no_es_ni_full_ni_none():
    result_full = build_legal_reasoning(_context({"agreement_level": "full"}))
    result_partial = build_legal_reasoning(_context({"agreement_level": "partial"}))
    result_none = build_legal_reasoning(_context({"agreement_level": "none"}))

    consensuado_full = _scenario(result_full, "consensuado")
    consensuado_partial = _scenario(result_partial, "consensuado")
    consensuado_none = _scenario(result_none, "consensuado")

    assert consensuado_none["score"] < consensuado_partial["score"] < consensuado_full["score"]


def test_agreement_level_partial_sigue_recomendando_consensuado():
    result = build_legal_reasoning(_context({"agreement_level": "partial"}))

    recommended = _recommended(result)
    assert recommended["name"] == "Divorcio consensuado"
    assert sum(1 for s in result["scenarios"] if s["recommended"]) == 1


def test_agreement_level_none_baja_dep_recibe_bonus_gradado():
    result_none = build_legal_reasoning(_context({"agreement_level": "none"}))
    result_partial = build_legal_reasoning(_context({"agreement_level": "partial"}))

    unilateral_none = _scenario(result_none, "unilateral")
    unilateral_partial = _scenario(result_partial, "unilateral")

    assert unilateral_none["score"] > unilateral_partial["score"]


# ---------------------------------------------------------------------------
# Tests: formatter (mantenidos y actualizados)
# ---------------------------------------------------------------------------


def test_formatter_contiene_lectura_rapida():
    # case_summary siempre presente → lectura rapida en cualquier profundidad
    result = build_legal_reasoning(
        _context({"agreement_level": "full", "facts": "Las partes llevan tres anos separadas de hecho."})
    )
    text = format_legal_reasoning_as_text(result)
    assert "Lectura rapida del caso" in text


def test_formatter_contiene_fundamento_de_la_recomendacion():
    result = build_legal_reasoning(_context({"agreement_level": "full"}))
    text = format_legal_reasoning_as_text(result)
    assert "Fundamento de la recomendacion" in text


def test_formatter_estructura_completa():
    """Con postura + partial + facts cortos → standard (complexity=1, simplicity<3)."""
    result = build_legal_reasoning(
        _context(
            {
                "agreement_level": "partial",
                "facts": "Hechos suficientes para activar lectura rapida.",
                "procedural_posture": "inicio",
            }
        )
    )
    text = format_legal_reasoning_as_text(result)

    assert "Lectura rapida del caso" in text
    assert "Estrategia recomendada" in text
    assert "Encuadre juridico" in text
    assert "Escenarios posibles" in text
    assert "Fundamento de la recomendacion" in text


def test_formatter_determinismo():
    context = _context({"agreement_level": "full", "procedural_posture": "inicio"})

    first = format_legal_reasoning_as_text(build_legal_reasoning(context))
    second = format_legal_reasoning_as_text(build_legal_reasoning(context))

    assert first == second


def test_formatter_exactamente_un_recomendado_marcado():
    """
    agreement_level='none' + base facts → minimal (simplicity=3, complexity=0).
    En minimal, '(recomendado)' aparece una vez en la linea de estrategia.
    """
    result = build_legal_reasoning(_context({"agreement_level": "none"}))
    text = format_legal_reasoning_as_text(result)

    assert text.count("(recomendado)") == 1


# ---------------------------------------------------------------------------
# Tests nuevos: reasoning_depth en output
# ---------------------------------------------------------------------------


def test_reasoning_depth_incluido_en_output():
    """El campo reasoning_depth debe estar siempre presente en el output."""
    for area in ("divorcio", "alimentos", "laboral", "civil"):
        result = build_legal_reasoning(_context({"legal_area": area}))
        assert "reasoning_depth" in result, f"Falta reasoning_depth para area={area}"
        assert result["reasoning_depth"] in ("minimal", "standard", "extended"), (
            f"Valor invalido: {result['reasoning_depth']}"
        )


def test_output_mantiene_contrato_completo():
    """El output debe incluir todos los campos del contrato publico."""
    result = build_legal_reasoning(_context())
    for key in ("case_summary", "legal_framing", "scenarios", "recommended_strategy",
                "reasoning_confidence", "reasoning_depth"):
        assert key in result, f"Falta campo '{key}' en el output"


# ---------------------------------------------------------------------------
# Tests nuevos: resolucion de profundidad
# ---------------------------------------------------------------------------


def test_caso_simple_y_claro_produce_minimal():
    """
    Sin bloqueo, sin postura, sin urgencia y gap grande → minimal.
    agreement_level='none': gap = unilateral(9) - consensuado(5) = 4 → simplicity=3.
    """
    result = build_legal_reasoning(_context({"agreement_level": "none"}))
    assert result["reasoning_depth"] == "minimal"


def test_caso_urgente_sin_bloqueo_produce_minimal():
    """
    Urgencia alta + sin bloqueo + gap muy grande → minimal.
    Con urgency y none: gap ≈ 9 ≥ 4, is_urgent=True → simplicity ≥ 4.
    """
    result = build_legal_reasoning(
        _context({"urgency_level": "high", "agreement_level": "none"})
    )
    assert result["reasoning_depth"] == "minimal"


def test_caso_normal_produce_standard():
    """
    agreement_level='full' + base facts (82 chars) + sin bloqueo + sin postura → standard.
    gap = consensuado(10) - unilateral(7) = 3 < 4 → simplicity = 2 (< 3).
    """
    result = build_legal_reasoning(_context({"agreement_level": "full"}))
    assert result["reasoning_depth"] == "standard"


def test_caso_con_bloqueo_y_scores_cercanos_produce_extended():
    """
    Bloqueo + scores cercanos (gap ≤ 2) → complexity ≥ 2 → extended.
    Con partial + blocking: unilateral=3, consensuado=1, gap=2.
    """
    result = build_legal_reasoning(
        _context(
            {
                "agreement_level": "partial",
                "blocking_factors": "medida cautelar vigente",
            }
        )
    )
    assert result["reasoning_depth"] == "extended"


def test_caso_con_bloqueo_postura_y_baja_confianza_produce_extended():
    """
    Bloqueo + postura procesal explicitada → complexity ≥ 2 → extended.
    """
    result = build_legal_reasoning(
        _context(
            {
                "agreement_level": "none",
                "blocking_factors": "incidente de nulidad pendiente",
                "procedural_posture": "bloqueado",
            }
        )
    )
    assert result["reasoning_depth"] == "extended"


def test_urgencia_no_produce_extended_en_caso_simple():
    """
    La urgencia no debe escalar a extended si el caso no tiene complejidad real.
    """
    result = build_legal_reasoning(
        _context({"urgency_level": "high", "agreement_level": "full"})
    )
    # Con urgencia + full + sin bloqueo, el caso es claro → no extended
    assert result["reasoning_depth"] != "extended"


def test_reasoning_depth_determinismo():
    """Mismo input → mismo reasoning_depth en cada llamada."""
    context = _context(
        {
            "agreement_level": "partial",
            "blocking_factors": "medida cautelar",
        }
    )
    first = build_legal_reasoning(context)
    second = build_legal_reasoning(context)
    assert first["reasoning_depth"] == second["reasoning_depth"]


# ---------------------------------------------------------------------------
# Tests nuevos: formatter adaptativo por depth
# ---------------------------------------------------------------------------


def test_formatter_minimal_omite_escenarios_detallados():
    """
    En modo minimal, 'Escenarios posibles' no debe aparecer en el texto.
    Solo estrategia y fundamento.
    """
    result = build_legal_reasoning(_context({"agreement_level": "none"}))
    assert result["reasoning_depth"] == "minimal"

    text = format_legal_reasoning_as_text(result)
    assert "Escenarios posibles" not in text


def test_formatter_minimal_mantiene_estrategia_y_fundamento():
    """En modo minimal, la estrategia y el fundamento deben estar presentes."""
    result = build_legal_reasoning(_context({"agreement_level": "none"}))
    assert result["reasoning_depth"] == "minimal"

    text = format_legal_reasoning_as_text(result)
    assert "Estrategia recomendada" in text
    assert "Fundamento de la recomendacion" in text


def test_formatter_minimal_incluye_recomendado_marker():
    """En modo minimal, '(recomendado)' debe aparecer exactamente una vez."""
    result = build_legal_reasoning(_context({"agreement_level": "none"}))
    assert result["reasoning_depth"] == "minimal"

    text = format_legal_reasoning_as_text(result)
    assert text.count("(recomendado)") == 1


def test_formatter_standard_incluye_cinco_secciones():
    """En modo standard, deben estar las 5 secciones principales."""
    result = build_legal_reasoning(_context({"agreement_level": "full"}))
    assert result["reasoning_depth"] == "standard"

    text = format_legal_reasoning_as_text(result)
    assert "Lectura rapida del caso" in text
    assert "Estrategia recomendada" in text
    assert "Encuadre juridico" in text
    assert "Escenarios posibles" in text
    assert "Fundamento de la recomendacion" in text


def test_formatter_standard_escenarios_tiene_marker_recomendado():
    """En standard, la lista de escenarios debe marcar exactamente uno como recomendado."""
    result = build_legal_reasoning(_context({"agreement_level": "full"}))
    assert result["reasoning_depth"] == "standard"

    text = format_legal_reasoning_as_text(result)
    assert text.count("(recomendado)") == 1


def test_formatter_extended_incluye_otros_escenarios_evaluados():
    """En modo extended, debe aparecer 'Otros escenarios evaluados'."""
    result = build_legal_reasoning(
        _context(
            {
                "agreement_level": "partial",
                "blocking_factors": "medida cautelar vigente",
            }
        )
    )
    assert result["reasoning_depth"] == "extended"

    text = format_legal_reasoning_as_text(result)
    assert "Otros escenarios evaluados" in text


def test_formatter_extended_tiene_estructura_completa_mas_nota():
    """En modo extended, todas las secciones estandar mas la nota final."""
    result = build_legal_reasoning(
        _context(
            {
                "agreement_level": "partial",
                "blocking_factors": "medida cautelar vigente",
            }
        )
    )
    assert result["reasoning_depth"] == "extended"

    text = format_legal_reasoning_as_text(result)
    assert "Lectura rapida del caso" in text
    assert "Estrategia recomendada" in text
    assert "Encuadre juridico" in text
    assert "Escenarios posibles" in text
    assert "Fundamento de la recomendacion" in text
    assert "Otros escenarios evaluados" in text


def test_formatter_extended_nota_menciona_escenarios_no_recomendados():
    """La nota de extended debe mencionar al menos un escenario no recomendado."""
    result = build_legal_reasoning(
        _context(
            {
                "agreement_level": "partial",
                "blocking_factors": "medida cautelar vigente",
            }
        )
    )
    assert result["reasoning_depth"] == "extended"

    text = format_legal_reasoning_as_text(result)
    non_recommended = [s for s in result["scenarios"] if not s["recommended"]]
    for scenario in non_recommended:
        assert scenario["name"] in text, f"'{scenario['name']}' no aparece en el texto extended"


def test_formatter_depth_fallback_a_standard_si_valor_invalido():
    """Si reasoning_depth tiene un valor desconocido, debe comportarse como standard."""
    result = build_legal_reasoning(_context({"agreement_level": "full"}))
    result_mod = dict(result)
    result_mod["reasoning_depth"] = "desconocido"

    text = format_legal_reasoning_as_text(result_mod)
    assert "Escenarios posibles" in text
    assert "Encuadre juridico" in text


def test_formatter_depth_vacio_compatibilidad():
    """format_legal_reasoning_as_text({}) y None deben devolver cadena vacia."""
    assert format_legal_reasoning_as_text({}) == ""
    assert format_legal_reasoning_as_text(None) == ""  # type: ignore[arg-type]
