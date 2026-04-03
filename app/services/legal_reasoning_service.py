from __future__ import annotations


VIABILITY_SCORES = {"alta": 4, "media": 2, "baja": 0}
RISK_SCORES = {"bajo": 2, "medio": 0, "alto": -2}
SPEED_SCORES = {"alta": 2, "media": 1, "baja": 0}
BLOCKING_PENALTIES = {"alta": 3, "media": 2, "baja": 1}
AGREEMENT_DEPENDENCY_PENALTIES = {"alta": 4, "media": 2, "baja": 0}


def build_legal_reasoning(context: dict) -> dict:
    """
    Construye un analisis de razonamiento juridico estructurado a partir del contexto del caso.

    Input context keys:
        facts              (str)  - hechos relevantes del caso
        detected_intent    (str)  - intencion detectada del usuario
        legal_area         (str)  - area juridica (divorcio, alimentos, laboral, etc.)
        urgency_level      (str)  - "high"/"alta" | "medium"/"media" | "low"/"baja"
        has_children       (bool) - hay hijos menores involucrados
        agreement_level    (str)  - "full"/"completo" | "partial"/"parcial" | "none" | None
        blocking_factors   (str)  - factor/es de bloqueo procesal o "" / "none"
        procedural_posture (str)  - postura procesal actual

    Output dict:
        case_summary         (str)
        legal_framing        (str)
        scenarios            (list[dict])
        recommended_strategy (str)
        reasoning_confidence (float 0-1)
    """
    facts = str(context.get("facts") or "").strip()
    detected_intent = str(context.get("detected_intent") or "").strip()
    legal_area = str(context.get("legal_area") or "").strip()
    urgency_level = str(context.get("urgency_level") or "low").strip().lower()
    has_children = bool(context.get("has_children"))
    agreement_level = str(context.get("agreement_level") or "none").strip().lower()
    blocking_factors = str(context.get("blocking_factors") or "").strip()
    procedural_posture = str(context.get("procedural_posture") or "").strip()

    has_blocking = bool(blocking_factors and blocking_factors.lower() not in ("", "none"))
    is_urgent = urgency_level in ("high", "alta")
    has_agreement = agreement_level in ("full", "partial", "completo", "parcial")

    case_summary = _build_case_summary(
        legal_area=legal_area,
        facts=facts,
        procedural_posture=procedural_posture,
        has_children=has_children,
    )
    legal_framing = _build_legal_framing(
        legal_area=legal_area,
        detected_intent=detected_intent,
        has_children=has_children,
    )
    scenarios = _build_scenarios(
        legal_area=legal_area,
        has_agreement=has_agreement,
        is_urgent=is_urgent,
        has_blocking=has_blocking,
        blocking_factors=blocking_factors,
        has_children=has_children,
    )
    scored_scenarios = _select_recommended_scenario(
        scenarios=scenarios,
        is_urgent=is_urgent,
        has_agreement=has_agreement,
        has_blocking=has_blocking,
    )
    recommended_strategy = _build_recommended_strategy(
        scenarios=scored_scenarios,
        is_urgent=is_urgent,
        has_agreement=has_agreement,
        has_blocking=has_blocking,
    )
    reasoning_confidence = _compute_confidence(
        legal_area=legal_area,
        facts=facts,
        has_blocking=has_blocking,
        scenarios=scored_scenarios,
        procedural_posture=procedural_posture,
    )

    return {
        "case_summary": case_summary,
        "legal_framing": legal_framing,
        "scenarios": scored_scenarios,
        "recommended_strategy": recommended_strategy,
        "reasoning_confidence": reasoning_confidence,
    }


def _build_case_summary(
    *,
    legal_area: str,
    facts: str,
    procedural_posture: str,
    has_children: bool,
) -> str:
    area_label = legal_area or "derecho de familia"
    parts = [f"Caso en materia de {area_label}."]
    if procedural_posture:
        parts.append(f"Postura procesal: {procedural_posture}.")
    if has_children:
        parts.append("Involucra hijos menores, lo que activa un marco de proteccion reforzada.")
    if facts:
        snippet = facts[:200].rstrip()
        if len(facts) > 200:
            snippet += "..."
        parts.append(f"Hechos relevantes: {snippet}")
    return " ".join(parts)


def _build_legal_framing(
    *,
    legal_area: str,
    detected_intent: str,
    has_children: bool,
) -> str:
    area = (legal_area or "").lower()

    if "divorcio" in area:
        base = (
            "El regimen de divorcio argentino (arts. 435-438 CCyC) es incausado y unilateral: "
            "cualquier conyuge puede solicitarlo sin expresar causa. "
        )
        if has_children:
            base += (
                "Si hay hijos menores, deben contemplarse con especial cuidado las cuestiones de "
                "cuidado personal, comunicacion y alimentos. "
            )
        base += (
            "La via consensuada suele reducir conflicto y tiempos, mientras que la unilateral "
            "permite avanzar cuando el acuerdo no es suficiente."
        )
        return base

    if "alimentos" in area:
        base = (
            "La obligacion alimentaria surge de la ley y puede reclamarse por una via autonoma "
            "o dentro de un expediente ya existente. "
        )
        if has_children:
            base += "Si hay hijos menores, el interes superior del niño exige una respuesta diligente. "
        base += "La definicion de la via depende sobre todo de la urgencia y del estado procesal."
        return base

    if "laboral" in area or "trabajo" in area:
        return (
            "El conflicto laboral debe analizarse a partir de la existencia del vinculo de dependencia, "
            "la instancia conciliatoria previa y la prueba disponible para sostener el reclamo."
        )

    if "penal" in area:
        return (
            "En materia penal rigen el principio de legalidad y la garantia de defensa. "
            "El analisis prudente requiere identificar con precision el hecho, su encuadre y el estado del proceso."
        )

    intent_note = f" El objetivo declarado es: {detected_intent}." if detected_intent else ""
    return f"El caso se encuadra en materia de {legal_area or 'derecho civil'}.{intent_note}"


def _build_scenarios(
    *,
    legal_area: str,
    has_agreement: bool,
    is_urgent: bool,
    has_blocking: bool,
    blocking_factors: str,
    has_children: bool,
) -> list[dict]:
    area = (legal_area or "").lower()

    if "divorcio" in area:
        return _scenarios_divorcio(
            has_agreement=has_agreement,
            is_urgent=is_urgent,
            has_blocking=has_blocking,
            blocking_factors=blocking_factors,
            has_children=has_children,
        )

    if "alimentos" in area:
        return _scenarios_alimentos(
            is_urgent=is_urgent,
            has_blocking=has_blocking,
            blocking_factors=blocking_factors,
        )

    if "laboral" in area or "trabajo" in area:
        return _scenarios_laboral(
            is_urgent=is_urgent,
            has_blocking=has_blocking,
        )

    return _scenarios_generic(
        has_agreement=has_agreement,
        is_urgent=is_urgent,
        has_blocking=has_blocking,
        blocking_factors=blocking_factors,
    )


def _scenarios_divorcio(
    *,
    has_agreement: bool,
    is_urgent: bool,
    has_blocking: bool,
    blocking_factors: str,
    has_children: bool,
) -> list[dict]:
    del is_urgent
    blocking_note = (
        f" Existe un bloqueo procesal ({blocking_factors}) que puede demorar la definicion."
        if has_blocking
        else ""
    )
    children_note = (
        " Si hay hijos menores, el convenio debe contemplar cuidado, comunicacion y alimentos."
        if has_children
        else ""
    )

    consensual_viability = "baja" if has_blocking else ("alta" if has_agreement else "media")
    unilateral_viability = "media" if has_blocking else "alta"

    return [
        {
            "name": "Divorcio consensuado",
            "description": (
                "Ambas partes presentan un convenio regulador conjunto. "
                "Suele bajar el nivel de conflicto cuando el acuerdo ya esta encaminado."
                f"{children_note}{blocking_note}"
            ),
            "viability": consensual_viability,
            "risk": "bajo" if has_agreement else "medio",
            "recommended": False,
            "response_speed": "alta",
            "agreement_dependency": "alta",
            "blocking_sensitivity": "alta",
        },
        {
            "name": "Divorcio unilateral",
            "description": (
                "Uno de los conyuges impulsa la peticion sin depender de un acuerdo total previo. "
                "Permite avanzar aunque luego deban discutirse aspectos accesorios."
                f"{blocking_note}"
            ),
            "viability": unilateral_viability,
            "risk": "medio" if has_blocking else "bajo",
            "recommended": False,
            "response_speed": "media",
            "agreement_dependency": "baja",
            "blocking_sensitivity": "media",
        },
        {
            "name": "Mediacion previa",
            "description": (
                "Abrir una instancia de dialogo antes de judicializar el conflicto. "
                "Puede ayudar a ordenar un convenio, pero depende de la colaboracion de ambas partes."
                f"{blocking_note}"
            ),
            "viability": "baja" if has_blocking else ("media" if has_agreement else "media"),
            "risk": "bajo" if has_agreement else "medio",
            "recommended": False,
            "response_speed": "baja",
            "agreement_dependency": "alta",
            "blocking_sensitivity": "media",
        },
    ]


def _scenarios_alimentos(
    *,
    is_urgent: bool,
    has_blocking: bool,
    blocking_factors: str,
) -> list[dict]:
    blocking_note = f" Bloqueo procesal detectado: {blocking_factors}." if has_blocking else ""

    return [
        {
            "name": "Cuota alimentaria incidental",
            "description": (
                "Pedir alimentos dentro de un expediente en curso o como medida de respuesta inmediata. "
                "Suele ser la via mas veloz cuando hay necesidad actual."
                f"{blocking_note}"
            ),
            "viability": "media" if has_blocking else "alta",
            "risk": "bajo",
            "recommended": False,
            "response_speed": "alta",
            "agreement_dependency": "baja",
            "blocking_sensitivity": "media",
        },
        {
            "name": "Juicio autonomo de alimentos",
            "description": (
                "Iniciar un reclamo de alimentos por una via independiente. "
                "Da un marco mas completo cuando no hay otro expediente utilizable."
                f"{blocking_note}"
            ),
            "viability": "media" if has_blocking else "alta",
            "risk": "medio" if has_blocking else "bajo",
            "recommended": False,
            "response_speed": "media",
            "agreement_dependency": "baja",
            "blocking_sensitivity": "alta",
        },
        {
            "name": "Intimacion extrajudicial de pago",
            "description": (
                "Requerir el cumplimiento por una via previa y documentada antes de judicializar. "
                "Puede ser util para ordenar el reclamo, pero depende de la respuesta de la otra parte."
                f"{blocking_note}"
            ),
            "viability": "baja" if is_urgent or has_blocking else "media",
            "risk": "medio",
            "recommended": False,
            "response_speed": "baja" if is_urgent else "media",
            "agreement_dependency": "alta",
            "blocking_sensitivity": "media",
        },
    ]


def _scenarios_laboral(*, is_urgent: bool, has_blocking: bool) -> list[dict]:
    del is_urgent
    return [
        {
            "name": "Conciliacion laboral (SECLO)",
            "description": (
                "Instancia conciliatoria previa para intentar una solucion rapida antes del juicio. "
                "Es util cuando todavia hay margen de negociacion."
            ),
            "viability": "media" if has_blocking else "alta",
            "risk": "bajo",
            "recommended": False,
            "response_speed": "alta",
            "agreement_dependency": "alta",
            "blocking_sensitivity": "media",
        },
        {
            "name": "Demanda laboral",
            "description": (
                "Accion judicial por despido, diferencias salariales u otros incumplimientos. "
                "Permite sostener el reclamo aun si la otra parte no coopera."
            ),
            "viability": "media" if has_blocking else "alta",
            "risk": "medio",
            "recommended": False,
            "response_speed": "media",
            "agreement_dependency": "baja",
            "blocking_sensitivity": "media",
        },
    ]


def _scenarios_generic(
    *,
    has_agreement: bool,
    is_urgent: bool,
    has_blocking: bool,
    blocking_factors: str,
) -> list[dict]:
    blocking_note = f" Existe un bloqueo actual: {blocking_factors}." if has_blocking else ""

    return [
        {
            "name": "Via consensuada / extrajudicial",
            "description": (
                "Buscar una solucion acordada o una gestion previa al litigio. "
                "Puede ordenar el conflicto con menor desgaste cuando hay predisposicion."
                f"{blocking_note}"
            ),
            "viability": "alta" if has_agreement and not has_blocking else ("media" if has_agreement else "baja" if is_urgent else "media"),
            "risk": "bajo",
            "recommended": False,
            "response_speed": "media" if has_agreement else "baja",
            "agreement_dependency": "alta",
            "blocking_sensitivity": "media",
        },
        {
            "name": "Via judicial / unilateral",
            "description": (
                "Iniciar la accion correspondiente para avanzar sin depender de un acuerdo previo."
                f"{blocking_note}"
            ),
            "viability": "media" if has_blocking else "alta",
            "risk": "alto" if has_blocking else "medio",
            "recommended": False,
            "response_speed": "media" if has_blocking else "alta",
            "agreement_dependency": "baja",
            "blocking_sensitivity": "media",
        },
    ]


def _score_scenario(
    scenario: dict,
    *,
    is_urgent: bool,
    has_agreement: bool,
    has_blocking: bool,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    viability = str(scenario.get("viability") or "baja").strip().lower()
    risk = str(scenario.get("risk") or "medio").strip().lower()
    response_speed = str(scenario.get("response_speed") or "media").strip().lower()
    agreement_dependency = str(scenario.get("agreement_dependency") or "media").strip().lower()
    blocking_sensitivity = str(scenario.get("blocking_sensitivity") or "media").strip().lower()

    viability_score = VIABILITY_SCORES.get(viability, 0)
    risk_score = RISK_SCORES.get(risk, 0)
    speed_score = SPEED_SCORES.get(response_speed, 1)

    score += viability_score
    score += risk_score

    if viability == "alta":
        reasons.append("mantiene buena viabilidad comparativa")
    elif viability == "media":
        reasons.append("presenta una viabilidad intermedia")
    else:
        reasons.append("su viabilidad aparece condicionada")

    if risk == "bajo":
        reasons.append("muestra un riesgo relativamente bajo")
    elif risk == "alto":
        reasons.append("expone un riesgo mayor")

    if is_urgent:
        urgency_bonus = speed_score * 2
        score += urgency_bonus
        if response_speed == "alta":
            reasons.append("responde mejor a la urgencia")
        elif response_speed == "baja":
            reasons.append("no es la via mas rapida para un contexto urgente")
    else:
        score += speed_score

    if agreement_dependency == "alta":
        if has_agreement:
            score += 2
            reasons.append("puede aprovechar el acuerdo ya disponible")
        else:
            score -= AGREEMENT_DEPENDENCY_PENALTIES["alta"]
            reasons.append("depende demasiado de la colaboracion de la otra parte")
        if is_urgent:
            score -= 2
    elif agreement_dependency == "media":
        if has_agreement:
            score += 1
        elif is_urgent:
            score -= 1

    if agreement_dependency == "baja" and not has_agreement:
        score += 2
        reasons.append("permite avanzar aun sin acuerdo")

    if has_blocking:
        blocking_penalty = BLOCKING_PENALTIES.get(blocking_sensitivity, 2)
        score -= blocking_penalty
        if blocking_sensitivity == "alta":
            reasons.append("se ve especialmente afectado por el bloqueo actual")
        else:
            reasons.append("debe leerse con prudencia por el bloqueo procesal")
    elif blocking_sensitivity == "baja":
        score += 1

    return score, _dedupe_reasons(reasons)


def _select_recommended_scenario(
    *,
    scenarios: list[dict],
    is_urgent: bool,
    has_agreement: bool,
    has_blocking: bool,
) -> list[dict]:
    if not scenarios:
        return []

    scored: list[dict] = []
    for index, scenario in enumerate(scenarios):
        scenario_copy = dict(scenario)
        scenario_copy["recommended"] = False
        score, reasons = _score_scenario(
            scenario_copy,
            is_urgent=is_urgent,
            has_agreement=has_agreement,
            has_blocking=has_blocking,
        )
        scenario_copy["score"] = score
        scenario_copy["score_reasons"] = reasons
        scenario_copy["_selection_index"] = index
        scored.append(scenario_copy)

    best = max(
        scored,
        key=lambda scenario: (
            int(scenario.get("score", 0)),
            VIABILITY_SCORES.get(str(scenario.get("viability") or "baja").lower(), 0),
            RISK_SCORES.get(str(scenario.get("risk") or "medio").lower(), 0),
            SPEED_SCORES.get(str(scenario.get("response_speed") or "media").lower(), 1),
            -int(scenario.get("_selection_index", 0)),
        ),
    )

    best_index = int(best.get("_selection_index", 0))
    result: list[dict] = []
    for scenario in scored:
        cleaned = dict(scenario)
        cleaned["recommended"] = int(cleaned.get("_selection_index", -1)) == best_index
        cleaned.pop("_selection_index", None)
        result.append(cleaned)
    return result


def _build_recommended_strategy(
    scenarios: list[dict],
    *,
    is_urgent: bool,
    has_agreement: bool,
    has_blocking: bool,
) -> str:
    recommended = next((scenario for scenario in scenarios if scenario.get("recommended")), None)
    if not recommended:
        return ""

    name = str(recommended.get("name") or "estrategia principal").strip()
    viability = str(recommended.get("viability") or "").strip()
    risk = str(recommended.get("risk") or "").strip()
    reasons = list(recommended.get("score_reasons") or [])

    explanation_parts: list[str] = []
    if is_urgent:
        if str(recommended.get("response_speed") or "").strip().lower() == "alta":
            explanation_parts.append("da una respuesta mas rapida frente a la urgencia")
        else:
            explanation_parts.append("permite avanzar sin demoras evitables")
    if has_agreement and str(recommended.get("agreement_dependency") or "").strip().lower() == "alta":
        explanation_parts.append("aprovecha el acuerdo ya alcanzado")
    if (not has_agreement) and str(recommended.get("agreement_dependency") or "").strip().lower() == "baja":
        explanation_parts.append("no depende del acuerdo de la otra parte")
    if has_blocking:
        explanation_parts.append("mantiene un margen de accion mas prudente pese al bloqueo actual")

    for reason in reasons:
        if len(explanation_parts) >= 2:
            break
        if reason not in explanation_parts:
            explanation_parts.append(reason)

    strategy = f"Se recomienda priorizar {name}"
    if explanation_parts:
        strategy += " porque " + " y ".join(explanation_parts[:2]) + "."
    else:
        strategy += "."

    meta_parts: list[str] = []
    if viability:
        meta_parts.append(f"viabilidad {viability}")
    if risk:
        meta_parts.append(f"riesgo {risk}")
    if meta_parts:
        strategy += " " + ", ".join(meta_parts).capitalize() + "."

    return strategy


def _compute_confidence(
    *,
    legal_area: str,
    facts: str,
    has_blocking: bool,
    scenarios: list[dict],
    procedural_posture: str,
) -> float:
    confidence = 0.5

    if legal_area:
        confidence += 0.15
    if facts and len(facts) > 50:
        confidence += 0.10
    if procedural_posture:
        confidence += 0.05
    if len(scenarios) >= 2:
        confidence += 0.10
    if has_blocking:
        confidence -= 0.15

    return round(max(0.1, min(0.95, confidence)), 2)


def format_legal_reasoning_as_text(reasoning: dict) -> str:
    """
    Convierte el dict de razonamiento juridico en texto natural para insertar en la respuesta,
    ubicado antes de los pasos practicos.
    """
    if not reasoning:
        return ""

    parts: list[str] = []
    scenarios = reasoning.get("scenarios") or []
    recommended = next((scenario for scenario in scenarios if scenario.get("recommended")), None)
    if recommended:
        parts.append(f"Estrategia recomendada: {recommended.get('name', 'estrategia principal')}.")

    legal_framing = str(reasoning.get("legal_framing") or "").strip()
    if legal_framing:
        parts.append(f"Encuadre juridico: {legal_framing}")

    if scenarios:
        lines = ["Escenarios posibles:"]
        for index, scenario in enumerate(scenarios, 1):
            name = scenario.get("name", f"Escenario {index}")
            viability = scenario.get("viability", "")
            risk = scenario.get("risk", "")
            description = scenario.get("description", "")
            is_recommended = bool(scenario.get("recommended"))

            rec_marker = " (recomendado)" if is_recommended else ""
            meta_parts = []
            if viability:
                meta_parts.append(f"viabilidad {viability}")
            if risk:
                meta_parts.append(f"riesgo {risk}")
            meta_str = f" [{', '.join(meta_parts)}]" if meta_parts else ""

            lines.append(f"{index}. {name}{meta_str}{rec_marker}")
            if description:
                lines.append(f"   {description}")

        parts.append("\n".join(lines))

    recommended_strategy = str(reasoning.get("recommended_strategy") or "").strip()
    if recommended_strategy:
        parts.append(f"Desarrollo de la estrategia recomendada: {recommended_strategy}")

    return "\n\n".join(parts)


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for reason in reasons:
        normalized = str(reason or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(reason).strip())
    return result
