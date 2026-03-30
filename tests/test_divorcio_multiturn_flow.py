from __future__ import annotations

from app.services import output_mode_service
from app.services import output_refinement_service
from app.services.clarification_flow_service import prepare_legal_query_turn
from app.services.strategy_reactivity_service import apply_strategy_reactivity
from legal_engine.case_profile_builder import build_case_profile


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        normalized = text.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(text)
    return result


def _build_frontend_like_clarification_context(
    previous_response: dict,
    previous_request_context: dict,
) -> dict | None:
    conversational = dict(previous_response.get("conversational") or {})
    previous_context = dict((previous_request_context.get("metadata") or {}).get("clarification_context") or {})
    question = str(conversational.get("question") or "").strip()
    base_query = str(
        previous_context.get("base_query")
        or previous_request_context.get("query")
        or previous_response.get("query")
        or ""
    ).strip()
    conversational_known_facts = (
        dict(conversational.get("known_facts") or {})
        if isinstance(conversational.get("known_facts"), dict)
        else {}
    )
    known_facts = {
        **(dict(previous_context.get("known_facts") or {}) if isinstance(previous_context.get("known_facts"), dict) else {}),
        **conversational_known_facts,
    }
    clarified_fields = _dedupe_texts([
        *list(previous_context.get("clarified_fields") or []),
        *list(known_facts.keys()),
    ])

    if not base_query and not previous_response.get("case_domain") and not known_facts:
        return None

    should_ask_first = bool(conversational.get("should_ask_first"))
    asked_questions = _dedupe_texts(
        list(previous_context.get("asked_questions") or [])
        + ([question] if should_ask_first and question else [])
    )

    return {
        **previous_context,
        "base_query": base_query,
        "case_domain": str(previous_response.get("case_domain") or previous_context.get("case_domain") or "").strip(),
        "last_question": question if should_ask_first else str(previous_context.get("last_question") or "").strip(),
        "asked_questions": asked_questions,
        "known_facts": known_facts,
        "clarified_fields": clarified_fields,
    }


def _build_case_profile_for_turn(effective_query: str, facts: dict) -> dict:
    return build_case_profile(
        query=effective_query,
        classification={},
        case_theory={},
        conflict={},
        normative_reasoning={},
        procedural_plan=None,
        facts=facts,
    )


def _question_engine_for_turn(facts: dict) -> dict:
    if "hay_hijos" not in facts:
        return {
            "questions": [
                {
                    "question": "¿Hay hijos menores o con capacidad restringida?",
                    "purpose": "Identificar si el divorcio involucra efectos parentales que deben ordenarse desde el inicio.",
                    "priority": "alta",
                    "category": "hijos",
                }
            ]
        }
    if "divorcio_modalidad" not in facts and "hay_acuerdo" not in facts:
        return {
            "questions": [
                {
                    "question": "¿El divorcio va a ser de comun acuerdo o unilateral?",
                    "purpose": "Definir la variante procesal del divorcio y evitar un encuadre incompleto.",
                    "priority": "alta",
                    "category": "variante_divorcio",
                }
            ]
        }
    return {
        "questions": [
            {
                "question": "¿Ya dejaron de convivir?",
                "purpose": "Ordenar el contenido minimo exigible para la presentacion judicial.",
                "priority": "alta",
                "category": "cese_convivencia",
            },
            {
                "question": "¿Hay bienes relevantes (inmuebles, vehiculos, ahorros)?",
                "purpose": "Ordenar el contenido minimo exigible para la presentacion judicial.",
                "priority": "alta",
                "category": "bienes",
            },
        ]
    }


def _case_strategy_for_turn(facts: dict) -> dict:
    recommended_actions = [
        "Preparar presentacion inicial de divorcio con encuadre y competencia correctos.",
        "Redactar propuesta reguladora con los efectos necesarios del divorcio.",
    ]
    risk_analysis = [
        "Perder el contexto del divorcio puede desviar la estrategia hacia un dominio equivocado.",
    ]
    procedural_focus = [
        "Mantener el flujo en divorcio mientras se completan los hechos pendientes.",
    ]

    if "hay_hijos" not in facts:
        critical_missing = ["Confirmar si existen hijos menores en comun."]
        ordinary_missing = [
            "Definir si el divorcio es conjunto o unilateral.",
            "Precisar que juzgado corresponde judicial y domicilios relevantes.",
        ]
    elif "divorcio_modalidad" not in facts and "hay_acuerdo" not in facts:
        critical_missing = []
        ordinary_missing = [
            "Definir si el divorcio es conjunto o unilateral.",
            "Precisar que juzgado corresponde judicial y domicilios relevantes.",
            "Fecha y lugar de celebracion del matrimonio.",
            "Ultimo domicilio conyugal.",
        ]
    else:
        critical_missing = []
        ordinary_missing = [
            "Precisar si ya hubo cese de convivencia.",
            "Precisar si hay bienes relevantes.",
            "Precisar que juzgado corresponde judicial y domicilios relevantes.",
            "Completar la propuesta o convenio regulador con el nivel de detalle necesario.",
            "Precisar alimentos, cuidado personal y regimen de comunicacion si corresponden.",
        ]

    if facts.get("convenio_regulador") is True:
        ordinary_missing = [
            item
            for item in ordinary_missing
            if "convenio regulador" not in item.lower()
            and "alimentos" not in item.lower()
            and "regimen de comunicacion" not in item.lower()
        ]
        recommended_actions.append(
            "Revisar si el convenio cubre con suficiente detalle alimentos y comunicacion."
        )
        risk_analysis.append(
            "Un convenio incompleto sobre alimentos o comunicacion puede abrir incidentes posteriores."
        )
        procedural_focus.append(
            "Controlar que el convenio regule alimentos y comunicacion de manera ejecutable."
        )

    return {
        "strategy_mode": "conservadora",
        "strategic_narrative": (
            "La estrategia inicial debe mantener el eje en divorcio y ordenar la presentacion "
            "sin perder el contexto conversacional ya aclarado."
        ),
        "conflict_summary": ["Existe un conflicto propio del divorcio que requiere orden procesal."],
        "recommended_actions": recommended_actions,
        "risk_analysis": risk_analysis,
        "procedural_focus": procedural_focus,
        "critical_missing_information": critical_missing,
        "ordinary_missing_information": ordinary_missing,
    }


def _build_pipeline_payload(original_query: str, prepared, profile: dict) -> dict:
    facts = dict(prepared.merged_facts or {})
    case_strategy = apply_strategy_reactivity(
        _case_strategy_for_turn(facts),
        case_domain=profile["case_domain"],
        facts=facts,
        metadata=prepared.metadata,
        query=prepared.effective_query,
    )
    return {
        "query": prepared.effective_query,
        "case_domain": profile["case_domain"],
        "case_domains": profile["case_domains"],
        "case_profile": profile,
        "facts": facts,
        "metadata": prepared.metadata,
        "confidence": 0.32,
        "quick_start": "Primer paso recomendado: Preparar presentacion inicial de divorcio con encuadre y competencia correctos.",
        "reasoning": {
            "short_answer": "La consulta sigue encuadrada como divorcio y requiere mantener ese eje en toda la conversacion.",
        },
        "legal_decision": {
            "confidence_score": 0.32,
            "strategic_posture": "conservadora",
        },
        "procedural_case_state": {"blocking_factor": "none"},
        "question_engine_result": _question_engine_for_turn(facts),
        "case_strategy": case_strategy,
        "procedural_strategy": {
            "next_steps": [
                "Preparar presentacion inicial de divorcio con encuadre y competencia correctos.",
            ],
            "missing_information": [],
        },
        "normative_reasoning": {
            "applied_rules": [
                {"source": "CCyC", "article": "438"},
                {"source": "CCyC", "article": "439"},
            ],
        },
    }


def _run_turn(
    *,
    query: str,
    facts: dict | None = None,
    metadata: dict | None = None,
) -> tuple[object, dict, dict]:
    prepared = prepare_legal_query_turn(
        query=query,
        facts=facts or {},
        metadata=metadata or {},
    )
    profile = _build_case_profile_for_turn(prepared.effective_query, prepared.merged_facts)
    payload = _build_pipeline_payload(query, prepared, profile)
    response = output_mode_service.build_dual_output(output_refinement_service.refine(payload))
    request_context = {
        "query": query,
        "facts": facts or {},
        "metadata": prepared.metadata,
    }
    return prepared, profile, {"response": response, "request_context": request_context}


def test_divorcio_multiturn_flow_preserves_context_and_never_jumps_to_alimentos():
    turn_1_prepared, turn_1_profile, turn_1 = _run_turn(query="Quiero divorciarme")

    assert turn_1_profile["case_domain"] == "divorcio"
    assert turn_1["response"]["conversational"]["should_ask_first"] is True
    assert "hijos" in (turn_1["response"]["conversational"]["question"] or "").lower()

    context_for_turn_2 = _build_frontend_like_clarification_context(
        turn_1["response"],
        turn_1["request_context"],
    )
    assert context_for_turn_2 is not None
    assert context_for_turn_2["case_domain"] == "divorcio"
    assert context_for_turn_2["base_query"] == "Quiero divorciarme"

    turn_2_prepared, turn_2_profile, turn_2 = _run_turn(
        query="Tengo una hija de 3 meses",
        metadata={"clarification_context": context_for_turn_2},
    )

    assert turn_2_profile["case_domain"] == "divorcio"
    assert turn_2_prepared.metadata["clarification_context"]["known_facts"]["hay_hijos"] is True
    assert turn_2_prepared.metadata["clarification_context"]["known_facts"]["hay_hijos_edad"] == "informada"
    assert "hijos" not in (turn_2["response"]["conversational"]["question"] or "").lower()
    assert turn_2["response"]["case_domain"] == "divorcio"

    context_for_turn_3 = _build_frontend_like_clarification_context(
        turn_2["response"],
        turn_2["request_context"],
    )
    assert context_for_turn_3 is not None
    assert context_for_turn_3["case_domain"] == "divorcio"
    assert context_for_turn_3["base_query"] == "Quiero divorciarme"
    assert context_for_turn_3["known_facts"]["hay_hijos"] is True
    assert "hay_hijos_edad" in context_for_turn_3["known_facts"]

    turn_3_prepared, turn_3_profile, turn_3 = _run_turn(
        query="Sera un divorcio unilateral",
        facts=context_for_turn_3["known_facts"],
        metadata={"clarification_context": context_for_turn_3},
    )

    final_context = turn_3_prepared.metadata["clarification_context"]
    final_known_facts = final_context["known_facts"]
    final_question = (turn_3["response"]["conversational"]["question"] or "").lower()

    assert "quiero divorciarme." in turn_3_prepared.effective_query.lower()
    assert "divorcio unilateral" in turn_3_prepared.effective_query.lower()
    assert turn_3_profile["case_domain"] == "divorcio"
    assert turn_3_profile["case_domains"][0] == "divorcio"
    assert turn_3["response"]["case_domain"] == "divorcio"
    assert turn_3["response"]["output_modes"]["user"]["title"] != "Dato clave para orientar alimentos"
    assert "alimentos" not in turn_3["response"]["case_domain"].lower()

    assert final_known_facts["hay_hijos"] is True
    assert final_known_facts["hay_hijos_edad"] == "informada"
    assert final_known_facts["divorcio_modalidad"] == "unilateral"
    assert final_known_facts["hay_acuerdo"] is False

    assert "hijos" not in final_question
    assert final_question != "¿hay hijos menores o con capacidad restringida?"
    assert "alimentos" not in (turn_3["response"]["output_modes"]["user"]["title"] or "").lower()
    assert "divorcio" in (turn_3["response"]["output_modes"]["user"]["title"] or "").lower()


def test_divorcio_multiturn_flow_evolves_when_convenio_terms_are_added():
    _, _, turn_1 = _run_turn(query="Quiero divorciarme")
    context_for_turn_2 = _build_frontend_like_clarification_context(
        turn_1["response"],
        turn_1["request_context"],
    )
    _, _, turn_2 = _run_turn(
        query="Tengo una hija de 3 meses",
        metadata={"clarification_context": context_for_turn_2},
    )
    context_for_turn_3 = _build_frontend_like_clarification_context(
        turn_2["response"],
        turn_2["request_context"],
    )
    _, _, turn_3 = _run_turn(
        query="Sera un divorcio unilateral",
        facts=context_for_turn_3["known_facts"],
        metadata={"clarification_context": context_for_turn_3},
    )
    context_for_turn_4 = _build_frontend_like_clarification_context(
        turn_3["response"],
        turn_3["request_context"],
    )

    turn_4_prepared, turn_4_profile, turn_4 = _run_turn(
        query="El convenio incluye 20% de mi sueldo para alimentos y regimen comunicacional para 3 dias de la semana con mi hija.",
        facts=context_for_turn_4["known_facts"],
        metadata={"clarification_context": context_for_turn_4},
    )

    final_known_facts = turn_4_prepared.metadata["clarification_context"]["known_facts"]
    final_question = (turn_4["response"]["conversational"]["question"] or "").lower()
    user_output = turn_4["response"]["output_modes"]["user"]
    professional_output = turn_4["response"]["output_modes"]["professional"]
    conversational_known_facts = turn_4["response"]["conversational"]["known_facts"]
    professional_summary = (professional_output["summary"] or "").lower()
    user_summary = (user_output["summary"] or "").lower()

    assert turn_4_profile["case_domain"] == "divorcio"
    assert turn_4_profile["case_domains"][0] == "divorcio"
    assert "alimentos" in turn_4_prepared.effective_query.lower()
    assert "regimen comunicacional" in turn_4_prepared.effective_query.lower()
    assert "detalle textual del usuario" in turn_4_prepared.effective_query.lower()

    assert final_known_facts["hay_hijos"] is True
    assert final_known_facts["hay_hijos_edad"] == "informada"
    assert final_known_facts["divorcio_modalidad"] == "unilateral"
    assert final_known_facts["convenio_regulador"] is True
    assert final_known_facts["alimentos_definidos"] is True
    assert final_known_facts["cuota_alimentaria_porcentaje"] == "20%"
    assert final_known_facts["regimen_comunicacional"] is True
    assert final_known_facts["regimen_comunicacional_frecuencia"] == "3 dias por semana"

    assert turn_4["response"]["case_domain"] == "divorcio"
    assert "alimentos" not in turn_4["response"]["case_domain"].lower()
    assert "hijos" not in final_question
    assert "unilateral" not in final_question

    assert conversational_known_facts["tema_cuidado"] == "inferred"
    assert conversational_known_facts["convenio_regulador"] is True
    assert "tema_alimentos" not in conversational_known_facts

    assert "homologacion" in user_summary
    assert "porcentaje" in user_summary or "base de calculo" in user_summary
    assert user_output["quick_start"]
    assert "homologacion" in user_output["quick_start"].lower() or "propuesta reguladora propia" in user_output["quick_start"].lower()
    assert "preparar presentacion inicial de divorcio con encuadre y competencia correctos" not in user_output["quick_start"].lower()
    assert any("homologacion" in step.lower() for step in user_output["next_steps"])
    assert any("base de calculo" in step.lower() for step in user_output["next_steps"])
    assert any("comunicacional" in step.lower() or "comunicacion" in step.lower() for step in user_output["next_steps"])
    assert any("porcentaje" in risk.lower() or "base de calculo" in risk.lower() for risk in user_output["key_risks"])
    assert any("homolog" in focus.lower() for focus in professional_output["procedural_focus"])
    assert "homologacion" in professional_summary or "precision" in professional_summary


def test_divorcio_multiturn_flow_reacts_when_hijos_are_defined():
    _, _, turn_1 = _run_turn(query="Quiero divorciarme")
    context_for_turn_2 = _build_frontend_like_clarification_context(
        turn_1["response"],
        turn_1["request_context"],
    )

    _, _, turn_2 = _run_turn(
        query="Tengo una hija",
        metadata={"clarification_context": context_for_turn_2},
    )

    reactivity = turn_2["response"]["case_strategy"]["strategy_reactivity"]
    user_summary = (turn_2["response"]["output_modes"]["user"]["summary"] or "").lower()
    risks = [item.lower() for item in turn_2["response"]["output_modes"]["user"]["key_risks"]]
    professional_summary = (turn_2["response"]["output_modes"]["professional"]["summary"] or "").lower()

    assert reactivity["stale"] is True
    assert "hay_hijos" in reactivity["changed_fields"]
    assert turn_2["request_context"]["metadata"]["clarification_context"]["strategy_stale"] is True
    assert "hijos" in user_summary
    assert "ahora el caso ya no es un divorcio sin definiciones parentales" in professional_summary
    assert any("hijos" in item or "efectos parentales" in item for item in risks)


def test_divorcio_multiturn_flow_reacts_when_modalidad_becomes_unilateral():
    _, _, turn_1 = _run_turn(query="Quiero divorciarme")
    context_for_turn_2 = _build_frontend_like_clarification_context(
        turn_1["response"],
        turn_1["request_context"],
    )
    _, _, turn_2 = _run_turn(
        query="Tengo una hija",
        metadata={"clarification_context": context_for_turn_2},
    )
    context_for_turn_3 = _build_frontend_like_clarification_context(
        turn_2["response"],
        turn_2["request_context"],
    )

    _, _, turn_3 = _run_turn(
        query="Sera un divorcio unilateral",
        facts=context_for_turn_3["known_facts"],
        metadata={"clarification_context": context_for_turn_3},
    )

    reactivity = turn_3["response"]["case_strategy"]["strategy_reactivity"]
    professional_summary = (turn_3["response"]["output_modes"]["professional"]["summary"] or "").lower()
    user_summary = (turn_3["response"]["output_modes"]["user"]["summary"] or "").lower()
    next_steps = [item.lower() for item in turn_3["response"]["output_modes"]["user"]["next_steps"]]
    risks = [item.lower() for item in turn_3["response"]["output_modes"]["user"]["key_risks"]]

    assert reactivity["stale"] is True
    assert "divorcio_modalidad" in reactivity["changed_fields"]
    assert "hay_acuerdo" in reactivity["changed_fields"]
    assert "unilateral" in professional_summary
    assert "via unilateral" in user_summary or "presentacion propia" in user_summary
    assert any("unilateral" in item for item in next_steps)
    assert any("acuerdo" in item or "unilateral" in item for item in risks)


def test_divorcio_multiturn_flow_shows_clear_contrast_between_states():
    _, _, turn_1 = _run_turn(query="Quiero divorciarme")
    summary_1 = (turn_1["response"]["output_modes"]["professional"]["summary"] or "").lower()

    context_for_turn_2 = _build_frontend_like_clarification_context(
        turn_1["response"],
        turn_1["request_context"],
    )
    _, _, turn_2 = _run_turn(
        query="Tengo una hija",
        metadata={"clarification_context": context_for_turn_2},
    )
    summary_2 = (turn_2["response"]["output_modes"]["professional"]["summary"] or "").lower()

    context_for_turn_3 = _build_frontend_like_clarification_context(
        turn_2["response"],
        turn_2["request_context"],
    )
    _, _, turn_3 = _run_turn(
        query="Sera un divorcio unilateral",
        facts=context_for_turn_3["known_facts"],
        metadata={"clarification_context": context_for_turn_3},
    )
    summary_3 = (turn_3["response"]["output_modes"]["professional"]["summary"] or "").lower()

    assert summary_1 != summary_2
    assert summary_2 != summary_3
    assert "hijos en juego" not in summary_1
    assert "hijos en juego" in summary_2
    assert "via unilateral" not in summary_2
    assert "via unilateral" in summary_3 or "presentacion propia" in summary_3


def test_divorcio_multiturn_flow_does_not_recalculate_when_no_structural_facts_change():
    _, _, turn_1 = _run_turn(query="Quiero divorciarme")
    context_for_turn_2 = _build_frontend_like_clarification_context(
        turn_1["response"],
        turn_1["request_context"],
    )
    _, _, turn_2 = _run_turn(
        query="Tengo una hija",
        metadata={"clarification_context": context_for_turn_2},
    )
    context_for_turn_3 = _build_frontend_like_clarification_context(
        turn_2["response"],
        turn_2["request_context"],
    )
    _, _, turn_3 = _run_turn(
        query="Sera un divorcio unilateral",
        facts=context_for_turn_3["known_facts"],
        metadata={"clarification_context": context_for_turn_3},
    )
    context_for_turn_4 = _build_frontend_like_clarification_context(
        turn_3["response"],
        turn_3["request_context"],
    )

    _, _, turn_4 = _run_turn(
        query="Quiero saber como sigue el tramite",
        facts=context_for_turn_4["known_facts"],
        metadata={"clarification_context": context_for_turn_4},
    )

    reactivity = turn_4["response"]["case_strategy"]["strategy_reactivity"]
    clarification_context = turn_4["request_context"]["metadata"]["clarification_context"]

    assert reactivity["stale"] is False
    assert reactivity["changed_fields"] == []
    assert clarification_context["strategy_stale"] is False
    assert clarification_context["structural_fact_changes"] == []
