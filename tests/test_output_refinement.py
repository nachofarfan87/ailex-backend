from __future__ import annotations

from app.services import output_refinement_service
from legal_engine.response_postprocessor import ResponsePostprocessor
from legal_engine.orchestrator_schema import RetrievalBundle, StrategyBundle


def _base_response() -> dict:
    return {
        "case_domain": "divorcio",
        "case_domains": ["divorcio", "divorcio", "alimentos"],
        "confidence": 0.32,
        "classification": {"action_slug": "divorcio_unilateral"},
        "legal_decision": {"confidence_score": 0.32, "execution_readiness": "requiere_impulso_procesal"},
        "procedural_case_state": {"blocking_factor": "none"},
        "warnings": [
            "La informacion faltante todavia es significativa para una evaluacion estable.",
            "Persisten cuestiones normativas sin resolver que pueden impactar la prueba.",
        ],
        "normative_reasoning": {
            "unresolved_issues": [
                "No se informa sobre bienes gananciales o situacion patrimonial.",
                "No se informa sobre propuesta reguladora final.",
            ],
        },
        "case_strategy": {
            "strategic_narrative": (
                "Se recomienda definir la via procesal y ordenar la presentacion. "
                "No corresponde presentar reclamos accesorios sin foco. "
                "La base disponible permite avanzar."
            ),
            "recommended_actions": [
                "Redactar el escrito inicial con petitorio claro.",
                "Definir la via procesal mas conveniente.",
                "Reunir prueba documental basica.",
                "Redactar el escrito inicial con petitorio claro.",
                "Acreditar vinculo y antecedentes relevantes.",
                "Preparar borrador de presentacion.",
                "Organizar prueba documental complementaria.",
            ],
            "risk_analysis": [
                "La omision de la propuesta reguladora puede generar observaciones.",
                "La omision de la propuesta reguladora puede generar observaciones judiciales.",
            ],
            "conflict_summary": [
                "Existe conflicto sobre vivienda.",
                "Existe conflicto sobre vivienda.",
            ],
            "procedural_focus": [],
            "secondary_domain_notes": [],
        },
    }


def test_elimina_duplicados_correctamente():
    response = output_refinement_service.refine(_base_response())

    assert response["case_domains"] == ["divorcio", "alimentos"]
    assert len(response["case_strategy"]["risk_analysis"]) == 1
    assert len(response["case_strategy"]["conflict_summary"]) == 1
    assert len(response["case_strategy"]["recommended_actions"]) < 7


def test_reduce_acciones_a_top_5():
    response = output_refinement_service.refine(_base_response())
    actions = response["case_strategy"]["recommended_actions"]

    assert len(actions) == 5
    assert actions[0] == "Definir la via procesal mas conveniente."


def test_mejora_confianza_en_caso_simple():
    response = output_refinement_service.refine(_base_response())

    assert response["confidence"] >= 0.6
    assert response["legal_decision"]["confidence_score"] >= 0.6


def test_genera_quick_start():
    response = output_refinement_service.refine(_base_response())

    assert response["quick_start"].startswith("Primer paso recomendado:")
    assert "Definir la via procesal" in response["quick_start"]


def test_divorcio_simple_moderates_warnings_and_groups_missing_information():
    response = output_refinement_service.refine(_base_response())

    assert response["warnings"] == [
        "Faltan datos para afinar detalles procesales o patrimoniales, pero el encuadre base del caso ya es utilizable."
    ]
    assert response["case_strategy"]["critical_missing_information"] == []
    assert response["case_strategy"]["ordinary_missing_information"] == [
        "Precisar bienes, vivienda familiar y eventual compensacion economica.",
        "Completar la propuesta o convenio regulador con el nivel de detalle necesario.",
    ]


def test_divorcio_con_hijos_y_bienes_sostiene_confianza_media_razonable():
    payload = _base_response()
    payload["normative_reasoning"]["unresolved_issues"] = [
        "No se informa sobre bienes gananciales o situacion patrimonial.",
        "No se informa sobre alimentos de los hijos.",
        "No se informa sobre cuidado personal ni regimen de comunicacion.",
    ]

    response = output_refinement_service.refine(payload)

    assert response["case_domain"] == "divorcio"
    assert response["confidence"] >= 0.55
    assert response["case_strategy"]["critical_missing_information"] == []
    assert response["case_strategy"]["ordinary_missing_information"] == [
        "Precisar bienes, vivienda familiar y eventual compensacion economica.",
        "Precisar alimentos, cuidado personal y regimen de comunicacion si corresponden.",
    ]


def test_caso_con_bloqueo_real_no_recibe_piso_artificial_de_confianza():
    payload = _base_response()
    payload["confidence"] = 0.28
    payload["legal_decision"]["confidence_score"] = 0.28
    payload["legal_decision"]["execution_readiness"] = "bloqueado_procesalmente"
    payload["procedural_case_state"]["blocking_factor"] = "competencia"
    payload["normative_reasoning"]["unresolved_issues"] = [
        "Falta precisar competencia territorial y juzgado competente.",
        "Falta acreditar legitimacion activa.",
    ]
    payload["warnings"] = ["Persisten preguntas criticas que pueden alterar la estrategia."]

    response = output_refinement_service.refine(payload)

    assert response["confidence"] == 0.28
    assert response["legal_decision"]["confidence_score"] == 0.28
    assert response["case_strategy"]["critical_missing_information"] == [
        "Precisar competencia judicial y domicilios relevantes.",
        "Acreditar legitimacion y personeria de las partes.",
    ]
    assert response["warnings"] == ["Persisten preguntas criticas que pueden alterar la estrategia."]


def test_caso_ambiguo_no_aplica_piso_de_confianza():
    payload = _base_response()
    payload["case_domain"] = "generic"
    payload["case_domains"] = ["generic"]
    payload["classification"] = {"action_slug": "generic"}

    response = output_refinement_service.refine(payload)

    assert response["confidence"] == 0.32


def test_dedupe_missing_information_equivalente_colapsa_a_una_sola_formulacion():
    payload = _base_response()
    payload["normative_reasoning"]["unresolved_issues"] = [
        "si sera unilateral o conjunto",
        "falta definir via",
        "falta definir modalidad procesal",
    ]

    response = output_refinement_service.refine(payload)

    assert response["case_strategy"]["ordinary_missing_information"] == [
        "Definir la via procesal aplicable."
    ]


def test_divorce_agreement_facts_enrich_visible_strategy_and_risks():
    payload = _base_response()
    payload["query"] = (
        "Quiero divorciarme. Tengo una hija de 3 meses. "
        "El convenio incluye 20% de mi sueldo para alimentos y regimen comunicacional para 3 dias por semana."
    )
    payload["facts"] = {
        "hay_hijos": True,
        "divorcio_modalidad": "unilateral",
        "hay_acuerdo": False,
        "convenio_regulador": True,
        "alimentos_definidos": True,
        "cuota_alimentaria_porcentaje": "20%",
        "regimen_comunicacional": True,
        "regimen_comunicacional_frecuencia": "3 dias por semana",
    }
    payload["reasoning"] = {
        "short_answer": "La consulta permite orientar una estrategia base de divorcio."
    }
    payload["case_strategy"]["ordinary_missing_information"] = [
        "Completar la propuesta o convenio regulador con el nivel de detalle necesario.",
        "Precisar alimentos, cuidado personal y regimen de comunicacion si corresponden.",
        "Precisar bienes, vivienda familiar y eventual compensacion economica.",
    ]

    response = output_refinement_service.refine(payload)
    reasoning = response["reasoning"]["short_answer"].lower()
    actions = [item.lower() for item in response["case_strategy"]["recommended_actions"]]
    risks = [item.lower() for item in response["case_strategy"]["risk_analysis"]]
    procedural_focus = [item.lower() for item in response["case_strategy"]["procedural_focus"]]
    ordinary_missing = [item.lower() for item in response["case_strategy"]["ordinary_missing_information"]]

    assert "homologacion" in reasoning
    assert "base de calculo" in reasoning
    assert any("homologacion" in item for item in actions)
    assert any("base de calculo" in item for item in actions)
    assert any("porcentaje" in item or "base de calculo" in item for item in risks)
    assert any("nino muy pequeno" in item for item in risks)
    assert any("auditar la precision ejecutable del convenio" in item for item in procedural_focus)
    assert any("gradualidad" in item for item in procedural_focus)
    assert any("base de calculo" in item for item in ordinary_missing)
    assert not any("completar la propuesta o convenio regulador" in item for item in ordinary_missing)
    assert not any("precisar alimentos, cuidado personal y regimen de comunicacion si corresponden" in item for item in ordinary_missing)


def test_divorce_agreement_enrichment_is_noop_without_relevant_facts():
    payload = _base_response()
    payload["query"] = "Quiero divorciarme y necesito orientacion inicial."
    payload["facts"] = {
        "hay_hijos": True,
        "divorcio_modalidad": "unilateral",
    }
    payload["reasoning"] = {
        "short_answer": "La consulta permite orientar una estrategia base de divorcio."
    }
    original_reasoning = payload["reasoning"]["short_answer"]

    response = output_refinement_service.refine(payload)
    actions = [item.lower() for item in response["case_strategy"]["recommended_actions"]]

    assert response["reasoning"]["short_answer"] == original_reasoning
    assert not any("homologacion" in item for item in actions)
    assert not any("base de calculo" in item for item in actions)


# ---------------------------------------------------------------------------
# Quick-start integration into response_text (via ResponsePostprocessor)
# ---------------------------------------------------------------------------

def _retrieval():
    return RetrievalBundle(source_mode="corpus", documents_considered=2)


def _strategy():
    return StrategyBundle()


def _postprocess(pipeline_payload):
    return ResponsePostprocessor().postprocess(
        request_id="test-qs",
        normalized_input={"query": "consulta"},
        pipeline_payload=pipeline_payload,
        retrieval=_retrieval(),
        strategy=_strategy(),
    )


def test_quick_start_inserted_at_beginning_of_response_text():
    """When quick_start exists, it should appear at the start of response_text."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "quick_start": "Primer paso recomendado: Definir la via procesal.",
        "reasoning": {"short_answer": "Respuesta juridica.", "applied_analysis": "Analisis completo."},
    })
    assert result.response_text.startswith("Primer paso recomendado: Definir la via procesal.")
    assert "Respuesta juridica." in result.response_text
    assert "Analisis completo." in result.response_text


def test_quick_start_not_duplicated_if_already_present():
    """If response_text already starts with the prefix, don't duplicate."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "quick_start": "Primer paso recomendado: Definir la via procesal.",
        "reasoning": {
            "short_answer": "Primer paso recomendado: Definir la via procesal.",
            "applied_analysis": "Analisis detallado.",
        },
    })
    text = result.response_text
    count = text.lower().count("primer paso recomendado:")
    assert count == 1, f"Expected 1 occurrence, found {count}"


def test_quick_start_normalizes_repeated_prefix():
    """If quick_start already contains the prefix, don't double it."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "quick_start": "Primer paso recomendado: Primer paso recomendado: Algo.",
        "reasoning": {"short_answer": "Cuerpo del texto."},
    })
    text = result.response_text
    # Should start with exactly one prefix
    assert text.startswith("Primer paso recomendado: Algo.")
    count = text.lower().count("primer paso recomendado:")
    assert count == 1


def test_quick_start_preserves_rest_of_text():
    """The body of response_text must be preserved intact after quick_start."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "quick_start": "Primer paso recomendado: Reunir prueba.",
        "reasoning": {
            "short_answer": "Primera linea.",
            "applied_analysis": "Segunda linea con mas detalle.",
        },
    })
    assert "Primera linea." in result.response_text
    assert "Segunda linea con mas detalle." in result.response_text


def test_no_quick_start_leaves_response_text_unchanged():
    """Without quick_start, response_text should not be modified."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "reasoning": {"short_answer": "Solo texto normal."},
    })
    assert "Primer paso recomendado" not in result.response_text
    assert "Solo texto normal." in result.response_text


def test_empty_quick_start_leaves_response_text_unchanged():
    """An empty quick_start should not add anything."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "quick_start": "",
        "reasoning": {"short_answer": "Texto base."},
    })
    assert "Primer paso recomendado" not in result.response_text
    assert "Texto base." in result.response_text


def test_quick_start_adds_trailing_period():
    """If quick_start body lacks punctuation, a period is appended."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "quick_start": "Primer paso recomendado: Reunir prueba",
        "reasoning": {"short_answer": "Cuerpo."},
    })
    first_line = result.response_text.split("\n")[0]
    assert first_line.endswith(".")


def test_quick_start_not_inserted_when_first_line_is_semantically_similar():
    """If the first line of the text is very similar to quick_start, skip insertion."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "quick_start": "Primer paso recomendado: Definir la via procesal mas conveniente.",
        "reasoning": {
            "short_answer": "Definir la via procesal mas conveniente.",
            "applied_analysis": "Detalle adicional.",
        },
    })
    # Should not have the prefix because the first line is semantically equivalent
    assert not result.response_text.startswith("Primer paso recomendado:")


def test_quick_start_without_prefix_gets_normalized():
    """If quick_start comes without the prefix, add it."""
    result = _postprocess({
        "query": "consulta",
        "pipeline_version": "v1",
        "quick_start": "Definir la via procesal.",
        "reasoning": {"short_answer": "Cuerpo del analisis."},
    })
    assert result.response_text.startswith("Primer paso recomendado: Definir la via procesal.")


def test_response_text_prioritizes_single_guiding_question_when_ask_first_is_active():
    result = _postprocess({
        "query": "Quiero divorciarme",
        "pipeline_version": "v1",
        "reasoning": {
            "short_answer": "El divorcio puede encuadrarse, pero la estrategia depende de mas datos.",
            "applied_analysis": "Analisis extenso que no deberia dominar la respuesta en este punto.",
        },
        "case_strategy": {
            "strategic_narrative": "Narrativa extensa que debe quedar en segundo plano.",
        },
        "conversational": {
            "should_ask_first": True,
            "guided_response": (
                "Para orientarte bien, primero necesito saber si el divorcio sera de comun acuerdo "
                "o unilateral, porque eso cambia la estrategia y la presentacion inicial."
            ),
        },
    })

    assert result.response_text == (
        "Para orientarte bien, primero necesito saber si el divorcio sera de comun acuerdo "
        "o unilateral, porque eso cambia la estrategia y la presentacion inicial."
    )
